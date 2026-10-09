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


# ============================================================
# محرك البرومبتات
# ============================================================

# الحروف العربية (أبجد + تشكيل + تاء مربوطة) — نتحقق منها في التحقق من اللغة.
ARABIC_PATTERN = r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]"
# الحد الأقصى للوصف الخام — يمنع استهلاك رصيد ضخم بطلب واحد.
MAX_RAW_INPUT = 4000


class PromptGenerateRequest(BaseModel):
    """طلب توليد برومبت من وصف خام."""

    input: str = Field(
        ...,
        min_length=3,
        max_length=MAX_RAW_INPUT,
        description="الوصف الخام الذي تريد تحويله إلى برومبت مهيكَل",
        examples=["أريد مقال عن الذكاء الاصطناعي"],
    )
    tool: str = Field(
        default="general",
        max_length=32,
        description="الأداة المستهدفة: chatgpt / claude / gemini / midjourney / cursor / general",
    )
    framework: str = Field(
        default="co-star",
        max_length=32,
        description="الإطار: co-star / crispe / 5c",
    )
    language: str = Field(
        default="ar",
        max_length=8,
        description="لغة البرومبت الناتج: ar أو en",
    )
    save: bool = Field(
        default=True,
        description="هل يُحفظ البرومبت في سجل المستخدم؟",
    )

    @field_validator("input")
    @classmethod
    def _validate_input(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("الوصف قصير جدًا — اكتب 3 أحرف على الأقل")
        return value

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("ar", "en"):
            raise ValueError("اللغة المدعومة: ar أو en")
        return value


class PromptEnhanceRequest(BaseModel):
    """طلب تحسين برومبت موجود."""

    prompt: str = Field(
        ...,
        min_length=5,
        max_length=MAX_RAW_INPUT,
        description="البرومبت الموجود الذي تريد تحسينه",
    )
    language: str = Field(
        default="ar",
        max_length=8,
        description="لغة البرومبت المحسَّن: ar أو en",
    )
    save: bool = Field(default=False, description="هل يُحفظ في السجل؟")


class SuggestFrameworkResponse(BaseModel):
    """رد اقتراح الإطار."""

    success: bool = True
    text: str
    framework: str
    framework_name: str
    reason_ar: str
    confidence: float
    alternatives: list[str]
