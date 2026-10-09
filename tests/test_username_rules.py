"""اختبارات قواعد اسم المستخدم (حروف فقط) ومسار خطأ 422."""

import pytest

from app.schemas import USERNAME_FORMAT_ERROR, LoginRequest


# ============================================================
# أ) الأسماء المقبولة
# ============================================================


@pytest.mark.parametrize(
    "raw",
    ["أحمد علي", "John Doe", "murad", "محمد", "ali", "نور الهدى"],
)
def test_accepts_letters_and_spaces(raw):
    """حروف عربية أو إنجليزية مع مسافات — يجب أن تُقبل."""
    request = LoginRequest(username=raw)
    assert request.username in raw


def test_collapses_surrounding_and_repeated_spaces():
    """المسافات الزائدة تطمس ولا تُشترط — المستخدم يكتبها بالخطأ كثيرًا."""
    assert LoginRequest(username="  أحمد   علي  ").username == "أحمد علي"


# ============================================================
# ب) الأسماء المرفوضة
# ============================================================


@pytest.mark.parametrize(
    "raw",
    [
        "احمد123",      # أرقام
        "user_1",       # شرطة سفلية + رقم
        "John-Doe",     # شرطة
        "a.b",          # نقطة
        "أحمد!",        # علامة ترقيم
        "@murad",       # رمز خاص
        "مُحَمّد",        # تشكيل داخل الكلمة (ليس ضمن النطاق)
        "user@example", # بريد إلكتروني
    ],
)
def test_rejects_non_letters(raw):
    """الأرقام والرموز والتشكيل مرفوضة برسالة عربية واحدة."""
    with pytest.raises(ValueError) as exc:
        LoginRequest(username=raw)

    assert USERNAME_FORMAT_ERROR in str(exc.value)


def test_rejects_too_short():
    """حرف واحد أقل من الحد الأدنى."""
    with pytest.raises(ValueError):
        LoginRequest(username="أ")


def test_rejects_too_long():
    """31 حرفًا تتجاوز الحد الأقصى (30)."""
    with pytest.raises(ValueError):
        LoginRequest(username="a" * 31)


def test_rejects_reserved_name():
    """الأسماء المحجوزة تُرفض حتى لو كانت حروفًا صافية."""
    with pytest.raises(ValueError, match="محجوز"):
        LoginRequest(username="admin")


# ============================================================
# ج) المسار عبر الـ API — 422 برسالة عربية
# ============================================================


def test_login_endpoint_returns_422_arabic_message(client):
    """اسم بأرقام → 422 والرسالة العربية تصل كما هي للواجهة."""
    response = client.post("/api/auth/login", json={"username": "احمد123"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any(USERNAME_FORMAT_ERROR in item["msg"] for item in detail)


def test_login_endpoint_accepts_arabic_name(client):
    """اسم عربي بحروف ومسافة → 200."""
    response = client.post("/api/auth/login", json={"username": "أحمد علي"})

    assert response.status_code == 200, response.text
    assert response.json()["user"]["username"] == "أحمد علي"


def test_login_endpoint_accepts_latin_name(client):
    """اسم إنجليزي بحروف ومسافة → 200."""
    response = client.post("/api/auth/login", json={"username": "John Doe"})

    assert response.status_code == 200, response.text
    assert response.json()["user"]["username"] == "John Doe"


def test_check_endpoint_flags_digits(client):
    """واجهة الفحص المسبق تُظهر نفس الرسالة العربية."""
    response = client.get("/api/auth/check", params={"username": "احمد123"})

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == USERNAME_FORMAT_ERROR