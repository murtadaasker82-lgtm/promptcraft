"""اتصال قاعدة البيانات — SQLite عبر SQLAlchemy."""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """القاعدة الأساسية لكل النماذج (models)."""


# connect_args مطلوبة لـ SQLite في FastAPI (كل طلب يفتح خيطًا)
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    future=True,
    connect_args=connect_args,
)

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
    if settings.DATABASE_URL.startswith("sqlite"):
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
