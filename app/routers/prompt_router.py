"""نقاط النهاية الخاصة بمحرك البرومبتات: توليد، تحسين، أطر، اقتراح."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session as OrmSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import PromptHistory, User
from app.schemas import (
    PromptEnhanceRequest,
    PromptGenerateRequest,
    SuggestFrameworkResponse,
)
from app.services.llm_client import LLMError, chat_completion
from app.services.prompt_engine import (
    DEFAULT_FRAMEWORK,
    SYSTEM_PROMPT,
    generate_prompt,
    list_frameworks,
    list_tools,
    suggest_framework,
)

logger = logging.getLogger("promptcraft.prompt")

router = APIRouter(prefix="/api/prompt", tags=["prompt"])


@router.post(
    "/generate",
    summary="توليد برومبت من وصف خام",
    responses={
        401: {"description": "يجب تسجيل الدخول"},
        400: {"description": "الوصف فارغ أو غير صالح"},
        502: {"description": "فشل الاتصال بـ OpenRouter"},
        503: {"description": "مفتاح OpenRouter غير مضبوط"},
    },
)
async def generate(
    payload: PromptGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> dict:
    """
    يحوّل وصفًا خامًا إلى برومبت مهيكَل ثم يحفظه في سجل المستخدم.

    المصادقة إلزامية، والحفظ اختياري عبر `save`.
    """
    logger.info(
        "طلب توليد من %s — أداة %s، إطار %s، لغة %s",
        current_user.username, payload.tool, payload.framework, payload.language,
    )

    try:
        result = await generate_prompt(
            raw_input=payload.input,
            tool=payload.tool,
            framework=payload.framework,
            language=payload.language,
        )
    except LLMError as exc:
        logger.warning("فشل التوليد (%s): %s", exc.status_code, exc.message)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    saved = False
    history_id = None
    if payload.save:
        entry = PromptHistory(
            user_id=current_user.id,
            raw_input=payload.input,
            generated_prompt=result["prompt"],
            tool=result["tool"],
            framework=result["framework"],
            language=result["language"],
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        saved = True
        history_id = entry.id
        logger.info("حُفظ البرومبت رقم %s للمستخدم %s", entry.id, current_user.username)

    return {
        "success": True,
        **result,
        "saved": saved,
        "history_id": history_id,
        "created_at": None,
    }


@router.post(
    "/enhance",
    summary="تحسين برومبت موجود",
    responses={
        401: {"description": "يجب تسجيل الدخول"},
        502: {"description": "فشل الاتصال بـ OpenRouter"},
        503: {"description": "مفتاح OpenRouter غير مضبوط"},
    },
)
async def enhance(
    payload: PromptEnhanceRequest,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> dict:
    """
    يأخذ برومبتًا قائمًا ويعيد صياغة أقوى.

    يحدد الثغرات الشائعة: غموض الهدف، غياب الجمهور والنبرة، عدم تحديد حدود المخرج،
    وعدم وجود معيار للنجاح.
    """
    logger.info("طلب تحسين من %s (%s حرف)", current_user.username, len(payload.prompt))

    # وضع التجربة: نعيد البرومبت مع ملاحظات تحسين ثابتة بدون اتصال
    if settings.PROMPT_MOCK:
        improved = _mock_enhance(payload.prompt)
        return {
            "success": True,
            "prompt": improved,
            "original": payload.prompt,
            "language": payload.language,
            "mock_used": True,
            "tokens_used": max(1, round(len(improved) / 4)),
            "model": "mock",
            "saved": False,
            "history_id": None,
        }

    if not settings.openrouter_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "مفتاح OpenRouter غير مضبوط. أضف OPENROUTER_API_KEY في ملف .env ثم "
                "أعد تشغيل الخادم. (تجده في: https://openrouter.ai/keys)"
            ),
        )

    language_line = (
        "حسّن البرومبت بالعربية الفصحى المبسّطة."
        if payload.language == "ar"
        else "Improve the prompt in clear professional English."
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "هذا برومبت موجود:\n"
                f"<<<\n{payload.prompt.strip()}\n>>>\n\n"
                "حسّنه وفق القواعد التالية:\n"
                "1. حدّد الهدف بنية واضحة ومعيار نجاح قابل للقياس.\n"
                "2. أضف الجمهور والنبرة إن غابتا.\n"
                "3. ضع حدودًا للمخرج (طول، صيغة، عدد عناصر) إن كانت غائبة.\n"
                "4. استبدل المبهمات بأرقام أو أمثلة ملموسة.\n"
                "5. احذف التكرار والحشو.\n"
                f"{language_line}\n\n"
                "أعد البرومبت المحسَّن بصيغة Markdown فقط، بدون شرح لما غيّرته."
            ),
        },
    ]

    try:
        improved_text = await chat_completion(
            messages=messages,
            model=settings.OPENROUTER_MODEL,
            temperature=0.5,
        )
    except LLMError as exc:
        logger.warning("فشل التحسين (%s): %s", exc.status_code, exc.message)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    improved = improved_text.strip()

    saved = False
    history_id = None
    if payload.save:
        entry = PromptHistory(
            user_id=current_user.id,
            raw_input=payload.prompt,
            generated_prompt=improved,
            tool="enhance",
            framework=DEFAULT_FRAMEWORK,
            language=payload.language,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        saved = True
        history_id = entry.id

    return {
        "success": True,
        "prompt": improved,
        "original": payload.prompt,
        "language": payload.language,
        "mock_used": False,
        "tokens_used": max(1, round(len(improved) / 4)),
        "model": settings.OPENROUTER_MODEL,
        "saved": saved,
        "history_id": history_id,
    }


@router.get("/frameworks", summary="الأطر والأدوات المتاحة")
def frameworks(current_user: User = Depends(get_current_user)) -> dict:
    """
    تعيد كل الأطر والأدوات التي يدعمها المحرك — تستخدمها الواجهة لملء القوائم.
    """
    return {
        "success": True,
        "default_framework": DEFAULT_FRAMEWORK,
        "default_tool": "general",
        "mock_mode": settings.PROMPT_MOCK,
        "ready": settings.openrouter_ready or settings.PROMPT_MOCK,
        "model": "mock" if settings.PROMPT_MOCK else settings.OPENROUTER_MODEL,
        "frameworks": list_frameworks(),
        "tools": list_tools(),
    }


@router.get(
    "/suggest",
    response_model=SuggestFrameworkResponse,
    summary="اقتراح الإطار الأنسب لنص معيّن",
)
def suggest(
    text: str = Query(
        ...,
        min_length=1,
        max_length=1000,
        description="النص المراد تحليله",
        examples=["اكتب لي مقال تسويقي عن"],
    ),
    current_user: User = Depends(get_current_user),
) -> SuggestFrameworkResponse:
    """
    تحلّل الكلمات المفتاحية في النص وتقترح الإطار الأنسب.

    سريع ومحلي بالكامل — بلا اتصال بـ OpenRouter.
    """
    suggestion = suggest_framework(text)
    logger.info(
        "اقتراح إطار لـ %s: %s (ثقة %s)",
        current_user.username, suggestion["framework"], suggestion["confidence"],
    )

    return SuggestFrameworkResponse(
        text=text,
        framework=suggestion["framework"],
        framework_name=suggestion["name_ar"],
        reason_ar=suggestion["reason_ar"],
        confidence=suggestion["confidence"],
        alternatives=suggestion["alternatives"],
    )


@router.get("/history", summary="سجل برومبتات المستخدم الحالي")
def history(
    limit: int = Query(default=20, ge=1, le=100, description="أقصى عدد عناصر"),
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> dict:
    """آخر برومبتات أنشأها المستخدم الحالي."""
    rows = db.scalars(
        select(PromptHistory)
        .where(PromptHistory.user_id == current_user.id)
        .order_by(desc(PromptHistory.created_at))
        .limit(limit)
    ).all()

    return {
        "success": True,
        "total": len(rows),
        "items": [
            {
                "id": row.id,
                "raw_input": row.raw_input,
                "generated_prompt": row.generated_prompt,
                "tool": row.tool,
                "framework": row.framework,
                "language": row.language,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.delete("/history", summary="حذف سجل البرومبتات")
def clear_history(
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> dict:
    """يحذف كل سجلات المستخدم الحالي فقط."""
    rows = db.scalars(
        select(PromptHistory).where(PromptHistory.user_id == current_user.id)
    ).all()
    for row in rows:
        db.delete(row)
    db.commit()

    logger.info("حُذف %s سجل برومبت للمستخدم %s", len(rows), current_user.username)
    return {"success": True, "deleted": len(rows)}


def _mock_enhance(prompt: str) -> str:
    """نسخة محسَّنة ثابتة لوضع التجربة — تُبرز الأقسام المفقودة فقط."""
    missing = []
    lowered = prompt.lower()
    checks = {
        "الجمهور المستهدف": ("الجمهور", "audience", "لجمهور"),
        "النبرة": ("النبرة", "tone", "بأسلوب"),
        "معيار النجاح": ("معيار", "مقياس", "بنسبة", "لا يقل", "success"),
        "حدود المخرج": ("كلمات", "أحرف", "عناصر", "حدود", "بحد أقصى", "حد أقصى", "words"),
    }
    for label, keys in checks.items():
        if not any(k in lowered for k in keys):
            missing.append(label)

    lines = [prompt.strip(), "", "---", "", "## إضافات مقترحة", ""]
    if missing:
        lines.append("الأقسام التالية غير موجودة في البرومبت الأصلي:")
        lines.extend(f"- **{item}**: أضف قسمًا يحمل هذا المعيار" for item in missing)
        lines.append("")
    lines.append("- **معيار النجاح**: حدّد كيف يُعرف أن المخرج ناجح (رقم، نسبة، أو قائمة شروط).")
    lines.append("- **حدود المخرج**: اذكر الطول أو عدد العناصر أو الصيغة المطلوبة.")
    lines.append("")
    lines.append(
        f"> هذا التحسين في وضع التجربة (`PROMPT_MOCK=true`). فعّله "
        f"`false` في `.env` لتحسين حقيقي عبر OpenRouter."
    )
    return "\n".join(lines)