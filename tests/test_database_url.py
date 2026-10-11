"""اختبارات تحويل رابط قاعدة البيانات — حارس ضد رجوع `wss://` إلى الإنتاج."""

import pytest

from app.config import Settings

TURSO_HOST = "promptcraft-x.aws-us-west-2.turso.io"
TOKEN = "eyJhbGciOi.TOKEN.sig"


def resolve(url: str) -> str:
    """`resolved_database_url` هي المكان الوحيد الذي يطبّع الرابط."""
    return Settings(DATABASE_URL=url).resolved_database_url


# ============================================================
# أ) التطبيع في config.Settings.resolved_database_url
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
    assert resolve(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}",
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
    ],
)
def test_already_correct_scheme_is_left_alone(raw):
    """`sqlite+libsql://` تُمرَّر كما هي، وتُضاف secure فقط إن غابت."""
    result = resolve(raw)
    assert result.startswith("sqlite+libsql://")
    assert result.count("secure=") == 1
    assert "secure=true" in result


@pytest.mark.parametrize(
    "raw",
    [
        "sqlite:///./data/promptcraft.db",
        "sqlite:///:memory:",
        "sqlite+aiosqlite:///./data/promptcraft.db",
        "postgresql://user:pw@localhost:5432/db",
    ],
)
def test_local_sqlite_and_unknown_urls_pass_through_untouched(raw):
    """روابط SQLite المحلية وأي مخطط آخر لا تُمسّ إطلاقًا."""
    assert resolve(raw) == raw


# ============================================================
# ب) الضمان الحاسم: لا يخرج wss:// أبدًا
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # خطأ لوحة النشر: رابط websocket بدل مخطط SQLAlchemy
        (f"wss://{TURSO_HOST}", f"sqlite+libsql://{TURSO_HOST}?secure=true"),
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
    assert resolve(raw) == expected


def test_ws_url_never_downgrades_to_plaintext():
    """`secure=false` لا تبقى بعد إصلاح رابط websocket — التوكن مشفَّر دائماً."""
    result = resolve(f"ws://{TURSO_HOST}?authToken={TOKEN}&secure=false")
    assert "secure=false" not in result
    assert "secure=true" in result


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
    رابط websocket هو وجهة النقل التي يبنيها الـ driver من `secure=true`،
    ولا مخطط تقبله `create_engine` — لو مرّرناه لانهار بخطأ
    `Can't load plugin: sqlalchemy.dialects:wss`. هذا الاختبار هو الحارس
    الذي يمنع عودته من `config.py` إلى `database.py` أو العكس.
    """
    result = resolve(raw)
    assert not result.startswith(("wss://", "ws://")), result


# ============================================================
# ج) config: التصنيف
# ============================================================


@pytest.mark.parametrize(
    "raw",
    [
        f"libsql://{TURSO_HOST}?authToken={TOKEN}",
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}",
        f"wss://{TURSO_HOST}?authToken={TOKEN}",
    ],
)
def test_is_turso_detects_every_remote_scheme(raw):
    """كل مخططات Turso السحابية — بما فيها المغلوط — تصفّها كـ Turso."""
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


def test_unknown_scheme_is_neither_turso_nor_sqlite():
    """
    رابط `postgresql://` مثلاً لا يصنّفه الكود كـ Turso ولا كملف محلي،
    فيمرّ خامًا. هذا سلوك صحيح: لا نفترض ولا نُصلح ما لا نعرفه.
    """
    settings = Settings(DATABASE_URL="postgresql://user:pw@localhost:5432/db")
    assert settings.is_turso is False
    assert settings.is_sqlite is False
    assert settings.database_backend == "postgresql"


# ============================================================
# د) database.py لا يطبّع — يمرّر ناتج config كما هو
# ============================================================


def test_database_module_does_not_reimplement_normalization():
    """
    التطبيع في مكان واحد فقط. لو نُسخت هنا لأمكن أن تنحرف إحدى
    النسختين عن الأخرى،的后果 قيمة قاعدة بيانات مختلفة في الإنتاج
    بلا أي اختبار يلحظ.
    """
    from app import database

    assert not hasattr(database, "_normalize_libsql_url")