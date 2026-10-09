"""اختبارات نقاط نهاية مكتبة البرومبتات.

تركيز الاختبارات على قاعدة واحدة تصعب مراقبتها بالعين: **المستخدم لا يرى
ولا يعدّل برومبتًا ليس له**. نستعمل مستخدمين اثنين ونتحقق أن أحدهما لا يطّلع
على برومبتات الآخر بأي طريقة — لا بقراءة ولا بحذف ولا بالإحصاءات.
"""

import pytest
from sqlalchemy import delete, select

from app.models import PromptHistory, User, utcnow


@pytest.fixture
def db(override_get_db):
    """جلسة على قاعدة بيانات الاختبار نفسها التي يستخدمها التطبيق."""
    session = next(override_get_db())
    yield session


@pytest.fixture
def two_users(db):
    """
    مستخدمان: `owner` و`other`.

    قاعدة بيانات الاختبار في الذاكرة وتُنشأ مرة واحدة لكل الجلسة (conftest)،
    فهي مشتركة بين كل الاختبارات. لذلك نبحث عن المستخدم أولًا ولا ننشئ إلا
    إن لم يكن موجودًا — إعادة الإنشاء في كل اختبار كانت ترفع خطأ UNIQUE.
    """
    users = {}
    for name in ("owner", "other"):
        user = db.scalar(select(User).where(User.username == name))
        if user is None:
            user = User(username=name)
            db.add(user)
        users[name] = user

    db.commit()
    for user in users.values():
        db.refresh(user)

    return users["owner"], users["other"]


@pytest.fixture
def seeded(two_users, db):
    """
    خمسة برومبتات لمستخدم `owner` وواحد لمستخدم `other`.

    نمسح سجلات هذين المستخدمَين أولًا لأن القاعدة مشتركة بين الاختبارات:
    بدون المسح تعتمد نتيجة كل اختبار على ما حذفه أو عدّله سابقه.
    """
    owner, other = two_users

    db.execute(
        delete(PromptHistory).where(PromptHistory.user_id.in_([owner.id, other.id]))
    )
    db.commit()

    rows = [
        PromptHistory(
            user_id=owner.id,
            raw_input="صورة تنين يطير فوق مدينة مستقبلية",
            generated_prompt="وصف بصري لتنين يطير فوق ناطحات سحاب",
            tool="midjourney",
            framework="co-star",
            language="ar",
        ),
        PromptHistory(
            user_id=owner.id,
            raw_input="مقال عن الذكاء الاصطناعي في التعليم",
            generated_prompt="اكتب مقالًا عن الذكاء الاصطناعي في التعليم",
            tool="chatgpt",
            framework="crispe",
            language="ar",
        ),
        PromptHistory(
            user_id=owner.id,
            raw_input="خطة تسويقية لحملة إطلاق منتج",
            generated_prompt="خطة تسويقية متكاملة للحملة",
            tool="claude",
            framework="co-star",
            language="ar",
        ),
        PromptHistory(
            user_id=owner.id,
            raw_input="refactor the auth module in the API",
            generated_prompt="Refactor the auth module and explain each change",
            tool="cursor",
            framework="5c",
            language="en",
        ),
        PromptHistory(
            user_id=owner.id,
            raw_input="شرح مبسط للذكاء الاصطناعي",
            generated_prompt="اشرح الذكاء الاصطناعي بلغة مبسطة",
            tool="chatgpt",
            framework="co-star",
            language="ar",
        ),
        PromptHistory(
            user_id=other.id,
            raw_input="سرّ خاص بالمستخدم الآخر",
            generated_prompt="محتوى لا يجوز أن يراه أحد",
            tool="gemini",
            framework="5c",
            language="ar",
        ),
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)

    return {"owner": owner, "other": other, "rows": rows}


def as_owner(auth_client, seeded):
    """
    يُسجّل دخول العميل باسم صاحب السجل (`owner`).

    نستدعيها في كل اختبار يتعامل مع بيانات مرتبطة بمعرّفات، لأن `auth_client`
    يسجّل باسم `tester` افتراضيًا — وهو لا يملك شيئًا من `seeded`.
    """
    auth_client.cookies.clear()
    response = auth_client.post(
        "/api/auth/login", json={"username": seeded["owner"].username}
    )
    assert response.status_code == 200, response.text
    return auth_client


# ============================================================
# أ) المصادقة
# ============================================================


def test_list_requires_auth(client):
    """بلا جلسة → 401، ولا تتسرّب أي بيانات."""
    assert client.get("/api/prompts").status_code == 401


def test_stats_requires_auth(client):
    assert client.get("/api/prompts/stats").status_code == 401


def test_get_requires_auth(client, seeded):
    target = seeded["rows"][0].id
    assert client.get(f"/api/prompts/{target}").status_code == 401


