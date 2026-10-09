"""إعدادات التطبيق — تُقرأ من ملف .env أو من متغيرات البيئة."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# مسار جذر المشروع (المجلد الذي يحتوي على مجلد app)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """كل إعدادات PromptCraft في مكان واحد."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- عام ----
    APP_NAME: str = "PromptCraft"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # ---- الأمان ----
    # مفتاح سري لتوقيع الكوكيز. يجب تغييره في الإنتاج.
    SECRET_KEY: str = "change_me"
    # اسم الكوكي الذي يحفظ توكن الجلسة
    SESSION_COOKIE_NAME: str = "session_token"
    # مدة صلاحية الجلسة بالأيام
    SESSION_TTL_DAYS: int = 30
    # اجعلها True عند التشغيل خلف HTTPS
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # ---- قاعدة البيانات ----
    DATABASE_URL: str = f"sqlite:///{(BASE_DIR / 'data' / 'promptcraft.db').as_posix()}"
    DB_ECHO: bool = False

    # ---- OpenAI ----
    OPENAI_API_KEY: str = ""
    # نموذج تفريغ الصوت
    WHISPER_MODEL: str = "whisper-1"
    # وضع التجربة للتفريغ: true = نص وهمي بدون اتصال بـ OpenAI
    # اجعلها false لتشغيل التفريغ الحقيقي (يتطلب OPENAI_API_KEY)
    WHISPER_MOCK: bool = True

    # ---- OpenRouter — محرك هندسة البرومبتات ----
    # المفتاح من: https://openrouter.ai/keys
    OPENROUTER_API_KEY: str = ""
    # النموذج الافتراضي (مجاني على OpenRouter)
    OPENROUTER_MODEL: str = "nvidia/nemotron-3-super-120b-a12b:free"
    # نماذج احتياطية تُجرَّب بالترتيب عند فشل الأساسي بأحد رموز
    # RETRYABLE_MODEL_STATUSES (429 مزدحم / 503 مؤقت / 404 غير موجود).
    # تحذير: `qwen/qwen-2.5-7b-instruct` و`gemini-2.0-flash-exp` رجعا 404
    # عند التحقق (أُزيلا من الواجهة) — باقيان كخيار لو عادا، وقائمة النماذج
    # المجانية تتغيّر باستمرار: راجع https://openrouter.ai/models
    # ملاحظة: صيغتها في .env يجب أن تكون JSON مصفوفة.
    OPENROUTER_MODELS_FALLBACK: list[str] = [
        "qwen/qwen-2.5-7b-instruct:free",
        "google/gemini-2.0-flash-exp:free",
        "apodex/apodex-1.1-mini:free",
    ]
    # نقطة النهاية المتوافقة مع OpenAI SDK
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # ترويسات تُرسل مع كل طلب (إحصاءات OpenRouter + هوية التطبيق)
    OPENROUTER_HTTP_REFERER: str = "https://promptcraft.app"
    OPENROUTER_APP_TITLE: str = "PromptCraft"
    # سقف زمني للاستجابة بالثواني (لحماية الواجهة من التعليق)
    OPENROUTER_TIMEOUT: float = 60.0
    # وضع التجربة: يُرجع برومبتًا قالبيًا بدون اتصال (للاختبار بدون مفتاح)
    PROMPT_MOCK: bool = False
    # أقصى عدد رموز في مخرج النموذج — يحدّ زمن الاستجابة وحجم الرد
    PROMPT_MAX_TOKENS: int = 800
    # تخزين آخر النتائج في الذاكرة لتفادي استدعاء مكرّر لنفس الطلب
    PROMPT_CACHE_ENABLED: bool = True
    PROMPT_CACHE_SIZE: int = 50
    PROMPT_CACHE_TTL: int = 3600

    # ---- الرفع الصوتي ----
    UPLOAD_DIR: Path = BASE_DIR / "data" / "uploads"
    MAX_UPLOAD_MB: int = 25
    # صيغ الصوت المدعومة (نفس صيغ Whisper API)
    ALLOWED_AUDIO_EXTENSIONS: list[str] = [
        ".mp3",
        ".mp4",
        ".m4a",
        ".wav",
        ".webm",
        ".ogg",
        ".mpeg",
        ".mpga",
        ".flac",
    ]

    # ---- مسارات الواجهة ----
    STATIC_DIR: Path = BASE_DIR / "static"
    TEMPLATES_DIR: Path = BASE_DIR / "templates"

    # ---- CORS ----
    # في التطوير فقط. في الإنتاج اجعلها نطاقات محددة.
    CORS_ORIGINS: list[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @property
    def session_ttl_seconds(self) -> int:
        """مدة الجلسة بالثواني."""
        return self.SESSION_TTL_DAYS * 24 * 60 * 60

    @property
    def max_upload_bytes(self) -> int:
        """الحد الأقصى لحجم الملف الصوتي بالبايت."""
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def openai_ready(self) -> bool:
        """هل يمكن استخدام OpenAI فعلًا؟"""
        return bool(self.OPENAI_API_KEY.strip())

    @property
    def openrouter_ready(self) -> bool:
        """هل يمكن استخدام OpenRouter لتوليد البرومبتات؟"""
        return bool(self.OPENROUTER_API_KEY.strip())

    def ensure_directories(self) -> None:
        """يتأكد من وجود المجلدات التي يحتاجها التطبيق قبل التشغيل."""
        self.STATIC_DIR.mkdir(parents=True, exist_ok=True)
        self.TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # مجلد قاعدة البيانات
        if self.DATABASE_URL.startswith("sqlite"):
            db_path = self.DATABASE_URL.replace("sqlite:///", "", 1)
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def cleanup_uploads(self, keep_hours: int = 6) -> int:
        """يحذف الملفات المؤقتة القديمة من مجلد الرفع. يُستدعى عند الإقلاع."""
        if not self.UPLOAD_DIR.exists():
            return 0

        import time

        cutoff = time.time() - keep_hours * 3600
        removed = 0
        for item in self.UPLOAD_DIR.iterdir():
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink()
                    removed += 1
            except OSError:
                continue
        return removed


@lru_cache
def get_settings() -> Settings:
    """نسخة واحدة من الإعدادات (cached) لكل تشغيل."""
    return Settings()


settings = get_settings()
