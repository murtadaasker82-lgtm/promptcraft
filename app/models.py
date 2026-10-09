"""نماذج قاعدة البيانات (SQLAlchemy ORM)."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    """الوقت الحالي بتوقيت UTC بصيغة naive (المتعارف عليها في SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """مستخدم PromptCraft — يُنشأ تلقائيًا عند أول تسجيل دخول باسمه."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    prompts: Mapped[list["PromptHistory"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"


class PromptHistory(Base):
    """سجل البرومبتات المولّدة — يحتفظ بالمدخل الخام والنتيجة."""

    __tablename__ = "prompt_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    generated_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    tool: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    framework: Mapped[str] = mapped_column(String(32), nullable=False, default="co-star")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="ar")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        nullable=False,
        index=True,
    )

    user: Mapped["User"] = relationship(back_populates="prompts")

    def __repr__(self) -> str:
        return (
            f"<PromptHistory id={self.id} user_id={self.user_id} "
            f"tool={self.tool!r} framework={self.framework!r}>"
        )


class Session(Base):
    """جلسة دخول واحدة (توكن واحد) — مدة صلاحيتها 30 يومًا."""

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped["User"] = relationship(back_populates="sessions")

    __table_args__ = (Index("ix_sessions_user_expires", "user_id", "expires_at"),)

    def is_expired(self) -> bool:
        """هل انتهت صلاحية الجلسة؟"""
        return utcnow() >= self.expires_at

    def __repr__(self) -> str:
        return f"<Session user_id={self.user_id} expires_at={self.expires_at}>"
