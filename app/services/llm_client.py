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

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


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
            timeout=settings.LLM_TIMEOUT_SECONDS,
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


def _map_status_error(exc: APIStatusError) -> LLMError:
    """يحوّل خطأ HTTP من الخدمة إلى رسالة عربية مفهومة + رمز مناسب."""
    status = exc.status_code

    if status in (401, 403):
        return LLMError(
            "مفتاح OpenRouter غير صالح أو منتهي. افتح https://openrouter.ai/keys "
            "وأنشئ مفتاحًا جديدًا ثم حدّث OPENROUTER_API_KEY في ملف .env.",
            status_code=401,
        )

    if status == 402:
        return LLMError(
            "رصيد حسابك في OpenRouter غير كافٍ لإتمام الطلب. "
            "أضف رصيدًا أو استخدم نموذجًا مجانيًا ( ending بـ :free ).",
            status_code=402,
        )

    if status == 429:
        return LLMError(
            "تم تجاوز حد الاستخدام مؤقتًا (429). غالبًا لأن النموذج مزدحم أو "
            "أن مفتاحك بلا رصيد. انتظر دقيقة ثم أعد المحاولة، أو غيّر النموذج.",
            status_code=429,
        )

    if status == 404:
        return LLMError(
            f"النموذج المطلوب غير موجود على OpenRouter: {settings.OPENROUTER_MODEL}. "
            "تحقق من الاسم في https://openrouter.ai/models",
            status_code=404,
        )

    if status >= 500:
        return LLMError(
            "خدمة OpenRouter تواجه خطأ داخليًا مؤقتًا — أعد المحاولة بعد قليل.",
            status_code=502,
        )

    return LLMError(
        f"رفضت OpenRouter الطلب (رمز {status}). راجع نص الطلب أو مفتاحك ثم أعد المحاولة.",
        status_code=502,
    )


async def chat_completion(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_attempts: int = 3,
) -> str:
    """
    يستدعي نموذج محادثة ويعيد نص الإجابة فقط.

    :param messages: قائمة رسائل بصيغة OpenAI: [{"role": ..., "content": ...}]
    :param model: اسم النموذج؛ الافتراضي من الإعدادات
    :param temperature: 0 = حتمي، 1 = إبداعي
    :param max_tokens: حد أعلى لطول الإجابة (اختياري)
    :param max_attempts: عدد المحاولات في أخطاء الشبكة أو 429/5xx
    :returns: نص الإجابة بعد تنظيفه
    :raises LLMError: عند غياب المفتاح أو فشل كل المحاولات
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
    client = get_llm_client()

    last_error: LLMError | None = None

    for attempt in range(1, max_attempts + 1):
        try:
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
            logger.info(
                "اكتمل الاستدعاء (model=%s، محاولات=%s، طول=%s حرف)",
                model,
                attempt,
                len(text),
            )
            return text

        except AuthenticationError as exc:
            # لا فائدة من إعادة المحاولة — المفتاح خطأ
            raise _map_status_error(exc) from exc

        except NotFoundError as exc:
            raise _map_status_error(exc) from exc

        except RateLimitError as exc:
            last_error = _map_status_error(exc)
            if attempt == max_attempts:
                raise last_error from exc
            wait = 2**attempt + random.random()
            logger.warning("حد معدل من OpenRouter — إعادة المحاولة %s/%s بعد %.1fs",
                           attempt, max_attempts, wait)
            await asyncio.sleep(wait)

        except InternalServerError as exc:
            last_error = _map_status_error(exc)
            if attempt == max_attempts:
                raise last_error from exc
            wait = 1.5 * attempt
            logger.warning("خطأ 5xx من OpenRouter — إعادة المحاولة %s/%s",
                           attempt, max_attempts)
            await asyncio.sleep(wait)

        except APIStatusError as exc:
            mapped = _map_status_error(exc)
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
            logger.warning("فشل الاتصال بـ OpenRouter — إعادة المحاولة %s/%s",
                           attempt, max_attempts)
            await asyncio.sleep(1.5 * attempt)

        except APIError as exc:
            raise LLMError(
                f"خطأ من عميل OpenRouter: {exc}",
                status_code=502,
            ) from exc

    raise last_error or LLMError("فشل توليد البرومبت", status_code=502)