"""
ترحيل أسماء المستخدمين لتوافق قاعدة "حروف فقط".

قبل: `USERNAME_PATTERN` كان `[A-Za-z0-9_.-]{3,32}` فكان يقبل `Mortada-Asker` و`user1`.
بعد: صار `[A-Za-z <عربية>]{2,30}`، فكل اسم قديم فيه رقم أو رمز صار مرفوضًا عند
تسجيل الدخول — ولا يستطيع صاحبه الدخول مجددًا.

هذا السكريبت يقرأ جدول المستخدمين ويصلح الأسماء المخالفة:
* يستبدل كل حرف أو رمز خارج (حروف + مسافة) بمسافة، ثم يطمس المسافات المكررة.
* إن كان الاسم الجديد فارغًا بعد التنظيف → يحذف المستخدم (لا فائدة منه).
* إن كان الاسم الجديد محجوزًا لمستخدم آخر → يحذف المستخدم المتعارض بدل أن
  يضيف رقمًا (الرقم يخالف القاعدة الجديدة).

يحذف نُسخة احتياطية من ملف قاعدة البيانات قبل أي تعديل، وبالوضع التجريبي
(بدون ‎--apply‎) لا يكتب شيئًا.

الاستخدام:
    python scripts/migrate_usernames.py            # معاينة فقط
    python scripts/migrate_usernames.py --apply    # تنفيذ
    python scripts/migrate_usernames.py --apply --delete-collisions
"""

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# جعل المشروع قابلًا للاستيراد عند التشغيل من أي مجلد
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import User  # noqa: E402
from app.schemas import USERNAME_PATTERN  # noqa: E402

BACKUP_DIR = ROOT / "data" / "backups"


def sanitize(raw: str) -> str:
    """
    يحوّل اسمًا قديمًا إلى اسم يطابق `USERNAME_PATTERN`.

    يستبدل كل حرف/رمز غير مسموح بمسافة ثم يطمس المسافات المكررة والطرفية،
    فيصير `Mortada-Asker` ← `Mortada Asker`.
    """
    allowed = re.compile(r"[^A-Za-z؀-ي ]")
    cleaned = allowed.sub(" ", raw)
    return " ".join(cleaned.split())


def is_valid(name: str) -> bool:
    """هل يطابق الاسم قاعدة الدخول الحالية؟"""
    return bool(re.match(USERNAME_PATTERN, name))


def db_file_path() -> Path | None:
    """مسار ملف SQLite من `DATABASE_URL`، أو None إذا لم تكن SQLite."""
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        return None
    raw = url.replace("sqlite:///", "", 1).lstrip("/")
    path = Path(raw)
    return path if not path.is_absolute() else path


