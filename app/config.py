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
    # النموذج المستخدم لتوليد البرومبت.
    # تحقّق حيّ (2026-10): النماذج المجانية الأخرى المرشّحة ترجع 404 — لا وجود
    # لها على OpenRouter anymore. فنُبقي apodex وحده في الطليعة.
    # راجع https://openrouter.ai/models إن أردت التغيير.
    OPENROUTER_MODEL: str = "apodex/apodex-1.1-mini:free"
    # سلسلة النماذج الاحتياطية — فارغة حاليًا لأن كل المرشّحين رجعوا 404،
    # والآلية جاهزة: أضف أسماء هنا لتُجرَّب تلقائيًا عند 404/429/503.
    # الصيغة في .env يجب أن تكون JSON مصفوفة.
    OPENROUTER_MODELS_FALLBACK: list[str] = []
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

    # ---- النسخ الاحتياطي ----
    # نسخة مؤرّخة من ملف قاعدة البيانات عند كل إقلاع
    BACKUP_ENABLED: bool = True
    BACKUP_KEEP_DAYS: int = 7

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
    # سلسلة مفصولة بفواصل. `*` تعني أي مصدر — مريح للتجربة، لكن في الإنتاج
    # حدّد نطاقك الحقيقي (مثل "https://promptcraft.onrender.com") لأن
    # `allow_credentials=True` مع `*` غير متوافق مع مواصفة CORS.
    CORS_ORIGINS: str = "*"

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
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS كقائمة — يفصل السلسلة على الفواصل ويتجاهل الفراغات."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def resolved_database_url(self) -> str:
        """
        رابط قاعدة البيانات كما هو — بلا أي تحويل.

        DATABASE_URL متغيّر واحد يتحكم به من لوحة النشر، والصيغة
        المعتمدة هي:

            # محليًا (افتراضي)
            DATABASE_URL=sqlite:///./data/promptcraft.db

            # إنتاج — Turso عبر libSQL
            DATABASE_URL=sqlite+libsql://<host>?authToken=<token>&secure=true

        لماذا `sqlite+libsql://` بالذات؟ لأن `sqlalchemy-libsql` يسجّل
        الـ dialect باسم `sqlite.libsql`، وهو المخطط الوحيد الذي تقبله
        `create_engine`. تمرير `libsql://` أو `wss://` مباشرةً يفشل
        بـ `NoSuchModuleError`، وتمرير `wss://` يعطي نفس الخطأ بمخطط
        مختلف — `wss://` هو وجهة الاتصال التي يبنيها الـ driver من
        `secure=true`، لا مخطط يقبله SQLAlchemy.

        `secure=true` مطلوب: بدونه يربط الـ driver عبر `ws://` غير مشفّر.
        """
        return self.DATABASE_URL

    @property
    def database_backend(self) -> str:
        """اسم مختصر للواجهة والسجلّات — بلا كشف أي توكن."""
        if self.is_turso:
            return "turso"
        if self.is_sqlite:
            return "sqlite"
        return self.DATABASE_URL.split("://", 1)[0]

    @property
    def is_turso(self) -> bool:
        """
        هل الاتصال بقاعدة Turso السحابية لا بملف SQLite محلي؟

        `libsql://` مدرجة هنا لأنها تحدّد سلوك التطبيق (نسخ احتياطي، pragmas)،
        حتى لو كان الرابط نفسه غير صالح لـ SQLAlchemy — تعالجه `database.py`.
        """
        return self.DATABASE_URL.startswith(("libsql://", "sqlite+libsql://"))

    @property
    def is_sqlite(self) -> bool:
        """
        هل الاتصال بملف SQLite محلي؟

        `sqlite+libsql://` يبدأ بـ "sqlite" لكنه ليس ملفاً — لذلك نشترط
        `sqlite:///` بالضبط، وهي صيغة الملفات.
        """
        return self.DATABASE_URL.startswith("sqlite:///") and not self.is_turso

    @property
    def openrouter_ready(self) -> bool:
        """هل يمكن استخدام OpenRouter لتوليد البرومبتات؟"""
        return bool(self.OPENROUTER_API_KEY.strip())

    def ensure_directories(self) -> None:
        """يتأكد من وجود المجلدات التي يحتاجها التطبيق قبل التشغيل."""
        self.STATIC_DIR.mkdir(parents=True, exist_ok=True)
        self.TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # مجلد قاعدة البيانات (فقط للملف المحلي)
        if self.is_sqlite:
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
