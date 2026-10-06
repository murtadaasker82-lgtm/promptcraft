"""منطق المصادقة: إنشاء الجلسات، الكوكيز، والـ dependency الخاص بالمستخدم الحالي."""

import hashlib
import secrets
from datetime import timedelta

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.config import settings
from app.database import get_db
from app.models import Session, User, utcnow

# ---------------- توليد التوكن ----------------

TOKEN_BYTES = 32
TOKEN_HASH_LEN = 64  # طول sha256 hex


def generate_token() -> str:
    """توكن عشوائي آمن (256 بت) يُرسل للعميل مرة واحدة فقط."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """
    هاش التوكن قبل تخزينه في قاعدة البيانات.

    عمود token هو المفتاح الأساسي في جدول sessions، لكن ما نخزّنه فيه هو
    sha256(token) وليس التوكن نفسه. لذلك لو تسرّبت قاعدة البيانات
    لا يستطيع المهاجم استخدام الكوكيز.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------- إنشاء / إلغاء الجلسات ----------------


def create_session(db: OrmSession, user: User) -> tuple[str, Session]:
    """ينشئ جلسة جديدة للمستخدم ويعيد (التوكن الأصلي، سجل الجلسة)."""
    token = generate_token()
    expires_at = utcnow() + timedelta(seconds=settings.session_ttl_seconds)

    db_session = Session(
        token=hash_token(token),
        user_id=user.id,
        created_at=utcnow(),
        expires_at=expires_at,
    )
    db.add(db_session)
    db.commit()
    db.refresh(db_session)

    return token, db_session


def delete_session(db: OrmSession, token: str | None) -> bool:
    """يحذف جلسة (تسجيل خروج). يعيد True إذا حُذفت فعلاً."""
    if not token:
        return False

    db_session = db.get(Session, hash_token(token))
    if db_session is None:
        return False

    db.delete(db_session)
    db.commit()
    return True


def get_session_by_token(db: OrmSession, token: str) -> Session | None:
    """يجلب جلسة صالحة (غير منتهية) من التوكن، ويحذف المنتهية تلقائيًا."""
    db_session = db.get(Session, hash_token(token))
    if db_session is None:
        return None

    if db_session.is_expired():
        db.delete(db_session)
        db.commit()
        return None

    return db_session


def purge_expired_sessions(db: OrmSession) -> int:
    """يحذف كل الجلسات المنتهية. يُستدعى عند الإقلاع."""
    result = db.execute(select(Session).where(Session.expires_at <= utcnow()))
    expired = list(result.scalars().all())
    for db_session in expired:
        db.delete(db_session)
    db.commit()
    return len(expired)


# ---------------- الكوكيز ----------------


def set_session_cookie(response: Response, token: str) -> None:
    """يضبط كوكي HTTP-only يحتوي التوكن."""
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """يحذف كوكي الجلسة من المتصفح."""
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )


# ----------------Dependency: المستخدم الحالي ----------------


def get_current_user(
    request: Request,
    session_token: str | None = Cookie(
        default=None,
        alias=settings.SESSION_COOKIE_NAME,
    ),
    db: OrmSession = Depends(get_db),
) -> User:
    """
    يتحقق من كوكي الجلسة ويعيد المستخدم الحالي.

    يرجع 401 إن كان الكوكي مفقودًا أو منتهيًا أو غير صالح.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="يجب تسجيل الدخول أولًا — أدخل اسم المستخدم",
        headers={"WWW-Authenticate": "Cookie"},
    )

    if not session_token:
        raise credentials_error

    db_session = get_session_by_token(db, session_token)
    if db_session is None:
        raise credentials_error

    user = db.get(User, db_session.user_id)
    if user is None:
        # جلسة يتيمة (حُذف المستخدم) — ننظّفها
        db.delete(db_session)
        db.commit()
        raise credentials_error

    request.state.user_id = user.id
    return user


def get_optional_user(
    session_token: str | None = Cookie(
        default=None,
        alias=settings.SESSION_COOKIE_NAME,
    ),
    db: OrmSession = Depends(get_db),
) -> User | None:
    """
    نفس `get_current_user` لكن يعيد None بدل رمي 401.

    يُستخدم في صفحات HTML التي تريد التوجيه إلى /login بدل إرجاع JSON خطأ.
    """
    if not session_token:
        return None

    db_session = get_session_by_token(db, session_token)
    if db_session is None:
        return None

    return db.get(User, db_session.user_id)
