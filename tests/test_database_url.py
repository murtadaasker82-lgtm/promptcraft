"""اختبارات تطبيع رابط قاعدة البيانات — النطاق المدعوم في المشروع."""

import pytest

from app.config import Settings

TURSO_HOST = "promptcraft-x.aws-us-west-2.turso.io"
TOKEN = "eyJhbGciOi.TOKEN.sig"


def resolve(url: str) -> str:
    """`resolved_database_url` هي المكان الوحيد الذي يطبّع الرابط."""
    return Settings(DATABASE_URL=url).resolved_database_url


# ============================================================
# أ) libsql://  →  sqlite+libsql://
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # secure تُضاف لأنها غائبة
        (
            f"libsql://{TURSO_HOST}?authToken={TOKEN}",
            f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
        ),
        # secure موجودة — لا تُكرَّر
        (
            f"libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
            f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
        ),
        # بلا query params إطلاقًا
        (f"libsql://{TURSO_HOST}", f"sqlite+libsql://{TURSO_HOST}?secure=true"),
    ],
)
def test_libsql_is_promoted_to_sqlite_plus_libsql(raw, expected):
    """`libsql://` تُرقّى إلى `sqlite+libsql://` مع إضافة `secure=true`."""
    assert resolve(raw) == expected


# ============================================================
# ب) sqlite+libsql://  →  بلا تغيير
# ============================================================


@pytest.mark.parametrize(
    "raw",
    [
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=false",
    ],
)
def test_correct_scheme_is_preserved_verbatim(raw):
    """`sqlite+libsql://` تُمرَّر كما هي تماماً — وsecure تُحترم كما كتبها صاحب الإعداد."""
    assert resolve(raw) == raw


def test_correct_scheme_gains_secure_only_when_absent():
    """`secure=true` تُضاف عند الغياب فقط، وتبقى قيمةً واحدة لا مكرّرة."""
    result = resolve(f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}")
    assert result == f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true"
    assert result.count("secure=") == 1


# ============================================================
# ج) sqlite:///  →  بلا تغيير
# ============================================================


@pytest.mark.parametrize(
    "raw",
    [
        "sqlite:///./data/promptcraft.db",
        "sqlite:///:memory:",
        "sqlite:///C:/absolute/path.db",
    ],
)
def test_local_sqlite_files_pass_through_untouched(raw):
    """ملفات SQLite المحلية تُمرَّر كما هي بلا أي لمس."""
    assert resolve(raw) == raw


# ============================================================
# د) التصنيف: is_turso / is_sqlite
# ============================================================


@pytest.mark.parametrize(
    "raw",
    [
        f"libsql://{TURSO_HOST}?authToken={TOKEN}",
        f"sqlite+libsql://{TURSO_HOST}?authToken={TOKEN}&secure=true",
    ],
)
def test_is_turso_detects_both_supported_schemes(raw):
    """كلا المخططين المدعومين يصفان اتصال Turso السحابي لا ملفًا محليًا."""
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


@pytest.mark.parametrize(
    "raw",
    ["postgresql://u:p@h:5432/db", "http://host.turso.io", "mysql://u:p@h/db"],
)
def test_unsupported_scheme_is_rejected_not_rewritten(raw):
    """
    ما خارج النطاق المدعوم لا يُصنَّف كـ Turso ولا كملف محلي، ويمرّ
    إلى `create_engine` كما هو. الكود لا يخترع صيغة لم يطلبها صاحب
    الإعداد — `create_engine` هو من يرفضها برسالة واضحة.
    """
    settings = Settings(DATABASE_URL=raw)
    assert settings.is_turso is False
    assert settings.is_sqlite is False
    assert settings.resolved_database_url == raw


# ============================================================
# هـ) database.py لا يطبّع — يمرّر ناتج config كما هو
# ============================================================


def test_database_module_does_not_reimplement_normalization():
    """
    التطبيع في مكان واحد فقط. لو نُسخت هنا لأمكن أن تنحرف إحدى النسختين
    عن الأخرى، والنتيجة قيمة قاعدة بيانات مختلفة في الإنتاج بلا أي
    اختبار يلحظ.
    """
    from app import database

    assert not hasattr(database, "_normalize_libsql_url")


def test_engine_uses_resolved_url_with_nullpool():
    """
    المحرك يأخذ الرابط من `config` مباشرةً، مع `NullPool` حتى لا تتنافس
    خيوط gunicorn على اتصال واحد.
    """
    import inspect

    from app.database import _build_engine

    source = inspect.getsource(_build_engine)
    assert "settings.resolved_database_url" in source
    assert "poolclass=NullPool" in source
    assert 'connect_args={"check_same_thread": False}' in source