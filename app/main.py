"""نقطة دخول تطبيق PromptCraft — FastAPI."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import get_optional_user, purge_expired_sessions
from app.config import settings
from app.database import SessionLocal, engine, init_db
from app.models import User
from app.routers.audio_router import router as audio_router
from app.routers.auth_router import router as auth_router
from app.routers.prompt_router import router as prompt_router

# ---------------- التسجيل (logging) ----------------

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("promptcraft")


# ---------------- دورة حياة التطبيق ----------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """قبل الإقلاع: إنشاء المجلدات والجداول وتنظيف الملفات القديمة. عند الإغلاق: تنظيف."""
    settings.ensure_directories()
    init_db()

    removed_uploads = settings.cleanup_uploads(keep_hours=6)
    if removed_uploads:
        logger.info("تم حذف %s ملف صوتي مؤقت قديم", removed_uploads)

    db = SessionLocal()
    try:
        removed_sessions = purge_expired_sessions(db)
        if removed_sessions:
            logger.info("تم حذف %s جلسة منتهية", removed_sessions)
    finally:
        db.close()

    logger.info(
        "%s v%s جاهز — قاعدة البيانات: %s",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.DATABASE_URL,
    )
    if settings.WHISPER_MOCK:
        logger.warning("وضع التجربة مفعّل (WHISPER_MOCK=true): التفريغ وهمي بلا اتصال")
    elif settings.openai_ready:
        logger.info("OpenAI API Key: مضبوط — التفريغ الحقيقي متاح")
    else:
        logger.warning("OpenAI API Key: غير مضبوط — التفريغ الحقيقي معطّل حتى تضيفه في .env")

    if settings.PROMPT_MOCK:
        logger.warning("وضع التجربة مفعّل (PROMPT_MOCK=true): توليد البرومبتات وهمي بلا اتصال")
    elif settings.openrouter_ready:
        logger.info("OpenRouter: مفتاح مضبوط — النموذج %s متاح", settings.OPENROUTER_MODEL)
    else:
        logger.warning("OpenRouter: مفتاح غير مضبوط — توليد البرومبتات معطّل حتى تضيف OPENROUTER_API_KEY في .env")
    logger.info("حد الرفع: %s ميجابايت — الصيغ: %s",
                settings.MAX_UPLOAD_MB, ", ".join(settings.ALLOWED_AUDIO_EXTENSIONS))
    yield
    logger.info("إيقاف %s", settings.APP_NAME)


# ---------------- إنشاء التطبيق ----------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="حوّل وصفك النصي أو الصوتي إلى برومبت احترافي مهيكلة.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ---- الملفات الثابتة والقوالب ----
app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))


# ---------------- معالجة الأخطاء الموحّدة ----------------


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """يعيد كل أخطاء HTTP ببنية JSON واحدة."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "detail": exc.detail,
            "path": request.url.path,
        },
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """يمسك أي خطأ غير متوقع ويرجّع 500 نظيف (بدل صفحة HTML)."""
    logger.exception("خطأ غير متوقع على %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "detail": "خطأ داخلي في الخادم، تم تسجيل المشكلة",
            "path": request.url.path,
        },
    )


# ---------------- المسارات ----------------

app.include_router(auth_router)
app.include_router(audio_router)
app.include_router(prompt_router)


@app.get("/api/health", tags=["meta"], summary="فحص صحة التطبيق")
def health() -> dict:
    """فحص سريع للتطبيق وقاعدة البيانات."""
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        logger.exception("فشل الاتصال بقاعدة البيانات")
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database": "ok" if db_ok else "error",
        "openai_configured": settings.openai_ready,
        "whisper_mock": settings.WHISPER_MOCK,
        "openrouter_configured": settings.openrouter_ready,
        "prompt_mock": settings.PROMPT_MOCK,
        "openrouter_model": settings.OPENROUTER_MODEL,
        "uploads_dir": str(settings.UPLOAD_DIR),
        "max_upload_mb": settings.MAX_UPLOAD_MB,
    }


