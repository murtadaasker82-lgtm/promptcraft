"""اتصال قاعدة البيانات — SQLite محليًا أو Turso (libSQL) في الإنتاج."""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings


class Base(DeclarativeBase):
    """القاعدة الأساسية لكل النماذج (models)."""


DATABASE_URL = settings.resolved_database_url
IS_SQLITE = settings.is_sqlite


def _build_engine():
    """
    ينشئ المحرك حسب نوع القاعدة.

    Turso: نترك الـ dialect لـ `sqlalchemy-libsql` عبر رابط `libsql://`.
    SQLite: نستخدم NullPool حتى لا يبقى اتصال محجوز للقفل، مع
    `check_same_thread=False` لأن FastAPI يخدم كل طلب في خيط مختلف.
    """
    if settings.is_turso:
        try:
            import sqlalchemy_libsql  # noqa: F401 — يسجّل dialect "libsql"
        except ImportError as exc:
            raise RuntimeError(
                "الاتصال بـ Turso يحتاج sqlalchemy-libsql. "
                "ثبّته: pip install sqlalchemy-libsql"
            ) from exc

        return create_engine(
            DATABASE_URL,
            echo=settings.DB_ECHO,
            future=True,
            connect_args={"check_same_thread": False},
        )

    connect_args = {"check_same_thread": False} if IS_SQLITE else {}

    return create_engine(
        DATABASE_URL,
        echo=settings.DB_ECHO,
        future=True,
        connect_args=connect_args,
        poolclass=NullPool if IS_SQLITE else None,
    )


engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """تفعيل WAL وتحقق المفاتيح الأجنبية وأداء أفضل على SQLite."""
    if IS_SQLITE:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    """Dependency: جلسة قاعدة بيانات لكل طلب، تُغلق تلقائيًا."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """إنشاء كل الجداول عند الإقلاع."""
    # نستورد النماذج هنا حتى تُسجَّل في Base.metadata قبل create_all
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