def test_delete_requires_auth(client, seeded):
    target = seeded["rows"][0].id
    assert client.delete(f"/api/prompts/{target}").status_code == 401


# ============================================================
# ب) القائمة
# ============================================================


def test_list_empty_for_new_user(auth_client):
    """مستخدم بلا سجل يرى قائمة فارجة لا كل شيء."""
    response = auth_client.get("/api/prompts")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["limit"] == 20
    assert body["offset"] == 0


def test_list_returns_only_own_prompts(auth_client, seeded):
    """القاعدة الأولى: لا يرى المستخدم إلا سجله هو."""
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts").json()

    assert body["total"] == 5
    assert len(body["items"]) == 5
    # وصف المستخدم الآخر غائب تمامًا
    assert all("سرّ خاص" not in item["raw_input"] for item in body["items"])


def test_list_search_matches_raw_input(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts", params={"search": "تنين"}).json()

    assert body["total"] == 1
    assert "تنين" in body["items"][0]["raw_input"]


def test_list_search_matches_generated_prompt(auth_client, seeded):
    """البحث يغطّي النص الناتج أيضًا لا الوصف فقط."""
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts", params={"search": "ناطحات"}).json()

    assert body["total"] == 1
    assert "تنين" in body["items"][0]["raw_input"]


def test_list_search_is_case_insensitive(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts", params={"search": "REFACTOR"}).json()

    assert body["total"] == 1


def test_list_search_no_match(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts", params={"search": "لن يوجد"}).json()

    assert body["total"] == 0
    assert body["items"] == []


def test_list_filter_by_tool(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts", params={"tool": "chatgpt"}).json()

    assert body["total"] == 2
    assert {item["tool"] for item in body["items"]} == {"chatgpt"}


def test_list_filter_by_framework(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts", params={"framework": "co-star"}).json()

    assert body["total"] == 3
    assert {item["framework"] for item in body["items"]} == {"co-star"}


def test_list_combines_filters(auth_client, seeded):
    """الأداة + الإطار معًا يعطيان تقاطعًا لا مجموعًا."""
    as_owner(auth_client, seeded)
    body = auth_client.get(
        "/api/prompts", params={"tool": "chatgpt", "framework": "co-star"}
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["raw_input"] == "شرح مبسط للذكاء الاصطناعي"


def test_list_total_reflects_filters(auth_client, seeded):
    """
    `total` يجب أن يطابق عوامل التصفية — لو كان الإجمالي الكلي لتأخّر
    الترقيم إلى ما لا نهاية عند الفلترة.
    """
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts", params={"tool": "chatgpt"}).json()

    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_pagination(auth_client, seeded):
    as_owner(auth_client, seeded)

    first = auth_client.get("/api/prompts", params={"limit": 2, "offset": 0}).json()
    second = auth_client.get("/api/prompts", params={"limit": 2, "offset": 2}).json()

    assert len(first["items"]) == 2
    assert len(second["items"]) == 2
    assert first["total"] == second["total"] == 5
    assert first["offset"] == 0 and second["offset"] == 2
    # بلا تكرار ولا نقص بين الصفحتين
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}


def test_list_pagination_last_page_partial(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts", params={"limit": 2, "offset": 4}).json()

    assert len(body["items"]) == 1
    assert body["total"] == 5


def test_list_pagination_past_end_returns_empty(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts", params={"limit": 2, "offset": 500}).json()

    assert body["items"] == []
    assert body["total"] == 5


def test_list_sort_oldest_puts_earliest_first(auth_client, seeded, db):
    as_owner(auth_client, seeded)
    rows = seeded["rows"]
    # نُرجع الصف الأول الأقدم عبر created_at
    rows[0].created_at = utcnow()
    rows[1].created_at = utcnow().replace(year=utcnow().year - 5)
    db.commit()

    oldest = auth_client.get("/api/prompts", params={"sort": "oldest", "limit": 1}).json()
    newest = auth_client.get("/api/prompts", params={"sort": "newest", "limit": 1}).json()

    assert oldest["items"][0]["id"] == rows[1].id
    assert newest["items"][0]["id"] != rows[1].id


def test_list_rejects_unknown_sort(auth_client, seeded):
    as_owner(auth_client, seeded)
    assert auth_client.get("/api/prompts", params={"sort": "sideways"}).status_code == 422


def test_list_rejects_bad_pagination(auth_client):
    assert auth_client.get("/api/prompts", params={"limit": 0}).status_code == 422
    assert auth_client.get("/api/prompts", params={"limit": 999}).status_code == 422
    assert auth_client.get("/api/prompts", params={"offset": -1}).status_code == 422


# ============================================================
# ج) الإحصاءات
# ============================================================


def test_stats_counts_only_own_prompts(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts/stats").json()

    assert body["total"] == 5
    assert sum(body["by_tool"].values()) == 5
    assert sum(body["by_framework"].values()) == 5


def test_stats_breakdown_by_tool(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts/stats").json()

    assert body["by_tool"] == {
        "midjourney": 1, "chatgpt": 2, "claude": 1, "cursor": 1,
    }
    assert "gemini" not in body["by_tool"]  # خاص بالمستخدم الآخر


def test_stats_breakdown_by_framework(auth_client, seeded):
    as_owner(auth_client, seeded)
    body = auth_client.get("/api/prompts/stats").json()

    assert body["by_framework"] == {"co-star": 3, "crispe": 1, "5c": 1}


def test_stats_last_7_days(auth_client, seeded, db):
    """ما قبل 7 أيام لا يُحسب، وما بعدها يُحسب."""
    as_owner(auth_client, seeded)
    rows = seeded["rows"]
    rows[0].created_at = utcnow().replace(year=utcnow().year - 5)
    rows[1].created_at = utcnow().replace(year=utcnow().year - 5)
    db.commit()

    body = auth_client.get("/api/prompts/stats").json()

    assert body["total"] == 5
    assert body["last_7_days"] == 3


def test_stats_is_not_shadowed_by_id_route(auth_client, seeded):
    """
    حارس على ترتيب المسارات: لو عُرّف `/{prompt_id}` قبل `/stats` لحاول
    FastAPI تحويل "stats" إلى int وأعاد 422 بدل الإحصاءات.
    """
    assert auth_client.get("/api/prompts/stats").status_code == 200


def test_stats_empty_for_new_user(auth_client):
    body = auth_client.get("/api/prompts/stats").json()

    assert body == {"total": 0, "by_tool": {}, "by_framework": {}, "last_7_days": 0}


# ============================================================
# د) برومبت واحد
# ============================================================


def test_get_prompt_by_id(auth_client, seeded):
    as_owner(auth_client, seeded)
    target = seeded["rows"][0]

    response = auth_client.get(f"/api/prompts/{target.id}")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == target.id
    assert response.json()["generated_prompt"] == target.generated_prompt


def test_get_prompt_missing_returns_404(auth_client):
    assert auth_client.get("/api/prompts/999999").status_code == 404


def test_get_prompt_of_other_user_returns_404(auth_client, seeded):
    """
    القاعدة الثانية: برومبت غير موجود وبرومبت غير مملوك يعطيان الرمز نفسه.

    نرجع 404 لا 403 عمدًا — الـ403 كان سيكشف وجود البرومبت لغير مالكه،
    فيتحوّل إلى ثغرة عدّاد تخمين المعرّفات.
    """
    as_owner(auth_client, seeded)
    foreign = [r for r in seeded["rows"] if r.user_id == seeded["other"].id][0]

    response = auth_client.get(f"/api/prompts/{foreign.id}")

    assert response.status_code == 404


def test_get_prompt_invalid_id_returns_422(auth_client):
    assert auth_client.get("/api/prompts/not-a-number").status_code == 422


# ============================================================
# هـ) الحذف
# ============================================================


def test_delete_prompt_success(auth_client, seeded):
    as_owner(auth_client, seeded)
    target = seeded["rows"][0]

    response = auth_client.delete(f"/api/prompts/{target.id}")

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert auth_client.get(f"/api/prompts/{target.id}").status_code == 404
    assert auth_client.get("/api/prompts/stats").json()["total"] == 4


def test_delete_prompt_missing_returns_404(auth_client):
    assert auth_client.delete("/api/prompts/999999").status_code == 404


def test_delete_prompt_of_other_user_returns_404_and_keeps_row(auth_client, seeded, db):
    """
    الحذف عبر معرّف غير مملوك يُرفض — والأهم: السجل يبقى سليمًا.

    لو رجع 403 هنا لكشفنا وجود السجل، ولو نُفّذ الحذف لخسر مالكُه برومبته.
    """
    as_owner(auth_client, seeded)
    foreign = [r for r in seeded["rows"] if r.user_id == seeded["other"].id][0]

    response = auth_client.delete(f"/api/prompts/{foreign.id}")

    assert response.status_code == 404
    db.expire_all()
    assert db.get(PromptHistory, foreign.id) is not None


def test_delete_then_list_reflects_removal(auth_client, seeded):
    as_owner(auth_client, seeded)
    target = seeded["rows"][0]

    auth_client.delete(f"/api/prompts/{target.id}")
    body = auth_client.get("/api/prompts").json()

    assert body["total"] == 4
    assert all(item["id"] != target.id for item in body["items"])


def test_delete_twice_returns_404_second_time(auth_client, seeded):
    as_owner(auth_client, seeded)
    target = seeded["rows"][0]

    assert auth_client.delete(f"/api/prompts/{target.id}").status_code == 200
    assert auth_client.delete(f"/api/prompts/{target.id}").status_code == 404