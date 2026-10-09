"""اختبارات سلسلة النماذج الاحتياطية في عميل OpenRouter."""

import asyncio

import pytest

from app.services import llm_client
from app.services.llm_client import (
    RETRYABLE_MODEL_STATUSES,
    LLMError,
    _model_candidates,
    chat_completion,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def ready(monkeypatch):
    """يمرّر فحص المفتاح دون اتصال فعلي."""
    monkeypatch.setattr(
        llm_client.settings, "OPENROUTER_API_KEY", "sk-or-v1-test", raising=False
    )
    monkeypatch.setattr(
        llm_client.settings,
        "OPENROUTER_MODELS_FALLBACK",
        ["fallback-a:free", "fallback-b:free"],
        raising=False,
    )
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: object())


# ============================================================
# أ) بناء السلسلة
# ============================================================


def test_candidates_put_primary_first(ready):
    assert _model_candidates("main:free") == ["main:free", "fallback-a:free", "fallback-b:free"]


def test_candidates_deduplicate(ready):
    """النموذج الأساسي إن كان في القائمة لا يتكرّر."""
    assert _model_candidates("fallback-a:free") == [
        "fallback-a:free",
        "fallback-b:free",
    ]


def test_candidates_skip_empty_entries(monkeypatch, ready):
    """الإدخال الفارغ في القائمة يُتجاهل ولا يصير اسم نموذج."""
    monkeypatch.setattr(
        llm_client.settings,
        "OPENROUTER_MODELS_FALLBACK",
        ["", "fallback-b:free", "   "],
        raising=False,
    )
    assert _model_candidates("main:free") == ["main:free", "fallback-b:free"]


def test_retryable_set_contains_expected_codes():
    assert RETRYABLE_MODEL_STATUSES == {404, 429, 503}


# ============================================================
# ب) الانتقال بين النماذج
# ============================================================


@pytest.mark.parametrize("http_status", [404, 429, 503])
def test_falls_back_on_retryable_status(monkeypatch, ready, http_status):
    """عند 404/429/503 ينتقل العميل إلى النموذج التالي حتى ينجح."""
    tried: list[str] = []

    async def fake(client, model, *args, **kwargs):
        tried.append(model)
        if len(tried) == 1:
            raise LLMError("فشل", status_code=502, http_status=http_status)
        return "رد ناجح"

    monkeypatch.setattr(llm_client, "_call_model", fake)

    text = run(chat_completion(messages=[{"role": "user", "content": "x"}], model="main:free"))

    assert text == "رد ناجح"
    assert tried == ["main:free", "fallback-a:free"]


def test_uses_mapped_status_503_not_displayed_502(monkeypatch, ready):
    """الرمز الأصلي 503 (المعروض 502) يجب أن يُعامَل كقابل لإعادة التوجيه."""
    tried: list[str] = []

    async def fake(client, model, *args, **kwargs):
        tried.append(model)
        if len(tried) < 3:
            raise LLMError("خطأ داخلي", status_code=502, http_status=503)
        return "نجح آخر نموذج"

    monkeypatch.setattr(llm_client, "_call_model", fake)

    text = run(chat_completion(messages=[{"role": "user", "content": "x"}], model="main:free"))

    assert text == "نجح آخر نموذج"
    assert tried == ["main:free", "fallback-a:free", "fallback-b:free"]


def test_does_not_fall_back_on_auth_error(monkeypatch, ready):
    """401 يعني مفتاحًا خاطئًا — تبديل النموذج لن يفيد، فيتوقف فورًا."""
    tried: list[str] = []

    async def fake(client, model, *args, **kwargs):
        tried.append(model)
        raise LLMError("مفتاح غير صالح", status_code=401, http_status=401)

    monkeypatch.setattr(llm_client, "_call_model", fake)

    with pytest.raises(LLMError) as exc:
        run(chat_completion(messages=[{"role": "user", "content": "x"}], model="main:free"))

    assert exc.value.status_code == 401
    assert tried == ["main:free"]


def test_raises_last_error_when_all_models_fail(monkeypatch, ready):
    """نفاد السلسلة يرفع آخر خطأ للمستخدم."""
    tried: list[str] = []

    async def fake(client, model, *args, **kwargs):
        tried.append(model)
        raise LLMError("غير موجود", status_code=404, http_status=404)

    monkeypatch.setattr(llm_client, "_call_model", fake)

    with pytest.raises(LLMError) as exc:
        run(chat_completion(messages=[{"role": "user", "content": "x"}], model="main:free"))

    assert exc.value.http_status == 404
    assert tried == ["main:free", "fallback-a:free", "fallback-b:free"]


def test_empty_response_does_not_trigger_fallback(monkeypatch, ready):
    """الرد الفارغ رمز 502 غير مُدرج في القائمة — لا نُبدّل النموذج."""
    tried: list[str] = []

    async def fake(client, model, *args, **kwargs):
        tried.append(model)
        raise LLMError("رد فارغ", status_code=502)

    monkeypatch.setattr(llm_client, "_call_model", fake)

    with pytest.raises(LLMError):
        run(chat_completion(messages=[{"role": "user", "content": "x"}], model="main:free"))

    assert tried == ["main:free"]