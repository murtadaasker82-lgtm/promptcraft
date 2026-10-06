"""نقاط النهاية الخاصة بالصوت: رفع ملف + تفريغه إلى نص."""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session as OrmSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import User
from app.services.transcription import TranscriptionError, transcribe_audio

logger = logging.getLogger("promptcraft.audio")

router = APIRouter(prefix="/api", tags=["audio"])


@router.post(
    "/transcribe",
    summary="تفريغ ملف صوتي إلى نص (Whisper)",
    responses={
        401: {"description": "يجب تسجيل الدخول"},
        413: {"description": "الملف أكبر من 25 ميجابايت"},
        415: {"description": "صيغة غير مدعومة"},
        500: {"description": "خطأ داخلي"},
        502: {"description": "فشل الاتصال بخدمة OpenAI"},
        503: {"description": "مفتاح OpenAI غير مضبوط"},
    },
)
async def transcribe(
    file: UploadFile = File(..., description="الملف الصوتي (mp3, m4a, wav, webm, ogg)"),
    language: str | None = Form(default=None, description="ar أو en — اتركه فارغًا للكشف"),
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> dict:
    """
    يستقبل ملفًا صوتيًا ويعيد نصه.

    الملف يُحفظ مؤقتًا في `data/uploads/` ويُحذف فور انتهاء التفريغ.
    المصادقة إلزامية: كل طلب مربوط بمستخدم عبر `get_current_user`.
    """
    logger.info(
        "طلب تفريغ من %s: %s (%s)",
        current_user.username,
        file.filename,
        file.content_type,
    )

    # فحص الحجم قبل القراءة الكاملة (يتحقق Starlette من content-length)
    declared_size = getattr(file, "size", None)
    if declared_size and declared_size > settings.max_upload_bytes:
        await file.close()
        size_mb = declared_size / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"حجم الملف {size_mb:.1f} ميجابايت، والحد الأقصى "
                f"{settings.MAX_UPLOAD_MB} ميجابايت"
            ),
        )

    try:
        file_bytes = await file.read()
    finally:
        await file.close()

    try:
        result = await transcribe_audio(
            file_bytes=file_bytes,
            filename=file.filename or "audio",
            language=language or None,
        )
    except TranscriptionError as exc:
        logger.warning("فشل التفريغ (%s): %s", exc.status_code, exc.message)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "success": True,
        "text": result.text,
        "language": result.language,
        "filename": result.filename,
        "size_bytes": result.size_bytes,
        "model": result.model,
        "duration_estimate_sec": result.duration_estimate_sec,
        "segments": result.segments,
        "mock": result.model == "mock",
    }


@router.get("/transcribe/info", summary="معلومات خدمة التفريغ")
def transcribe_info(current_user: User = Depends(get_current_user)) -> dict:
    """ما الذي يدعمه الرفع حاليًا — تستخدمه الواجهة لعرض الرسائل."""
    return {
        "success": True,
        "ready": settings.openai_ready or settings.WHISPER_MOCK,
        "mock_mode": settings.WHISPER_MOCK,
        "model": "mock" if settings.WHISPER_MOCK else settings.WHISPER_MODEL,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "max_upload_bytes": settings.max_upload_bytes,
        "allowed_extensions": settings.ALLOWED_AUDIO_EXTENSIONS,
        "hint": (
            "وضع التجربة مفعّل (WHISPER_MOCK=true)"
            if settings.WHISPER_MOCK
            else (
                "جاهز للتفريغ الحقيقي"
                if settings.openai_ready
                else "أضف OPENAI_API_KEY في .env لتشغيل التفريغ الحقيقي"
            )
        ),
    }
