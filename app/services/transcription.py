"""تفريغ الصوت إلى نص باستخدام OpenAI Whisper."""

import asyncio
import io
import logging
import random
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path

import aiofiles
from openai import APIConnectionError, APIError, AsyncOpenAI, RateLimitError

from app.config import settings

logger = logging.getLogger("promptcraft.transcription")


class TranscriptionError(Exception):
    """خطأ في التفريغ — يحمل رمز HTTP ورسالة عربية جاهزة للعرض."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class TranscriptionResult:
    """نتيجة تفريغ ملف صوتي."""

    text: str
    language: str | None = None
    filename: str = ""
    size_bytes: int = 0
    model: str = "whisper-1"
    duration_estimate_sec: float | None = None
    segments: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "model": self.model,
            "duration_estimate_sec": self.duration_estimate_sec,
            "segments": self.segments,
        }


def get_extension(filename: str) -> str:
    """امتداد الملف بحروف صغيرة، مع الرجوع لـ '' عند غيابه."""
    return Path(filename or "").suffix.lower()


def validate_audio(filename: str, size_bytes: int) -> str:
    """
    يتحقق من نوع الملف وحجمه قبل أي اتصال بـ OpenAI.

    يرفع TranscriptionError بالرمز المناسب:
      * 415 — صيغة غير مدعومة
      * 413 — الحجم أكبر من 25 ميجابايت
    """
    ext = get_extension(filename)
    allowed = {e.lower() for e in settings.ALLOWED_AUDIO_EXTENSIONS}

    if not ext:
        raise TranscriptionError(
            "الملف بدون امتداد — تأكد أنه ملف صوتي (mp3, m4a, wav, webm, ogg)",
            status_code=415,
        )

    if ext not in allowed:
        raise TranscriptionError(
            f"الصيغة {ext} غير مدعومة. الصيغ المقبولة: "
            f"{', '.join(sorted(allowed))}",
            status_code=415,
        )

    if size_bytes <= 0:
        raise TranscriptionError("الملف فارغ — لا يوجد ما يُفرَّغ", status_code=415)

    if size_bytes > settings.max_upload_bytes:
        size_mb = size_bytes / (1024 * 1024)
        raise TranscriptionError(
            f"حجم الملف {size_mb:.1f} ميجابايت، والحد الأقصى "
            f"{settings.MAX_UPLOAD_MB} ميجابايت",
            status_code=413,
        )

    return ext


def _wav_duration(file_bytes: bytes) -> float | None:
    """مدة ملف WAV بدقة من ترويسته (بدون ffprobe)."""
    try:
        with wave.open(io.BytesIO(file_bytes), "rb") as w:
            rate = w.getframerate()
            if rate:
                return round(w.getnframes() / rate, 1)
    except Exception:  # noqa: BLE001 — ترويسة تالفة
        return None
    return None


def _estimate_duration(size_bytes: int, ext: str, file_bytes: bytes | None = None) -> float:
    """تقدير تقريبي للمدة — للعرض فقط (لا نعرف البت‑ريت بدون ffprobe)."""
    if ext == ".wav" and file_bytes:
        exact = _wav_duration(file_bytes)
        if exact is not None:
            return exact

    bitrate_kbps = {
        ".mp3": 128,
        ".mp4": 128,
        ".m4a": 128,
        ".mpeg": 128,
        ".mpga": 128,
        ".wav": 256,
        ".flac": 1000,
        ".ogg": 128,
        ".webm": 128,
    }.get(ext, 128)
    return round((size_bytes * 8) / (bitrate_kbps * 1000), 1)


async def _save_temp_upload(file_bytes: bytes, filename: str) -> Path:
    """يحفظ الملف مؤقتًا في data/uploads/ (لأن Whisper يحتاج مسار ملف)."""
    ext = get_extension(filename) or ".bin"
    temp_path = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"

    async with aiofiles.open(temp_path, "wb") as f:
        await f.write(file_bytes)

    logger.debug("حُفظ مؤقتًا: %s (%s bytes)", temp_path.name, len(file_bytes))
    return temp_path


def _delete_temp_upload(path: Path | None) -> None:
    """يحذف الملف المؤقت — يُستدعى دائمًا حتى عند الفشل."""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("تعذّر حذف الملف المؤقت: %s", path)


def _mock_transcript(
    filename: str, size_bytes: int, ext: str, file_bytes: bytes | None = None
) -> TranscriptionResult:
    """نص وهمي لوضع التجربة (WHISPER_MOCK=true) بدون أي اتصال خارجي."""
    duration = _estimate_duration(size_bytes, ext, file_bytes)

    return TranscriptionResult(
        text=(
            "[وضع التجربة] هذا نص وهمي لمعاينة المسار فقط. "
            "لتفعيل التفريغ الحقيقي: ضع OPENAI_API_KEY في ملف .env "
            "ثم أعد تشغيل الخادم. "
            f"(الملف: {filename} · المدة التقديرية: {duration} ثانية)"
        ),
        language="ar",
        filename=filename,
        size_bytes=size_bytes,
        model="mock",
        duration_estimate_sec=duration,
    )


async def transcribe_audio(
    file_bytes: bytes,
    filename: str,
    language: str | None = None,
    max_attempts: int = 3,
) -> TranscriptionResult:
    """
    يفرّغ ملف صوتي إلى نص باستخدام Whisper.

    :param file_bytes: محتوى الملف الصوتي كاملًا
    :param filename: اسم الملف الأصلي (لتحديد الصيغة)
    :param language: رمز اللغة مثل "ar" أو "en"، أو None للكشف التلقائي
    :raises TranscriptionError: عند غياب المفتاح أو خطأ في الصيغة/الحجم/الخدمة
    """
    ext = validate_audio(filename, len(file_bytes))

    # وضع التجربة: لا يحتاج مفتاح ولا اتصال
    if settings.WHISPER_MOCK:
        logger.info("وضع التجربة مفعّل — لا يوجد اتصال بـ OpenAI")
        return _mock_transcript(filename, len(file_bytes), ext, file_bytes)
    if not settings.openai_ready:
        raise TranscriptionError(
            "مفتاح OpenAI غير مضبوط. أضف OPENAI_API_KEY في ملف .env ثم أعد "
            "تشغيل الخادم. (تحدده في: https://platform.openai.com/api-keys)",
            status_code=503,
        )

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    temp_path = await _save_temp_upload(file_bytes, filename)

    started = time.perf_counter()
    try:
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                async with aiofiles.open(temp_path, "rb") as f:
                    result = await client.audio.transcriptions.create(
                        model=settings.WHISPER_MODEL,
                        file=(filename, f),
                        language=language,
                        response_format="verbose_json",
                    )
                break
            except RateLimitError as exc:
                last_error = exc
                wait = 2**attempt + random.random()
                logger.warning("حد معدل من OpenAI — إعادة المحاولة %s/%s بعد %.1fs",
                               attempt, max_attempts, wait)
                if attempt == max_attempts:
                    raise TranscriptionError(
                        "تم تجاوز حد استخدام OpenAI مؤقتًا. حاول بعد دقيقة.",
                        status_code=502,
                    ) from exc
                await asyncio.sleep(wait)
            except (APIConnectionError, APIError) as exc:
                last_error = exc
                wait = 1.5 * attempt
                logger.warning("خطأ في الاتصال بـ OpenAI (%s) — إعادة المحاولة %s/%s",
                               type(exc).__name__, attempt, max_attempts)
                if attempt == max_attempts:
                    raise TranscriptionError(
                        "تعذّر الاتصال بخدمة التفريغ. تحقق من الإنترنت ومن صحة "
                        "مفتاح OpenAI ثم أعد المحاولة.",
                        status_code=502,
                    ) from exc
                await asyncio.sleep(wait)
        else:  # pragma: no cover - للحماية
            raise TranscriptionError(
                f"فشل التفريغ: {last_error}", status_code=502
            )

        elapsed = time.perf_counter() - started
        logger.info(
            "تم تفريغ %s (%s) في %.2f ثانية — %d حرف",
            filename, ext, elapsed, len(getattr(result, "text", "") or ""),
        )

        return TranscriptionResult(
            text=(getattr(result, "text", "") or "").strip(),
            language=getattr(result, "language", language),
            filename=filename,
            size_bytes=len(file_bytes),
            model=getattr(result, "model", settings.WHISPER_MODEL),
            duration_estimate_sec=getattr(result, "duration", None)
            or _estimate_duration(len(file_bytes), ext, file_bytes),
            segments=[
                {"start": s.start, "end": s.end, "text": s.text}
                for s in (getattr(result, "segments", None) or [])
            ],
        )

    except TranscriptionError:
        raise
    except FileNotFoundError as exc:
        raise TranscriptionError("تعذّر قراءة الملف المرفوع", status_code=500) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("خطأ غير متوقع أثناء التفريغ")
        raise TranscriptionError(
            "حدث خطأ غير متوقع أثناء تفريغ الصوت. راجع سجل الخادم.",
            status_code=500,
        ) from exc
    finally:
        # يُحذف الملف المؤقت دائمًا
        _delete_temp_upload(temp_path)
