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
    # وضع التجربة: يُرجع نصًا وهميًا بدون اتصال بـ OpenAI (للاختبار فقط)
    WHISPER_MOCK: bool = False

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