@app.get("/api", tags=["meta"], summary="قائمة المسارات المتاحة")
def api_index() -> dict:
    """يوثّق المسارات الأساسية في مكان واحد."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/api/docs",
        "endpoints": {
            "auth": {
                "login": "POST /api/auth/login",
                "logout": "POST /api/auth/logout",
                "me": "GET /api/auth/me",
                "check": "GET /api/auth/check?username=...",
                "sessions": "GET /api/auth/sessions",
            },
            "audio": {
                "transcribe": "POST /api/transcribe  (multipart: file)",
                "info": "GET /api/transcribe/info",
            },
            "prompt": {
                "generate": "POST /api/prompt/generate",
                "enhance": "POST /api/prompt/enhance",
                "frameworks": "GET /api/prompt/frameworks",
                "suggest": "GET /api/prompt/suggest?text=...",
                "history": "GET /api/prompt/history",
                "clear_history": "DELETE /api/prompt/history",
            },
            "pages": {
                "login": "GET /login",
                "app": "GET /app",
            },
            "meta": {
                "health": "GET /api/health",
            },
        },
    }


# ---------------- صفحات HTML ----------------


def _render(request: Request, name: str, context: dict):
    """يرسم قالبًا مع تمرير الإعدادات للواجهة دائمًا."""
    base_context = {
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "allowed_extensions": settings.ALLOWED_AUDIO_EXTENSIONS,
        "transcribe_ready": settings.openai_ready or settings.WHISPER_MOCK,
        "whisper_mock": settings.WHISPER_MOCK,
        "prompt_ready": settings.openrouter_ready or settings.PROMPT_MOCK,
        "prompt_mock": settings.PROMPT_MOCK,
        "openrouter_model": "mock" if settings.PROMPT_MOCK else settings.OPENROUTER_MODEL,
    }
    base_context.update(context)
    return templates.TemplateResponse(request=request, name=name, context=base_context)


@app.get("/", include_in_schema=False)
def root(current_user: User | None = Depends(get_optional_user)):
    """يوجّه إلى /app إن كانت هناك جلسة، وإلا إلى /login."""
    if current_user is not None:
        return RedirectResponse(url="/app", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@app.get("/login", include_in_schema=False)
def login_page(request: Request, current_user: User | None = Depends(get_optional_user)):
    """صفحة تسجيل الدخول. المستخدم المسجّل يُحوَّل مباشرة إلى /app."""
    if current_user is not None:
        return RedirectResponse(url="/app", status_code=status.HTTP_302_FOUND)

    return _render(
        request,
        "login.html",
        {
            "page_title": "تسجيل الدخول",
            "auth_user": None,
        },
    )


@app.get("/app", include_in_schema=False)
def app_page(request: Request, current_user: User | None = Depends(get_optional_user)):
    """واجهة الإنشاء — محمية. بدون جلسة يُحوَّل إلى /login."""
    if current_user is None:
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_302_FOUND,
        )

    return _render(
        request,
        "app.html",
        {
            "page_title": "إنشاء برومبت",
            "auth_user": current_user,
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """أيقونة بسيطة (SVG) — بدل 404 في المتصفح."""
    return HTMLResponse(content="", status_code=status.HTTP_204_NO_CONTENT)


@app.get("/session", include_in_schema=False)
def session_info(current_user: User | None = Depends(get_optional_user)) -> dict:
    """لماذا وُجد هذا الـ endpoint: الصفحة تحتاج حالة الجلسة بعد أي إعادة تحميل."""
    if current_user is None:
        return {"authenticated": False, "user": None}

    return {
        "authenticated": True,
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "created_at": current_user.created_at.isoformat(),
        },
        "transcribe": {
            "ready": settings.openai_ready or settings.WHISPER_MOCK,
            "mock": settings.WHISPER_MOCK,
            "max_upload_mb": settings.MAX_UPLOAD_MB,
            "allowed_extensions": settings.ALLOWED_AUDIO_EXTENSIONS,
        },
    }
