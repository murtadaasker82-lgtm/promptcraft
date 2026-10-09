"""اختبارات محرك هندسة البرومبتات ونقاط نقطته."""

import asyncio

import pytest

from app.config import settings
from app.services.llm_client import LLMError
from app.services.prompt_engine import (
    DEFAULT_FRAMEWORK,
    FRAMEWORKS,
    TOOL_TEMPLATES,
    generate_prompt,
    suggest_framework,
)


def run(coro):
    """يشغّل دالة async داخل الاختبار (pytest-anyio ليس مطلوبًا)."""
    return asyncio.run(coro)


# ============================================================
# أ) توليد البرومبت في وضع التجربة
# ============================================================


def test_generate_prompt_mock_returns_structured_markdown(mock_prompt_mode):
    """وضع التجربة: برومبت Markdown بعناوين كل أقسام الإطار، بلا أي اتصال."""
    result = run(
        generate_prompt(
            raw_input="أريد مقالًا عن الذكاء الاصطناعي",
            tool="chatgpt",
            framework="co-star",
            language="ar",
        )
    )

    assert result["mock_used"] is True
    assert result["framework"] == "co-star"
    assert result["tool"] == "chatgpt"
    assert result["language"] == "ar"
    assert result["model"] == "mock"
    assert result["tokens_used"] > 0

    prompt = result["prompt"]
    assert "أريد مقالًا عن الذكاء الاصطناعي" in prompt
    for section in FRAMEWORKS["co-star"]["sections"]:
        assert f"## {section['name_ar']}" in prompt


def test_generate_prompt_mock_respects_framework_and_tool(mock_prompt_mode):
    """الأداة والإطار المحددان ينعكسان على البرومبت الناتج."""
    result = run(
        generate_prompt(
            raw_input="صمم لي شعارًا لمقهى",
            tool="midjourney",
            framework="5c",
            language="ar",
        )
    )

    assert result["framework"] == "5c"
    assert result["tool_name"] == "Midjourney"
    assert "Midjourney" in result["prompt"]
    for section in FRAMEWORKS["5c"]["sections"]:
        assert f"## {section['name_ar']}" in result["prompt"]


def test_generate_prompt_english_mode(mock_prompt_mode):
    """اللغة الإنجليزية تنتج برومبتًا بمحتوى إنجليزي."""
    result = run(
        generate_prompt(
            raw_input="write a blog post about artificial intelligence",
            tool="general",
            framework="crispe",
            language="en",
        )
    )

    assert result["language"] == "en"
    assert "Mock mode" in result["prompt"]
    assert "write a blog post about artificial intelligence" in result["prompt"]
    for section in FRAMEWORKS["crispe"]["sections"]:
        assert f"## {section['name_ar']}" in result["prompt"]


def test_generate_prompt_rejects_empty_input(mock_prompt_mode):
    """الوصف الفارغ يرفع خطأ واضحًا بدل استدعاء النموذج."""
    with pytest.raises(LLMError) as exc_info:
        run(generate_prompt(raw_input="   ", mock=True))

    assert exc_info.value.status_code == 400


def test_generate_prompt_unknown_framework_falls_back(mock_prompt_mode):
    """إطار أو أداة غير معروفين يعودان إلى الافتراضي بدل رمي خطأ."""
    result = run(
        generate_prompt(
            raw_input="اكتب عن الطاقة المتجددة",
            framework="does-not-exist",
            tool="does-not-exist",
            mock=True,
        )
    )

    assert result["framework"] == DEFAULT_FRAMEWORK
    assert result["tool"] == "general"


# ============================================================
# ب) اقتراح الإطار
# ============================================================


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("اكتب لي مقال تسويقي عن تطبيقات الذكاء الاصطناعي", "co-star"),
        ("اكتب لي مقال تسويقي عن تطبيقات الذكاء الاصطناعي", "co-star"),
        ("أريد قائمة بخطوات مرتبة لعمل التطبيق", "crispe"),
        ("اكتب جدولًا يقارن بين الخيارات مع تحليل", "crispe"),
        ("اختصر لي الفكرة في جملة واحدة", "5c"),
        ("اشرح بشكل بسيط ما هو الذكاء الاصطناعي", "5c"),
        ("", DEFAULT_FRAMEWORK),
        ("مرحبا", DEFAULT_FRAMEWORK),
    ],
)
def test_suggest_framework(text, expected):
    """الكلمات المفتاحية تحدد الإطار المقترح."""
    suggestion = suggest_framework(text)

    assert suggestion["framework"] == expected
    assert suggestion["name_ar"] == FRAMEWORKS[expected]["name_ar"]
    assert 0.0 <= suggestion["confidence"] <= 1.0
    assert suggestion["reason_ar"]


