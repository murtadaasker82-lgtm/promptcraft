"""اختبارات الذاكرة المؤقتة لنتائج محرك البرومبت."""

import asyncio

from app.services.prompt_engine import (
    _cache_get,
    _cache_key,
    _cache_put,
    clear_prompt_cache,
)


def run(coro):
    return asyncio.run(coro)


# ============================================================
# أ) مفتاح الكاش
# ============================================================


def test_key_depends_on_every_input_dimension():
    """تغيّر أي بُعد (وصف/أداة/إطار/لغة) يعطي مفتاحًا مختلفًا."""
    base = _cache_key("وصف", "general", "co-star", "ar")

    assert _cache_key("وصف آخر", "general", "co-star", "ar") != base
    assert _cache_key("وصف", "midjourney", "co-star", "ar") != base
    assert _cache_key("وصف", "general", "crispe", "ar") != base
    assert _cache_key("وصف", "general", "co-star", "en") != base
    # الفراغات الطرفية لا تغيّر المعنى
    assert _cache_key("  وصف  ", "general", "co-star", "ar") == base


# ============================================================
# ب) التخزين والجلب والانتهاء
# ============================================================


def test_put_then_get_marks_cached():
    clear_prompt_cache()
    key = _cache_key("وصف", "general", "co-star", "ar")

    _cache_put(key, {"prompt": "برومبت"})
    hit = _cache_get(key)

    assert hit is not None
    assert hit["prompt"] == "برومبت"
    assert hit["cached"] is True


def test_get_returns_none_on_miss():
    clear_prompt_cache()
    assert _cache_get(_cache_key("لم يُخزَّن", "general", "co-star", "ar")) is None


def test_get_ignores_expired_entry(monkeypatch):
    """ما تجاوز عمره PROMPT_CACHE_TTL يُتجاهل ويُحذف."""
    from app.config import settings

    clear_prompt_cache()
    key = _cache_key("قديم", "general", "co-star", "ar")
    _cache_put(key, {"prompt": "قديم"})

    monkeypatch.setattr(settings, "PROMPT_CACHE_TTL", 0, raising=False)

    assert _cache_get(key) is None


def test_disabled_cache_never_stores(monkeypatch):
    """مع PROMPT_CACHE_ENABLED=false لا يُخزَّن شيء ولا يُقرأ شيء."""
    from app.config import settings

    clear_prompt_cache()
    monkeypatch.setattr(settings, "PROMPT_CACHE_ENABLED", False, raising=False)

    key = _cache_key("وصف", "general", "co-star", "ar")
    _cache_put(key, {"prompt": "لا يُحفظ"})

    assert _cache_get(key) is None
    assert clear_prompt_cache() == 0


# ============================================================
# ج) حدود الحجم
# ============================================================


def test_cache_respects_max_size(monkeypatch):
    """عند تجاوز PROMPT_CACHE_SIZE يُحذف الأقدم."""
    from app.config import settings

    clear_prompt_cache()
    monkeypatch.setattr(settings, "PROMPT_CACHE_SIZE", 3, raising=False)

    keys = [_cache_key(f"وصف {i}", "general", "co-star", "ar") for i in range(5)]
    for key in keys:
        _cache_put(key, {"prompt": key})

    from app.services.prompt_engine import _prompt_cache

    assert len(_prompt_cache) == 3
    # الأقدمان طارا، والأحدث ثلاثة باقية
    assert _cache_get(keys[0]) is None
    assert _cache_get(keys[1]) is None
    assert _cache_get(keys[4]) is not None


def test_clear_returns_count():
    clear_prompt_cache()
    _cache_put(_cache_key("أ", "general", "co-star", "ar"), {"prompt": "x"})
    _cache_put(_cache_key("ب", "general", "co-star", "ar"), {"prompt": "y"})

    assert clear_prompt_cache() == 2
    assert clear_prompt_cache() == 0