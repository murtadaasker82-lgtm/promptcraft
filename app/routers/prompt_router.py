"""نقاط النهاية الخاصة بمحرك البرومبتات: توليد، تحسين، أطر، اقتراح، ومكتبة السجل."""

import logging
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session as OrmSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import PromptHistory, User, utcnow
from app.schemas import (
    PromptEnhanceRequest,
    PromptGenerateRequest,
    PromptListItem,
    PromptListResponse,
    PromptStats,
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

# مكتبة البرومبتات — مسار منفصل `/api/prompts` عن محرك التوليد `/api/prompt`
library_router = APIRouter(prefix="/api/prompts", tags=["prompts"])


def _owned_prompt(db: OrmSession, prompt_id: int, user: User) -> PromptHistory:
    """
    يُعيد البرومبت بعد التأكد من ملكيته للمستخدم الحالي.

    نستعلم بالـ id والمستخدم معًا بدل جلب ثم مقارنة — فلا يمكن لأي مستخدم أن
    يستكشف وجود برومبتات غيره بتخمين المعرّفات، ويُرجع 404 (لا 403) حتى لا
    نكشف الفرق بين "غير موجود" و"موجود لكنه ليس لك".
    """
    row = db.scalar(
        select(PromptHistory).where(
            PromptHistory.id == prompt_id,
            PromptHistory.user_id == user.id,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="البرومبت غير موجود",
        )
    return row


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


# ============================================================
# مكتبة البرومبتات — قراءة سجل المستخدم وحذفه
# ============================================================
#
# ترتيب المسارات هنا مقصود: `/stats` مُعرَّف **قبل** `/{prompt_id}`، لأن
# FastAPI يطابق المسار بالترتيب — فلو سبق `/{prompt_id}` لحاول تحويل "stats"
# إلى int وفشل بـ 422 بدل الوصول إلى نقطة الإحصاءات.


@library_router.get(
    "",
    response_model=PromptListResponse,
    summary="سجل برومبتات المستخدم مع بحث وتصفية وترقيم صفحات",
)
def list_prompts(
    search: str | None = Query(
        default=None,
        max_length=200,
        description="نص يُبحث عنه في الوصف الخام وفي البرومبت الناتج",
        examples=["تنين"],
    ),
    tool: str | None = Query(default=None, max_length=32, description="تصفية بالأداة"),
    framework: str | None = Query(default=None, max_length=32, description="تصفية بالإطار"),
    sort: Literal["newest", "oldest"] = Query(
        default="newest",
        description="ترتيب النتائج زمنيًا: الأحدث أولًا أو الأقدم أولًا",
    ),
    limit: int = Query(default=20, ge=1, le=100, description="عدد العناصر في الصفحة"),
    offset: int = Query(default=0, ge=0, description="عدد العناصر المتخطّاة"),
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> PromptListResponse:
    """صفحة واحدة من سجل المستخدم، مع عدد إجمالي يطابق نفس عوامل التصفية."""
    conditions = [PromptHistory.user_id == current_user.id]

    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                PromptHistory.raw_input.ilike(pattern),
                PromptHistory.generated_prompt.ilike(pattern),
            )
        )
    if tool:
        conditions.append(PromptHistory.tool == tool)
    if framework:
        conditions.append(PromptHistory.framework == framework)

    # total يحسب النتائج بعد التصفية (لا الإجمالي الكلي) وإلا لم يطابق عدد الصفحات
    total = db.scalar(
        select(func.count()).select_from(PromptHistory).where(*conditions)
    ) or 0

    # الترتيب على (created_at, id) معًا حتى لا تتأرجح العناصر المتساوية زمنًا
    # بين صفحتين متتاليتين ويتكرر عنصر أو يُفقد آخر
    primary = desc if sort == "newest" else asc

    rows = db.scalars(
        select(PromptHistory)
        .where(*conditions)
        .order_by(primary(PromptHistory.created_at), primary(PromptHistory.id))
        .limit(limit)
        .offset(offset)
    ).all()

    logger.info(
        "استعراض سجل %s — %s عنصر (بحث=%s، أداة=%s، إطار=%s، ترتيب=%s)",
        current_user.username, len(rows), search, tool, framework, sort,
    )

    return PromptListResponse(
        items=[PromptListItem.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@library_router.get(
    "/stats",
    response_model=PromptStats,
    summary="إحصاءات سجل المستخدم",
)
def prompt_stats(
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> PromptStats:
    """عدد البرومبتات الكلي وموزّعها على الأدوات والأطر ونشاط آخر 7 أيام."""
    owned = PromptHistory.user_id == current_user.id

    total = db.scalar(
        select(func.count()).select_from(PromptHistory).where(owned)
    ) or 0

    tool_rows = db.execute(
        select(PromptHistory.tool, func.count())
        .where(owned)
        .group_by(PromptHistory.tool)
    ).all()
    framework_rows = db.execute(
        select(PromptHistory.framework, func.count())
        .where(owned)
        .group_by(PromptHistory.framework)
    ).all()

    since = utcnow() - timedelta(days=7)
    last_7_days = db.scalar(
        select(func.count())
        .select_from(PromptHistory)
        .where(owned, PromptHistory.created_at >= since)
    ) or 0

    return PromptStats(
        total=total,
        by_tool=dict(tool_rows),
        by_framework=dict(framework_rows),
        last_7_days=last_7_days,
    )


@library_router.get(
    "/{prompt_id}",
    response_model=PromptListItem,
    summary="برومبت واحد بالمعرّف",
    responses={404: {"description": "لا يوجد برومبت بهذا المعرّف لهذا المستخدم"}},
)
def get_prompt(
    prompt_id: int,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> PromptListItem:
    """يعيد برومبتًا واحدًا — ويقبل فقط ما يملكه المستخدم الحالي."""
    row = _owned_prompt(db, prompt_id, current_user)
    return PromptListItem.model_validate(row)


@library_router.delete(
    "/{prompt_id}",
    summary="حذف برومبت",
    responses={404: {"description": "لا يوجد برومبت بهذا المعرّف لهذا المستخدم"}},
)
def delete_prompt(
    prompt_id: int,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> dict:
    """يحذف برومبتًا واحدًا — ويقبل فقط ما يملكه المستخدم الحالي."""
    row = _owned_prompt(db, prompt_id, current_user)
    db.delete(row)
    db.commit()

    logger.info("حُذف البرومبت %s بواسطة %s", prompt_id, current_user.username)
    return {"success": True, "deleted": 1, "id": prompt_id}