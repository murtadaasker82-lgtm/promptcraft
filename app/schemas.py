"""مخططات Pydantic للطلب والاستجابة."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# قواعد اسم المستخدم: 3-32 حرفًا إنجليزيًا/رقميًا مع _ . -
USERNAME_PATTERN = r"^[A-Za-z0-9_.-]{3,32}$"
RESERVED_USERNAMES = {
    "admin",
    "administrator",
    "root",
    "system",
    "api",
    "static",
    "login",
    "logout",
    "app",
    "library",
    "health",
    "www",
    "support",
    "help",
    "null",
    "none",
    "undefined",
}


class LoginRequest(BaseModel):
    """طلب تسجيل الدخول — اسم المستخدم فقط، بلا كلمة مرور."""

    username: str = Field(
        ...,
        min_length=3,
        max_length=32,
        description="اسم المستخدم (3-32 حرفًا: حروف إنجليزية، أرقام، _ . -)",
        examples=["murad"],
    )

    @field_validator("username")
    @classmethod
    def _validate_username(cls, value: str) -> str:
        value = value.strip()
        if not re.match(USERNAME_PATTERN, value):
            raise ValueError(
                "اسم المستخدم يجب أن يكون بين 3 و 32 حرفًا، ويحتوي فقط على "
                "حروف إنجليزية وأرقام والرموز _ . -"
            )
        if value.lower() in RESERVED_USERNAMES:
            raise ValueError("هذا الاسم محجوز، اختر اسمًا آخر")
        return value


class UserOut(BaseModel):
    """بيانات المستخدم التي تُعاد للواجهة."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: datetime


class LoginResponse(BaseModel):
    """رد تسجيل الدخول."""

    success: bool = True
    message: str = "تم تسجيل الدخول بنجاح"
    token: str = Field(..., description="توكن الجلسة (يُحفظ أيضًا في كوكي HTTP-only)")
    expires_at: datetime
    user: UserOut


class LogoutResponse(BaseModel):
    """رد تسجيل الخروج."""

    success: bool = True
    message: str = "تم تسجيل الخروج بنجاح"


class CurrentUserResponse(BaseModel):
    """رد طلب المستخدم الحالي."""

    success: bool = True
    user: UserOut


class UsernameCheckResponse(BaseModel):
    """رد فحص اسم المستخدم قبل الدخول."""

    available: bool
    reason: str | None = None


class ErrorResponse(BaseModel):
    """بنية الخطأ الموحّدة."""

    success: bool = False
    detail: str