def backup(path: Path) -> Path:
    """ينسخ ملف قاعدة البيانات إلى `data/backups/` ويعيد مسار النسخة."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"{path.stem}-{stamp}{path.suffix}"
    shutil.copy2(path, target)
    return target


def render_table(rows: list[tuple], headers: tuple[str, ...]) -> str:
    """جدول نصّي محاذى (العرض بالبايت لا بالحرف، فلا نضبط العربية تمامًا)."""
    lines = []
    body = [tuple(str(cell) for cell in row) for row in rows]
    widths = [
        max(len(headers[i]), max((len(r[i]) for r in body), default=0))
        for i in range(len(headers))
    ]

    def fmt(cells):
        return " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))

    lines.append(fmt(headers))
    lines.append("-+-".join("-" * w for w in widths))
    lines.extend(fmt(r) for r in body)
    return "\n".join(lines)


def plan(session, delete_collisions: bool):
    """
    يبني خطة الترحيل دون كتابة شيء.

    :returns: (rename_map, to_delete, untouched) где
        rename_map = [(user_id, old, new, status)] و to_delete = [(id, username, reason)]
    """
    users = session.scalars(select(User).order_by(User.id)).all()
    taken = {u.username.lower(): u.id for u in users}

    renames, deletions, untouched = [], [], []

    for user in users:
        if is_valid(user.username):
            untouched.append((user.id, user.username, "سليم"))
            continue

        new_name = sanitize(user.username)

        if not new_name:
            deletions.append((user.id, user.username, "فارغ بعد التنظيف"))
            continue

        if not is_valid(new_name):
            deletions.append((user.id, user.username, f"لا يطابق القاعدة بعد التنظيف: {new_name!r}"))
            continue

        owner = taken.get(new_name.lower())
        if owner is not None and owner != user.id:
            deletions.append((user.id, user.username, f"محتَرَب مع {new_name!r} (المستخدم {owner})"))
            continue

        renames.append((user.id, user.username, new_name, "تغيير اسم"))

    if not delete_collisions:
        deletions = [d for d in deletions if "المستخدم" in d[2]]

    return renames, deletions, untouched


def apply_plan(session, renames, deletions) -> tuple[int, int]:
    """ينفّذ الخطة ويعيد (عدد التغييرات، عدد الحذف)."""
    for user_id, _old, new_name, _status in renames:
        user = session.get(User, user_id)
        user.username = new_name

    for user_id, _name, _reason in deletions:
        user = session.get(User, user_id)
        # حذف المتتالي مطبَّق في relationships (cascade="all, delete-orphan")
        session.delete(user)

    session.commit()
    return len(renames), len(deletions)


def main() -> int:
    parser = argparse.ArgumentParser(description="ترحيل أسماء المستخدمين")
    parser.add_argument("--apply", action="store_true", help="نفّذ التغييرات فعلًا")
    parser.add_argument(
        "--delete-collisions",
        action="store_true",
        help="احذف المستخدم عندما يكون اسمه الجديد محجوزًا (يمحو سجلّه)",
    )
    args = parser.parse_args()

    path = db_file_path()
    if path is None:
        print("DATABASE_URL ليس SQLite — تخطّى الترحيل.")
        return 1
    if not path.exists():
        print(f"لم أجد ملف قاعدة البيانات: {path}")
        return 1

    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Session = sessionmaker(bind=engine, autoflush=False)
    session = Session()

    before = [(u.id, u.username) for u in session.scalars(select(User).order_by(User.id)).all()]

    print("=" * 78)
    print("الحالة قبل الترحيل")
    print("=" * 78)
    print(render_table(before, ("id", "username")) if before else "لا يوجد مستخدمون.")

    renames, deletions, untouched = plan(session, args.delete_collisions)

    print()
    print("=" * 78)
    print("الخطة")
    print("=" * 78)
    print(render_table(renames, ("id", "قبل", "بعد", "الحالة")) if renames else "لا تغييرات أسماء.")
    print()
    print(render_table(deletions, ("id", "username", "السبب")) if deletions else "لا حذف.")

    ok_count = len([r for r in untouched if r[2] == "سليم"])
    print()
    print(f"سليمون: {ok_count} | تغييرات: {len(renames)} | حذف: {len(deletions)}")

    if not args.apply:
        print()
        print("وضع المعاينة — لم يُكتب شيء. أعد التشغيل بـ --apply للتنفيذ.")
        return 0

    print()
    saved = backup(path)
    print(f"نسخة احتياطية: {saved.relative_to(ROOT)}")

    changed, deleted = apply_plan(session, renames, deletions)

    after = [(u.id, u.username) for u in session.scalars(select(User).order_by(User.id)).all()]

    print()
    print("=" * 78)
    print("الحالة بعد الترحيل")
    print("=" * 78)
    print(render_table(after, ("id", "username")) if after else "لا يوجد مستخدمون.")

    print()
    print(f"تم: {changed} تغيير، {deleted} حذف.")

    # تحقق أخير: كل الأسماء الحالية يجب أن تمرّ بقاعدة الدخول
    invalid = [n for _i, n in after if not is_valid(n)]
    if invalid:
        print(f"تحذير: أسماء ما زالت مخالفة: {invalid}")
        return 1

    print("تحقّق نهائي: كل الأسماء تطابق قاعدة الدخول الحالية.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())