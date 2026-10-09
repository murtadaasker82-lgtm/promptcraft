"""
عميل LLM موحّد عبر OpenRouter.

OpenRouter يوفّر واجهة متوافقة مع OpenAI SDK، لذلك نستخدم `AsyncOpenAI` مع
تغيير `base_url` فقط. كل استدعاء يمرّ من هنا حتى يكون مكان التعامل مع
الأخطاء والمهل واحدًا لكل التطبيق.

مثال:
    from app.services.llm_client import chat_completion
    نص = await chat_completion([{"role": "user", "content": "مرحبا"}])
"""

import asyncio
import logging
import random
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)

from app.config import settings

logger = logging.getLogger("promptcraft.llm")

# نسخة واحدة من العميل لكل عملية (العميل آمن للاستخدام المتزامن).
_client: AsyncOpenAI | None = None


class LLMError(Exception):
    """خطأ في استدعاء النموذج — يحمل رمز HTTP ورسالة عربية جاهزة للعرض."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        # الرمز الأصلي من الخدمة قبل التحويل (مثل 503 الذي نعرضه 502).
        # سلسلة النماذج الاحتياطية تحكم على هذا لا على status_code المعروض.
        self.http_status = http_status


def get_llm_client() -> AsyncOpenAI:
    """
    يعيد عميل AsyncOpenAI مربوطًا بـ OpenRouter.

    يُنشأ مرة واحدة ويُعاد استخدامه (الاتصال محفوظ داخليًا في العميل).
    """
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
            timeout=settings.OPENROUTER_TIMEOUT,
            max_retries=0,  # نتحكم بأنفسنا في إعادة المحاولة برسائل عربية
            default_headers={
                # مطلوبان لإحصاءات OpenRouter فقط، لكن نرسلهما دائمًا
                "HTTP-Referer": settings.OPENROUTER_HTTP_REFERER,
                "X-Title": settings.OPENROUTER_APP_TITLE,
            },
        )
        logger.debug(
            "تم إنشاء عميل OpenRouter (base_url=%s, model=%s)",
            settings.OPENROUTER_BASE_URL,
            settings.OPENROUTER_MODEL,
        )
    return _client


def reset_llm_client() -> None:
    """
    يتخلّص من العميل المخزَّن.

    يُستخدم في الاختبارات بعد تغيير الإعدادات (القيم تُقرأ عند الإنشاء).
    """
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:  # noqa: BLE001 — الإغلاق اختياري
            pass
    _client = None


def _map_status_error(exc: APIStatusError, model: str | None = None) -> LLMError:
    """يحوّل خطأ HTTP من الخدمة إلى رسالة عربية مفهومة + رمز مناسب."""
    status = exc.status_code
    attempted = model or settings.OPENROUTER_MODEL

    if status in (401, 403):
        return LLMError(
            "مفتاح OpenRouter غير صالح أو منتهي. افتح https://openrouter.ai/keys "
            "وأنشئ مفتاحًا جديدًا ثم حدّث OPENROUTER_API_KEY في ملف .env.",
            status_code=401,
            http_status=status,
        )

    if status == 402:
        return LLMError(
            "رصيد حسابك في OpenRouter غير كافٍ لإتمام الطلب. "
            "أضف رصيدًا أو استخدم نموذجًا مجانيًا ( ending بـ :free ).",
            status_code=402,
            http_status=status,
        )

    if status == 429:
        return LLMError(
            "تم تجاوز حد الاستخدام مؤقتًا (429). غالبًا لأن النموذج مزدحم أو "
            "أن مفتاحك بلا رصيد. انتظر دقيقة ثم أعد المحاولة، أو غيّر النموذج.",
            status_code=429,
            http_status=status,
        )

    if status == 404:
        return LLMError(
            f"النموذج المطلوب غير موجود على OpenRouter: {attempted}. "
            "تحقق من الاسم في https://openrouter.ai/models",
            status_code=404,
            http_status=status,
        )

    if status >= 500:
        return LLMError(
            "خدمة OpenRouter تواجه خطأ داخليًا مؤقتًا — أعد المحاولة بعد قليل.",
            status_code=502,
            http_status=status,
        )

    return LLMError(
        f"رفضت OpenRouter الطلب (رمز {status}). راجع نص الطلب أو مفتاحك ثم أعد المحاولة.",
        status_code=502,
        http_status=status,
    )


async def _collect_stream(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
) -> str:
    """
    يجمع نص الرد من بثّ تدريجي (streaming) بدل انتظار الرد الكامل.

    البث يقلّل زمن الاستجابة المحسوس: أول جزء من النص يصل قبل أن يُنهي النموذج
    توليده، ولا نفعّل البث عمليًا في قياس زمن الواجهة لأن الواجهة تنتظر الرد
    الكامل في كل الأحوال.
    """
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    parts: list[str] = []
    async for chunk in stream:
        if not chunk.choices:
            continue
        piece = chunk.choices[0].delta.content
        if piece:
            parts.append(piece)

    return "".join(parts).strip()


# رموز خطأ تعني "هذا النموذج لا يعمل الآن" فنجرّب التالي بدل الفشل النهائي.
# 404 مُدرجة لأن قوائم النماذج المجانية تتغيّر باستمرار واسم قديم يعود 404.
RETRYABLE_MODEL_STATUSES = frozenset({404, 429, 503})


def _model_candidates(model: str) -> list[str]:
    """
    ترتيب النماذج المُجرَّبة: الأساسي أولًا ثم قائمة الاحتياطية بلا تكرار.
    """
    chain = [model]
    for raw in settings.OPENROUTER_MODELS_FALLBACK:
        fallback = (raw or "").strip()
        if fallback and fallback not in chain:
            chain.append(fallback)
    return chain


async def _call_model(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    max_attempts: int,
    stream: bool,
) -> str:
    """محاولات متكرّرة على نموذج واحد. يرمي `LLMError` عند الفشل النهائي."""
    last_error: LLMError | None = None

    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            if stream:
                text = await _collect_stream(
                    client, model, messages, temperature, max_tokens
                )
            else:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                text = (response.choices[0].message.content or "").strip()

            if not text:
                raise LLMError(
                    "أعاد النموذج إجابة فارغة. جرّب صياغة الوصف بتفصيل أكبر "
                    "أو غيّر النموذج.",
                    status_code=502,
                )
            elapsed = time.perf_counter() - started
            logger.info(
                "اكتمل الاستدعاء في %.2fث (model=%s، بث=%s، محاولات=%s، "
                "%s حرف، حد=%s رمز)",
                elapsed,
                model,
                "نعم" if stream else "لا",
                attempt,
                len(text),
                max_tokens,
            )
            return text

        except AuthenticationError as exc:
            # لا فائدة من إعادة المحاولة — المفتاح خطأ
            raise _map_status_error(exc, model) from exc

        except NotFoundError as exc:
            # 404 لا يتحسّن بتكرار المحاولة على نفس النموذج — نُرجع الفشل
            # فورًا ليتولّاه متصفح النماذج فيجرّب اسمًا آخر.
            raise _map_status_error(exc, model) from exc

        except RateLimitError as exc:
            last_error = _map_status_error(exc, model)
            if attempt == max_attempts:
                raise last_error from exc
            wait = 2**attempt + random.random()
            logger.warning(
                "حد معدل من OpenRouter بعد %.2fث (model=%s) — إعادة المحاولة "
                "%s/%s بعد %.1fs",
                time.perf_counter() - started, model, attempt, max_attempts, wait,
            )
            await asyncio.sleep(wait)

        except InternalServerError as exc:
            last_error = _map_status_error(exc, model)
            if attempt == max_attempts:
                raise last_error from exc
            wait = 1.5 * attempt
            logger.warning(
                "خطأ 5xx من OpenRouter بعد %.2fث (model=%s) — إعادة المحاولة %s/%s",
                time.perf_counter() - started, model, attempt, max_attempts,
            )
            await asyncio.sleep(wait)

        except APIStatusError as exc:
            mapped = _map_status_error(exc, model)
            # 4xx الأخرى لا تُفيد بإعادة المحاولة
            if exc.status_code < 500 or attempt == max_attempts:
                raise mapped from exc
            last_error = mapped
            await asyncio.sleep(1.5 * attempt)

        except APIConnectionError as exc:
            last_error = LLMError(
                "تعذّر الاتصال بـ OpenRouter. تحقق من الإنترنت ثم أعد المحاولة.",
                status_code=502,
            )
            if attempt == max_attempts:
                raise last_error from exc
            logger.warning(
                "فشل الاتصال بـ OpenRouter بعد %.2fث — إعادة المحاولة %s/%s",
                time.perf_counter() - started, attempt, max_attempts,
            )
            await asyncio.sleep(1.5 * attempt)

        except APIError as exc:
            raise LLMError(
                f"خطأ من عميل OpenRouter: {exc}",
                status_code=502,
            ) from exc

    raise last_error or LLMError("فشل توليد البرومبت", status_code=502)


async def chat_completion(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_attempts: int = 3,
    stream: bool = True,
) -> str:
    """
    يستدعي نموذج محادثة ويعيد نص الإجابة فقط.

    جرّب النموذج المطلوب أولًا، فإن فشل برمز من `RETRYABLE_MODEL_STATUSES`
    انتقل تلقائيًا إلى بقية `OPENROUTER_MODELS_FALLBACK`.

    :param messages: قائمة رسائل بصيغة OpenAI: [{"role": ..., "content": ...}]
    :param model: اسم النموذج؛ الافتراضي من الإعدادات
    :param temperature: 0 = حتمي، 1 = إبداعي
    :param max_tokens: حد أعلى لطول الإجابة؛ الافتراضي `PROMPT_MAX_TOKENS`
    :param max_attempts: عدد المحاولات لكل نموذج
    :param stream: True للبثّ التدريجي (أسرع استجابة)، False لطلب عادي
    :returns: نص الإجابة بعد تنظيفه
    :raises LLMError: عند غياب المفتاح أو فشل كل النماذج
    """
    if not settings.openrouter_ready:
        raise LLMError(
            "مفتاح OpenRouter غير مضبوط. أضف OPENROUTER_API_KEY في ملف .env ثم أعد "
            "تشغيل الخادم. (تجده في: https://openrouter.ai/keys)",
            status_code=503,
        )

    if not messages:
        raise LLMError("لا توجد رسائل لإرسالها", status_code=400)

    model = model or settings.OPENROUTER_MODEL
    max_tokens = max_tokens or settings.PROMPT_MAX_TOKENS
    client = get_llm_client()

    candidates = _model_candidates(model)
    last_error: LLMError | None = None

    for index, candidate in enumerate(candidates):
        try:
            return await _call_model(
                client, candidate, messages, temperature, max_tokens, max_attempts, stream
            )
        except LLMError as exc:
            last_error = exc
            has_next = index < len(candidates) - 1
            # نحكم على الرمز الأصلي من الخدمة لا على المعروض (503 تُعرض 502)
            http_status = exc.http_status if exc.http_status is not None else exc.status_code
            if http_status not in RETRYABLE_MODEL_STATUSES or not has_next:
                raise
            logger.warning(
                "النموذج %s فشل (%s) — جرّب %s (%s من %s)",
                candidate,
                http_status,
                candidates[index + 1],
                index + 2,
                len(candidates),
            )

    raise last_error or LLMError("فشل توليد البرومبت", status_code=502)