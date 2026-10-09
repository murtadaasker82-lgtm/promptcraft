"""
النسخ الاحتياطي لقاعدة البيانات.

لماذا نسخة قبل كل إقلاع: `init_db()` ينشئ الجداول، وأي هجرة مستقبلية قد
تغيّر الشكل. نسخة مؤرّخة كل تشغيل تجعل التراجع عملية نسخ ملف واحد.

الاحتفاظ سبعة أيام افتراضيًا، والحذفOlder يتم بالمقارنة بالتاريخ لا بعدد
الملفات، فلا يتأثّر الحدّ بمعدّل الإقلاع.
"""

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from app.config import BASE_DIR, settings

logger = logging.getLogger("promptcraft.backup")

# بنية اسم النسخة: promptcraft_YYYYMMDD_HHMMSS.db
STAMP_FORMAT = "%Y%m%d_%H%M%S"
BACKUP_DIRNAME = "backups"


class BackupError(Exception):
    """فشل إنشاء أو استرجاع نسخة."""


def database_path() -> Path | None:
    """
    مسار ملف SQLite من `DATABASE_URL`، أو None إذا لم تكن SQLite.

    `DATABASE_URL` في ملف .env نسبي (`./data/promptcraft.db`) بينما الافتراضي
    في `config.py` مطلق — نتعامل مع الصيغتين.
    """
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        return None

    raw = url.replace("sqlite:///", "", 1).lstrip("/")
    path = Path(raw)
    if not path.is_absolute():
        # نعتمد BASE_DIR لا المسار النسبي للprocess: تشغيل الخادم من مجلد
        # آخر كان سيجعل النسخ يكتب إلى `app/data/` بالخطأ.
        path = (BASE_DIR / path).resolve()
    return path


def backup_dir() -> Path:
    """مجلد النسخ — beside ملف قاعدة البيانات لا في مكان عام."""
    db_path = database_path()
    base = db_path.parent if db_path else Path(settings.UPLOAD_DIR).parent
    return base / BACKUP_DIRNAME


def _is_backup_file(path: Path) -> bool:
    """هل هذا ملف نسخة صالحة باسم مطابق للبنية؟"""
    name = path.name
    if not name.startswith("promptcraft_") or path.suffix != ".db":
        return False
    stamp = name[len("promptcraft_"):-len(".db")]
    try:
        datetime.strptime(stamp, STAMP_FORMAT)
    except ValueError:
        return False
    return True


def prune_backups(keep_days: int | None = None) -> list[str]:
    """
    يحذف النسخ الأقدم من `keep_days` يومًا.

    :returns: أسماء الملفات المحذوفة
    """
    days = settings.BACKUP_KEEP_DAYS if keep_days is None else keep_days
    directory = backup_dir()
    if not directory.exists():
        return []

    cutoff = datetime.now() - timedelta(days=days)
    removed: list[str] = []

    for path in directory.glob("promptcraft_*.db"):
        if not _is_backup_file(path):
            continue
        stamp = datetime.strptime(path.stem[len("promptcraft_"):], STAMP_FORMAT)
        if stamp < cutoff:
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as exc:
                logger.warning("تعذّر حذف النسخة القديمة %s: %s", path.name, exc)

    if removed:
        logger.info("حُذفت %s نسخة أقدم من %s يومًا", len(removed), days)

    return removed


def create_backup() -> Path | None:
    """
    ينسخ قاعدة البيانات إلى `data/backups/promptcraft_YYYYMMDD_HHMMSS.db`.

    :returns: مسار النسخة، أو None إن كان التعطيل مفعّلًا أو القاعدة ليست SQLite
        أو الملف غير موجود.
    """
    if not settings.BACKUP_ENABLED:
        logger.debug("النسخ الاحتياطي معطّل (BACKUP_ENABLED=false)")
        return None

    db_path = database_path()
    if db_path is None:
        logger.info("قاعدة البيانات ليست SQLite — تُخطّى النسخ الاحتياطي")
        return None
    if not db_path.exists():
        logger.warning("ملف قاعدة البيانات غير موجود: %s — تُخطّى النسخ", db_path)
        return None

    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime(STAMP_FORMAT)
    target = directory / f"promptcraft_{stamp}.db"

    try:
        # copy2 لا copy: نحافظ على بيانات الأوقات (mtime) لتعمل التنظيفات
        shutil.copy2(db_path, target)
    except OSError as exc:
        # فشل النسخ لا يجوز أن يمنع الخادم من الإقلاع
        logger.error("فشل إنشاء نسخة احتياطية: %s", exc)
        return None

    logger.info("أُنشئت نسخة احتياطية: %s", target.name)

    prune_backups()

    return target


def restore_backup(filename: str) -> Path:
    """
    يسترجع نسخة مكان قاعدة البيانات الحالية.

    :param filename: اسم ملف النسخة فقط (مثل `promptcraft_20260101_120000.db`)
    :returns: مسار قاعدة البيانات بعد الاسترجاع
    :raises BackupError: اسم غير صالح، أو نسخة غير موجودة، أو فشل الكتابة
    """
    db_path = database_path()
    if db_path is None:
        raise BackupError("الاسترجاع متاح لقواعد SQLite فقط")

    # حارس اجتياز المسارات: نقبل اسمًا عاديًا فقط، بلا مسارات ولا `..`
    if Path(filename).name != filename or not _is_backup_file(Path(filename)):
        raise BackupError("اسم ملف النسخة غير صالح")

    source = backup_dir() / filename
    if not source.exists():
        raise BackupError(f"النسخة غير موجودة: {filename}")

    # نأخذ نسخة أمان من الحالة الراهنة قبل أن نستبدلها
    try:
        if db_path.exists():
            stamp = datetime.now().strftime(STAMP_FORMAT)
            safety = backup_dir() / f"promptcraft_{stamp}.db"
            shutil.copy2(db_path, safety)
            logger.info("حُفظت الحالة الحالية في %s قبل الاسترجاع", safety.name)

        shutil.copy2(source, db_path)
    except OSError as exc:
        raise BackupError(f"فشل الاسترجاع: {exc}") from exc

    logger.warning("استُرجعت قاعدة البيانات من %s — أعد تشغيل الخادم", filename)
    return db_path


def list_backups() -> list[dict]:
    """قائمة النسخ المتاحة، الأحدث أولًا."""
    directory = backup_dir()
    if not directory.exists():
        return []

    files = [p for p in directory.glob("promptcraft_*.db") if _is_backup_file(p)]
    files.sort(key=lambda p: p.stem, reverse=True)

    return [
        {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        }
        for path in files
    ]


__all__ = [
    "BackupError",
    "backup_dir",
    "create_backup",
    "database_path",
    "list_backups",
    "prune_backups",
    "restore_backup",
]