def test_suggest_framework_returns_alternatives():
    """نص فيه أكثر من إشارة يعيد بدائل مرتبة."""
    suggestion = suggest_framework("اكتب قائمة مقارنة وتحليل لمقال تسويقي")

    assert suggestion["framework"] in FRAMEWORKS
    assert isinstance(suggestion["alternatives"], list)


# ============================================================
# ج) نقاط النهاية
# ============================================================


def test_generate_endpoint_requires_auth(client):
    """بدون جلسة → 401."""
    response = client.post(
        "/api/prompt/generate",
        json={"input": "أريد مقال عن الذكاء الاصطناعي"},
    )
    assert response.status_code == 401


def test_generate_endpoint_mock(auth_client, mock_prompt_mode):
    """طلب محمي ينجح ويعيد البرومبت ويحفظه في السجل."""
    response = auth_client.post(
        "/api/prompt/generate",
        json={
            "input": "أريد مقال عن الذكاء الاصطناعي",
            "tool": "chatgpt",
            "framework": "co-star",
            "language": "ar",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["mock_used"] is True
    assert data["saved"] is True
    assert data["history_id"] is not None
    assert "الذكاء الاصطناعي" in data["prompt"]
    assert "## الهدف" in data["prompt"]


def test_generate_endpoint_persists_history(auth_client, mock_prompt_mode):
    """السجل يحتوي العنصر الجديد بعد التوليد."""
    auth_client.post(
        "/api/prompt/generate",
        json={"input": "اكتب عن الطاقة المتجددة", "tool": "claude"},
    )

    response = auth_client.get("/api/prompt/history")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 1
    assert items[0]["tool"] == "claude"


def test_generate_endpoint_validates_body(auth_client):
    """حقل input الناقص أو قصير جدًا أو لغة غير مدعومة → 422."""
    assert auth_client.post("/api/prompt/generate", json={}).status_code == 422

    short = auth_client.post("/api/prompt/generate", json={"input": "ا"})
    assert short.status_code == 422

    bad_language = auth_client.post(
        "/api/prompt/generate",
        json={"input": "مقال عن الذكاء الاصطناعي", "language": "fr"},
    )
    assert bad_language.status_code == 422


def test_enhance_endpoint_mock(auth_client, mock_prompt_mode):
    """التحسين في وضع التجربة يعيد نصًا محسّنًا."""
    response = auth_client.post(
        "/api/prompt/enhance",
        json={"prompt": "اكتب مقال عن الذكاء الاصطناعي"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["mock_used"] is True
    assert "إضافات مقترحة" in data["prompt"]


def test_frameworks_endpoint(auth_client):
    """قائمة الأطر والأدوات متاحة للمستخدم المسجّل."""
    response = auth_client.get("/api/prompt/frameworks")

    assert response.status_code == 200
    data = response.json()
    assert data["default_framework"] == DEFAULT_FRAMEWORK
    assert len(data["frameworks"]) == len(FRAMEWORKS)
    assert len(data["tools"]) == len(TOOL_TEMPLATES)
    assert {"id": "chatgpt", "name_ar": "ChatGPT", "description_ar": "نماذج OpenAI المحادثة — رد نصي أو تحليلي منظّم."} in data["tools"]


def test_suggest_endpoint(auth_client):
    """اقتراح الإطار عبر HTTP."""
    response = auth_client.get(
        "/api/prompt/suggest",
        params={"text": "اكتب لي مقال تسويقي عن"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["framework"] == "co-star"
    assert data["framework_name"] == "CO-STAR"
    assert data["confidence"] > 0


def test_clear_history_endpoint(auth_client, mock_prompt_mode):
    """حذف السجل يعمل ويعيد العدد."""
    auth_client.post("/api/prompt/generate", json={"input": "اكتب عن الذكاء الاصطناعي"})

    deleted = auth_client.delete("/api/prompt/history")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] >= 1

    assert auth_client.get("/api/prompt/history").json()["items"] == []


def test_health_reports_prompt_config(client):
    """فحص الصحة يذكر حالة محرك البرومبتات."""
    data = client.get("/api/health").json()

    assert "prompt_mock" in data
    assert "openrouter_configured" in data
    assert data["openrouter_model"] == settings.OPENROUTER_MODEL