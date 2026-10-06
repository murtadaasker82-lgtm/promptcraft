"""نقاط النهاية الخاصة بتسجيل الدخول والخروج."""

import logging
import re

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.auth import (
    clear_session_cookie,
    create_session,
    delete_session,
    get_current_user,
    set_session_cookie,
)
from app.config import settings
from app.database import get_db
from app.models import Session, User
from app.schemas import (
    RESERVED_USERNAMES,
    USERNAME_PATTERN,
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    UserOut,
    UsernameCheckResponse,
)

logger = logging.getLogger("promptcraft.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _get_or_create_user(db: OrmSession, username: str) -> tuple[User, bool]:
    """
    يعيد المستخدم إن كان موجودًا، وينشئه إن لم يكن.

    ‏is_new=True يعني أن أول تسجيل دخول لهذا الاسم هو الآن.
    """
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is not None:
        return user, False

    user = User(username=username)
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("مستخدم جديد: %s (id=%s)", user.username, user.id)
    return user, True


@router.post("/login", response_model=LoginResponse, summary="تسجيل الدخول باسم المستخدم")
def login(
    payload: LoginRequest,
    response: Response,
    db: OrmSession = Depends(get_db),
) -> LoginResponse:
    """
    تسجيل الدخول بدون كلمة مرور.

    * إذا كان الاسم موجودًا → تسجيل دخول.
    * إذا لم يكن موجودًا → إنشاء حساب جديد تلقائيًا.
    """
    try:
        user, is_new = _get_or_create_user(db, payload.username)
    except Exception as exc:  # noqa: BLE001
        logger.exception("فشل إنشاء/جلب المستخدم")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="حدث خطأ أثناء تسجيل الدخول، حاول مرة أخرى",
        ) from exc

    token, db_session = create_session(db, user)

    set_session_cookie(response, token)

    message = "أهلًا بك مجددًا" if not is_new else f"تم إنشاء حساب {user.username} — أهلًا بك!"
    logger.info("تسجيل دخول: %s (token_hash=%s…)", user.username, db_session.token[:8])

    return LoginResponse(
        success=True,
        message=message,
        token=token,
        expires_at=db_session.expires_at,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", response_model=LogoutResponse, summary="تسجيل الخروج")
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=settings.SESSION_COOKIE_NAME),
    db: OrmSession = Depends(get_db),
) -> LogoutResponse:
    """يحذف الجلسة من قاعدة البيانات ويمسح الكوكي."""
    removed = delete_session(db, session_token)
    clear_session_cookie(response)

    if removed:
        logger.info("تسجيل خروج ناجح")

    return LogoutResponse(success=True, message="تم تسجيل الخروج بنجاح")


@router.get("/me", response_model=CurrentUserResponse, summary="بيانات المستخدم الحالي")
def me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    """يعيد بيانات المستخدم الحالي اعتمادًا على كوكي الجلسة."""
    return CurrentUserResponse(
        success=True,
        user=UserOut.model_validate(current_user),
    )


@router.get(
    "/check",
    response_model=UsernameCheckResponse,
    summary="فحص صلاحية اسم المستخدم",
)
def check_username(
    username: str | None = None,
    db: OrmSession = Depends(get_db),
) -> UsernameCheckResponse:
    """
    يتحقق أن الاسم يمرّ بقواعد الصيغة وليس محجوزًا.

    ‏?username=admin   → {"available": false, "reason": "هذا الاسم محجوز"}
    ‏?username=murad   → {"available": true}
    ملاحظة أمنية: لا نكشف إن كان الاسم مسجلًا من قبل، لأن الدخول بالاسم
    مسموح دائمًا؛ الكشف عن التوفر فقط يعطي مؤشرًا لتعداد المستخدمين.
    """
    if not username:
        return UsernameCheckResponse(available=False, reason="أرسل اسم المستخدم: ?username=...")

    username = username.strip()

    if not re.match(USERNAME_PATTERN, username):
        return UsernameCheckResponse(
            available=False,
            reason="اسم المستخدم يجب أن يكون بين 3 و 32 حرفًا، ويحتوي فقط على "
            "حروف إنجليزية وأرقام والرموز _ . -",
        )

    if username.lower() in RESERVED_USERNAMES:
        return UsernameCheckResponse(available=False, reason="هذا الاسم محجوز، اختر اسمًا آخر")

    return UsernameCheckResponse(available=True, reason=None)


@router.get("/sessions", summary="جلسات المستخدم الحالي")
def my_sessions(
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> dict:
    """قائمة جلسات المستخدم الحالي (بدون التوكنات)."""
    rows = db.scalars(
        select(Session)
        .where(Session.user_id == current_user.id)
        .order_by(Session.created_at.desc())
    ).all()

    return {
        "success": True,
        "total": len(rows),
        "sessions": [
            {
                "token_prefix": row.token[:8] + "…",
                "created_at": row.created_at,
                "expires_at": row.expires_at,
            }
            for row in rows
        ],
    }
