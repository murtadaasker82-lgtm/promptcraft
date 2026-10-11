"""اختبارات تحويل رابط قاعدة البيانات — حارس ضد رجوع `wss://` إلى الإنتاج."""

import pytest

from app.config import Settings
from app.database import _normalize_libsql_url

TURSO_HOST = "promptcraft-x.aws-us-west-2.turso.io"
TOKEN = "eyJhbGciOi.TOKEN.sig"


# ============================================================
# أ) التحويل في database._normalize_libsql_url
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # الصيغة الحقيقية في لوحة النشر
        (
            f"libsql://{TURSO_HOST}?authToken={TOKEN}",
            f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
        ),
        # secure موجودة مسبقًا — لا تُكرَّر
        (
            f"libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
            f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
        ),
        # secure=false صريحة — تُحترم ولا تُقوى
        (
            f"libsql://{TURSO_HOST}?authToken={TOKEN}&secure=false",
            f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=false",
        ),
        # بلا query params إطلاقًا
        (
            f"libsql://{TURSO_HOST}",
            f"sqlite+libsql://{TURSO_HOST}?secure=true",
        ),
    ],
)
def test_libsql_scheme_is_promoted_to_sqlite_plus_libsql(raw, expected):
    """`libsql://` تُرقّى إلى `sqlite+libsql://` مع ضمان `secure=true`."""
    assert _normalize_libsql_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}",
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
    ],
)
def test_already_correct_scheme_is_left_alone(raw):
    """`sqlite+libsql://` تُمرَّر كما هي، وتُضاف secure فقط إن غابت."""
    result = _normalize_libsql_url(raw)
    assert result.startswith("sqlite+libsql://")
    assert result.count("secure=") == 1
    assert "secure=true" in result


@pytest.mark.parametrize(
    "raw",
    [
        "sqlite:///./data/promptcraft.db",
        "sqlite:///:memory:",
        "sqlite+aiosqlite:///./data/promptcraft.db",
    ],
)
def test_local_sqlite_urls_pass_through_untouched(raw):
    """روابط SQLite المحلية لا تُمسّ إطلاقًا."""
    assert _normalize_libsql_url(raw) == raw


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # خطأ لوحة النشر: رابط websocket بدل مخطط SQLAlchemy
        (
            f"wss://{TURSO_HOST}",
            f"sqlite+libsql://{TURSO_HOST}?secure=true",
        ),
        (
            f"wss://{TURSO_HOST}?authToken={TOKEN}",
            f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
        ),
        # ws:// يعني فضح authToken — نفرض TLS حتى لو كُتب contrary
        (
            f"ws://{TURSO_HOST}?authToken={TOKEN}",
            f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
        ),
        (
            f"ws://{TURSO_HOST}?authToken={TOKEN}&secure=false",
            f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
        ),
    ],
)
def test_websocket_url_is_repaired_to_sqlalchemy_scheme(raw, expected):
    """`wss://` و `ws://` يُصلَحان إلى `sqlite+libsql://` مع TLS إجباري."""
    assert _normalize_libsql_url(raw) == expected


def test_ws_url_never_downgrades_to_plaintext():
    """`secure=false` لا تبقى بعد إصلاح رابط websocket — التوكن مشفَّر دائماً."""
    result = _normalize_libsql_url(f"ws://{TURSO_HOST}?authToken={TOKEN}&secure=false")
    assert "secure=false" not in result
    assert "secure=true" in result


# ============================================================
# ب) الضمان الحاسم: لا يخرج wss:// أبدًا
# ============================================================


@pytest.mark.parametrize(
    "raw",
    [
        f"libsql://{TURSO_HOST}?authToken={TOKEN}",
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}",
        f"libsql://{TURSO_HOST}",
        "sqlite:///./data/promptcraft.db",
        f"wss://{TURSO_HOST}",  # حتى لو وصلت مغلوطة من لوحة النشر
        f"ws://{TURSO_HOST}",
    ],
)
def test_output_never_becomes_a_websocket_url(raw):
    """
    `wss://` وجهة اتصال يبنيها الـ driver من `secure=true`، لا مخطط
    تقبله `create_engine`. لو مرّرناه لـ SQLAlchemy لانهار بخطأ
    `Can't load plugin: sqlalchemy.dialects:wss`. هذا الاختبار هو الحارس
    الذي يمنع عودتها إلى `database.py` أو `config.py`.
    """
    result = _normalize_libsql_url(raw)
    assert not result.startswith(("wss://", "ws://")), result


# ============================================================
# ج) config: التصنيف والـ resolved URL
# ============================================================


@pytest.mark.parametrize(
    "raw",
    [
        f"libsql://{TURSO_HOST}?authToken={TOKEN}",
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}",
    ],
)
def test_is_turso_detects_both_schemes(raw):
    """كلا المخططين يصفان اتصال Turso السحابي لا ملفًا محليًا."""
    settings = Settings(DATABASE_URL=raw)
    assert settings.is_turso is True
    assert settings.is_sqlite is False
    assert settings.database_backend == "turso"


def test_is_sqlite_only_for_file_paths():
    """`sqlite+libsql://` يبدأ بـ sqlite لكنه ليس ملفًا."""
    settings = Settings(DATABASE_URL="sqlite:///./data/promptcraft.db")
    assert settings.is_sqlite is True
    assert settings.is_turso is False
    assert settings.database_backend == "sqlite"


def test_wss_url_is_classified_as_turso_and_repaired():
    """
    رابط `wss://` المغلوط يجب أن يصنّفه الكود كـ Turso فيدخل فرع
    Turso، ويصلحه `database.py`. قبل هذا كانت `is_turso` خاطئةً له فلا
    يُصحَّح ولا يُستخدم، فيمرّ `wss://` خامًا إلى `create_engine` وينهار.
    """
    settings = Settings(DATABASE_URL=f"wss://{TURSO_HOST}?authToken={TOKEN}")
    assert settings.is_turso is True
    assert settings.is_sqlite is False
    assert settings.database_backend == "turso"
    # resolved لا تُصلح (دورها تمرير)، لكن database.py يفعل
    assert settings.resolved_database_url == f"wss://{TURSO_HOST}?authToken={TOKEN}"
    assert _normalize_libsql_url(settings.resolved_database_url).startswith(
        "sqlite+libsql://"
    )


def test_unknown_scheme_is_neither_turso_nor_sqlite():
    """
    رابط `postgresql://` مثلاً لا يصنّفه الكود كـ Turso ولا كملف محلي،
    فيمرّ خامًا. هذا سلوك صحيح: لا نفترض ولا نُصلح ما لا نعرفه.
    """
    settings = Settings(DATABASE_URL="postgresql://user:pw@localhost:5432/db")
    assert settings.is_turso is False
    assert settings.is_sqlite is False
    assert settings.database_backend == "postgresql"


@pytest.mark.parametrize(
    "raw",
    [
        f"libsql://{TURSO_HOST}?authToken={TOKEN}",
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
        "sqlite:///./data/promptcraft.db",
    ],
)
def test_resolved_database_url_never_yields_wss(raw):
    """الدالة تمرّر الرابط بلا تحويل، فلا تُنتج `wss://` ولا `ws://`."""
    resolved = Settings(DATABASE_URL=raw).resolved_database_url
    assert not resolved.startswith(("wss://", "ws://")), resolved