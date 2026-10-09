"""
محرك هندسة البرومبتات.

المسار من "وصف خام" إلى "برومبت مهيكل":

    وصف المستخدم
        ↓  TOOL_TEMPLATES  (لمن سيُكتب؟ ChatGPT/Claude/Midjourney/…)
        ↓  FRAMEWORKS      (بأي هيكل؟ CO-STAR/CRISPE/5C)
        ↓  SYSTEM_PROMPT   (تعليمات النموذج)
        ↓  OpenRouter      (النموذج يولّد الـ Markdown)
        ↓
    برومبت جاهز للنسخ

كل إطار له أقسام محددة، وكل أداة لها "تلميح نظام" يُدمج في تعليمات النموذج حتى
يكتب البرومبت بالشكل الذي تتوقعه تلك الأداة تحديدًا.
"""

import hashlib
import logging
import re
import time
from collections import OrderedDict

from app.config import settings
from app.services.llm_client import LLMError, chat_completion

logger = logging.getLogger("promptcraft.prompt_engine")


# ============================================================
# أ) أطر البرومبتات
# ============================================================
#
# أسماء الأقسام بالإنجليزية في مفتاح `key` (تُستخدم داخليًا)، وبالعربية في
# `name_ar` (تظهر للمستخدم). السبب: لوحة المفاتيح العربية تُبطئ كتابة حرفي
# يبحث عنه مطوّر، بينما الواجهة عربية بالكامل.

FRAMEWORKS: dict[str, dict] = {
    "co-star": {
        "name_ar": "CO-STAR",
        "description_ar": (
            "أشهر إطار هندسي: يفصل السياق عن الهدف والنبرة، فيمنع النموذج من "
            "تشتيت نفسه في تفاصيل جانبية. مناسب لأغلب مهام المحتوى: مقالات، "
            "تحليل، تسويق، محتوى، بريد إلكتروني."
        ),
        "sections": [
            {"key": "context", "name_ar": "السياق", "hint_ar": "الخلفية والمعطيات المتاحة"},
            {"key": "objective", "name_ar": "الهدف", "hint_ar": "المطلوب بدقة + معيار النجاح"},
            {"key": "style", "name_ar": "الأسلوب", "hint_ar": "الصياغة والبنية وطول المخرج"},
            {"key": "tone", "name_ar": "النبرة", "hint_ar": "رسمية / ودّية / تحفيزية"},
            {"key": "audience", "name_ar": "الجمهور", "hint_ar": "من سيقرأ ويستخدم المخرج"},
            {"key": "response", "name_ar": "صيغة الرد", "hint_ar": "شكل المخرجات المطلوبة"},
        ],
    },
    "crispe": {
        "name_ar": "CRISPE",
        "description_ar": (
            "إطار أدق في ضبط الدور والسعة وحدود الإبداع. ممتاز عندما تحتاج مخرجات "
            "ثابتة البنية (قوائم، جداول، تقارير) أو تريد التحكم الدقيق في عدد "
            "العناصر وطول كل عنصر."
        ),
        "sections": [
            {"key": "capacity", "name_ar": "السعة", "hint_ar": "المعرفة والخبرة المطلوبة"},
            {"key": "role", "name_ar": "الدور", "hint_ar": "من يمثّل النموذج بالتحديد"},
            {"key": "insight", "name_ar": "الرؤية", "hint_ar": "تحليل المعطيات واستخلاص الخلاصة"},
            {"key": "statement", "name_ar": "المطلوب", "hint_ar": "المهمة بصيغة أمر مباشرة"},
            {"key": "personality", "name_ar": "الشخصية", "hint_ar": "الصوت والأسلوب"},
            {"key": "experiment", "name_ar": "التجربة", "hint_ar": "قيود بديلة ومخرجات اختبار"},
        ],
    },
    "5c": {
        "name_ar": "5C",
        "description_ar": (
            "أقصر إطار وأسرعه: شخصية ودافع وقيد واستثناء ومعيار ثقة. مناسب للردود "
            "السريعة أو عندما يكون الوصف نفسه قصيرًا وتريد مخرجًا مباشرًا."
        ),
        "sections": [
            {"key": "character", "name_ar": "من يعمل", "hint_ar": "الشخصية والمهمة"},
            {"key": "cause", "name_ar": "الدافع", "hint_ar": "لماذا ولماذا الآن"},
            {"key": "constraint", "name_ar": "القيد", "hint_ar": "الحدود والقيود"},
            {"key": "contingency", "name_ar": "الاستثناء", "hint_ar": "ماذا يحدث عند غياب المعطى"},
            {"key": "calibration", "name_ar": "معيار الثقة", "hint_ar": "متى يصرّ ومتى يجيب"},
        ],
    },
}

DEFAULT_FRAMEWORK = "co-star"


# ============================================================
# ب) قوالب الأدوات
# ============================================================
#
# كل أداة لها نظامها الخاص. الأدوات النصية (ChatGPT/Claude/Gemini) تستقبل برومبتًا
# نصيًا عاديًا، أما Midjourney فتحتاج وصفًا بصريًا واحدًا متماسكًا لا عناوين
# أقسام، وأدوات الكود (Cursor) تحتاج سياق ملفات وتعليمات نطاق.

TOOL_TEMPLATES: dict[str, dict] = {
    "chatgpt": {
        "name_ar": "ChatGPT",
        "description_ar": "نماذج OpenAI المحادثة — رد نصي أو تحليلي منظّم.",
        "system_hint": (
            "البرومبت مخصص لـ ChatGPT. لا تضع وسوم XML أو كتل JSON، اكتب تعليمات "
            "بعناوين واضحة، واطلب الرد مباشرة بلا مقدمات."
        ),
    },
    "claude": {
        "name_ar": "Claude",
        "description_ar": "نماذج Anthropic — ممتازة للنصوص الطويلة والتحليل متعدد الخطوات.",
        "system_hint": (
            "البرومبت مخصص لـ Claude. استغل طول السياق: اطلب تحليلًا خطوة بخطوة ثم "
            "خلاصة في نهاية، وميّز بين الحقائق والافتراضات صراحةً."
        ),
    },
    "gemini": {
        "name_ar": "Gemini",
        "description_ar": "نماذج Google — قوية في الجداول والمقارنات وربط خدمات Google.",
        "system_hint": (
            "البرومبت مخصص لـ Gemini. إن طلب المستخدم مقارنة أو بيانات منظمة فانخرجه "
            "في جدول Markdown واضح، واذكر المصادر إن وُجدت."
        ),
    },
    "midjourney": {
        "name_ar": "Midjourney",
        "description_ar": "توليد الصور — يحتاج وصفًا بصريًا دقيقًا ومعاملات إعدادات في النهاية.",
        "system_hint": (
            "البرومبت مخصص لـ Midjourney. اكتب وصفًا بصريًا واحدًا متماسكًا (20 إلى 60 "
            "كلمة) يبدأ بالموضوع ثم تفاصيل المظهر والإضاءة ثم نوع العدسة. لا تضع "
            "عناوين أقسام ولا شرحًا ولا جملًا تمهيدية. أضف في النهاية --ar بنسبة "
            "الأبعاد المطلوبة، واستخدم --v 7 إن طلب المستخدم أحدث إصدار. لا تكتب "
            "عربية داخل الوصف البصري إلا إذا كان النص جزءًا من الصورة نفسها."
        ),
    },
    "cursor": {
        "name_ar": "Cursor",
        "description_ar": "محرّر الكود بالذكاء الاصطناعي — يحتاج سياقًا وتعليمات تحرير.",
        "system_hint": (
            "البرومبت مخصص لـ Cursor وأدوات الكود المشابهة. حدّد التقنية والملفات "
            "المعنية ونمط الكود المطلوب صراحةً، واطلب أن يشرح التغيير ولا يحذف "
            "شيئًا خارج النطاق المذكور."
        ),
    },
    "general": {
        "name_ar": "عام",
        "description_ar": "برومبت محايد يصلح لأي نموذج محادثة.",
        "system_hint": (
            "البرومبت محايد ولا يستهدف أداة بعينها. اجعله قابلًا للتنفيذ في أي "
            "نموذج محادثة."
        ),
    },
}

DEFAULT_TOOL = "general"


# ============================================================
# ذاكرة مؤقتة للنتائج
# ============================================================
#
# نفس المدخلات تعطي نفس البرومبت، فلا داعي لاستدعاء النموذج مرة ثانية. المفتاح
# هاش للمدخلات، والقيمة زوج (وقت الحفظ، النتيجة). الإذناط مُرضٍ من الأقدم
# (OrderedDict) حتى يبقى أداؤها ثابتًا مهما بلغ الحجم.

_prompt_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()


def _cache_key(raw_input: str, tool: str, framework: str, language: str) -> str:
    """هاش ثابت للمدخلات — لا نخزّن الوصف نفسه كمفتاح."""
    payload = f"{raw_input.strip()}|{tool}|{framework}|{language}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None:
    """يعيد النتيجة المخزّنة إن كانت صالحة، أو None."""
    if not settings.PROMPT_CACHE_ENABLED:
        return None

    entry = _prompt_cache.get(key)
    if entry is None:
        return None

    stored_at, value = entry
    if time.time() - stored_at > settings.PROMPT_CACHE_TTL:
        _prompt_cache.pop(key, None)
        return None

    _prompt_cache.move_to_end(key)
    return {**value, "cached": True}


def _cache_put(key: str, value: dict) -> None:
    """يخزّن النتيجة ويفرض الحد الأقصى للحجم."""
    if not settings.PROMPT_CACHE_ENABLED:
        return

    _prompt_cache[key] = (time.time(), value)
    _prompt_cache.move_to_end(key)

    limit = max(1, settings.PROMPT_CACHE_SIZE)
    while len(_prompt_cache) > limit:
        _prompt_cache.popitem(last=False)


def clear_prompt_cache() -> int:
    """يفرغ الذاكرة المؤقتة ويعيد عدد ما حُذف."""
    removed = len(_prompt_cache)
    _prompt_cache.clear()
    return removed


def framework_sections_text(framework: str) -> str:
    """يحوّل أقسام الإطار إلى نص إرشادي يُمرَّر في تعليمات النموذج."""
    spec = FRAMEWORKS.get(framework, FRAMEWORKS[DEFAULT_FRAMEWORK])
    lines = [f"الإطار المطلوب هو {spec['name_ar']}، وكل قسم بعنوان عربي واحد فقط:"]
    for i, section in enumerate(spec["sections"], start=1):
        lines.append(f"{i}. **{section['name_ar']}** — {section['hint_ar']}")
    return "\n".join(lines)


# ============================================================
# ج) تعليمات النظام
# ============================================================

SYSTEM_PROMPT = """\
أنت مهندس برومبتات. حوّل وصف المستخدم الخام إلى برومبت مهيكل جاهز للاستخدام فورًا.

قواعد ملزمة:
1. نظّم الوصف وفق الإطار المطلوب واملأ كل قسم بمحتوى واقعي مستنتج منه. لا تترك
   قسمًا فارغًا؛ إن نقص المعطى فاستنتج قيمة معقولة بدل أن تسأل المستخدم.
2. اجعل القابل للتنفيذ أولويتك: أرقام وحدود وتواريخ وأسماء بدل العبارات المبهمة.
3. أعد البرومبت وحده بصيغة Markdown — بلا مقدمة ولا شرح ولا تعليق على الوصف.
4. اكتب باللغة المطلوبة كما وردت في التعليمات (عربية أو إنجليزية).
"""

SYSTEM_PROMPT_EN = """\
You are a prompt engineer. Convert the user's raw description into a structured
prompt that is ready to use immediately.

Mandatory rules:
1. Restructure per the requested framework, filling every section with concrete
   inferred content. Never leave a section empty; infer a sensible value instead
   of asking a question.
2. Prefer the executable: real numbers, limits, dates and names over vague wording.
3. Return only the prompt as Markdown — no preamble, no commentary, no critique.
4. Write in the requested language (Arabic or English).
"""


def build_user_instructions(
    raw_input: str,
    tool: str = DEFAULT_TOOL,
    framework: str = DEFAULT_FRAMEWORK,
    language: str = "ar",
) -> str:
    """
    يبني نص التعليمات الذي يُرسل كرسالة مستخدم.

    هنا تُحقن ثلاث معلومات: ما طلبه المستخدم، ولمن سيُكتب البرومبت (الأداة)،
    وبأي هيكل (الإطار)، وبأي لغة.
    """
    tool_spec = TOOL_TEMPLATES.get(tool, TOOL_TEMPLATES[DEFAULT_TOOL])
    framework_spec = FRAMEWORKS.get(framework, FRAMEWORKS[DEFAULT_FRAMEWORK])

    language_line = (
        "اكتب البرومبت باللغة العربية الفصحى المبسّطة."
        if language == "ar"
        else "Write the prompt in clear professional English."
    )

    return (
        "وصف المستخدم الخام:\n"
        f"<<<\n{raw_input.strip()}\n>>>\n\n"
        f"الأداة المستهدفة: {tool_spec['name_ar']}\n"
        f"{tool_spec['system_hint']}\n\n"
        f"{framework_sections_text(framework)}\n\n"
        f"{language_line}\n\n"
        f"اكتب البرومبت الآن بصيغة Markdown فقط، بعنوان لكل قسم من أقسام إطار "
        f"{framework_spec['name_ar']} بالترتيب، وبدون أي كلام إضافي."
    )


# ============================================================
# د) توليد البرومبت
# ============================================================

# قيم تملأ وضع التجربة لكل قسم. المفتاح هو الاسم العربي للقسم.
_MOCK_AR: dict[str, str] = {
    "السياق": "الجمهور عربي، وخبرته السابقة بالموضوع محدودة، والمطلوب من المخرج أن "
              "يصلح لسند غير متخصص دون تسهيل يفسد المعنى.",
    "الهدف": "إنتاج مخرج واحد واضح يمكن تطبيقه مباشرة، مع معيار نجاح قابل للقياس.",
    "الأسلوب": "منظّم بعناوين، جمل قصيرة، بلا حشو ولا تكرار، مع مثال تطبيقي واحد.",
    "النبرة": "مهنية ودّية، بلا مبالغة ولا مصطلحات معقّدة بلا داعٍ.",
    "الجمهور": "قارئ عربي يفهم المجال دون خلفية تقنية، ويقرأ على الهاتف غالبًا.",
    "صيغة الرد": "رد نصي منظّم بعناوين، يبدأ بمخرج مباشر ثم تفاصيل مسنودة.",
    "السعة": "خبرة في المجال مع إمكانية التحقق من كل معلومة يُذكر مصدرها.",
    "الدور": "محرّر متخصص في تحويل المحتوى الخام إلى صيغ قابلة للتطبيق فورًا.",
    "الرؤية": "حلّل المعطيات المتاحة أولًا، ثم استخلص منها خلاصة عملية واحدة.",
    "المطلوب": "أنتج لي النص النهائي وفق البنية المطلوبة أعلاه، دون مقدمات.",
    "الشخصية": "دقيق ومباشر، ويشرح المصطلح عند أول استخدام له في النص.",
    "التجربة": "إن نقصت معلومة، اذكر الافتراض صراحةً وقدّم بديلين قابلين للتنفيذ.",
    "من يعمل": "خبير في المجال يقدّم إجابة عملية لا وصفة نظرية.",
    "الدافع": "الحاجة إلى مخرج جاهز بدل البحث في مصادر متفرقة.",
    "القيد": "الالتزام بما ورد في الوصف دون إضافة حقول أو محاور جديدة.",
    "الاستثناء": "إن غاب معطى، اذكر ما يفترضه الرد بوضوح قبل الإجابة.",
    "معيار الثقة": "صريح فيما هو مؤكد ومتردد فيما يحتاج تحققًا، مع ذكر سبب التردد.",
}

_MOCK_EN: dict[str, str] = {
    "السياق": "Arabic-speaking audience with limited prior knowledge of the topic.",
    "الهدف": "Produce one directly applicable output with a measurable success criterion.",
    "الأسلوب": "Structured with headings, short sentences, no filler, one worked example.",
    "النبرة": "Professional and friendly, free of hype.",
    "الجمهور": "An Arabic reader without a technical background, mostly on mobile.",
    "صيغة الرد": "An organized Markdown answer that opens with the output itself.",
    "السعة": "Domain expertise with verifiable sources for every factual claim.",
    "الدور": "An editor turning raw content into immediately applicable form.",
    "الرؤية": "Analyze the given inputs first, then extract one practical conclusion.",
    "المطلوب": "Produce the final text following the structure above, no preamble.",
    "الشخصية": "Precise and direct, defining terms on first use.",
    "التجربة": "If data is missing, state the assumption and offer two alternatives.",
    "من يعمل": "A domain expert giving a practical answer, not a lecture.",
    "الدافع": "Need a ready output instead of scattered research.",
    "القيد": "Stick to the given description; add no new fields.",
    "الاستثناء": "If data is missing, state what the answer assumes before answering.",
    "معيار الثقة": "Confident about facts, explicit about uncertainty and its cause.",
}


def _estimate_tokens(text: str) -> int:
    """
    تقدير تقريبي لعدد الـ tokens (نحو 4 حروف لكل token).

    تقدير يكفي للعرض في وضع التجربة. في الوضع الحقيقي نُبقيه أيضًا تقريبًا
    لأن استدعاء OpenRouter يُرجع usage لكن واجهتنا تعرض تقديرًا موحّدًا.
    """
    return max(1, round(len(text) / 4))


def _mock_prompt(raw_input: str, tool: str, framework: str, language: str) -> str:
    """
    برومبت قالبي لوضع التجربة (PROMPT_MOCK=true) — بلا أي اتصال خارجي.

    يحافظ على نفس بنية المخرج الحقيقي (Markdown بعناوين لكل قسم) حتى تبقى
    الواجهة والاختبارات متطابقة الشكل بين الوضعين.
    """
    tool_spec = TOOL_TEMPLATES.get(tool, TOOL_TEMPLATES[DEFAULT_TOOL])
    framework_spec = FRAMEWORKS.get(framework, FRAMEWORKS[DEFAULT_FRAMEWORK])
    subject = (raw_input or "").strip() or "موضوع عام"
    fillers = _MOCK_AR if language == "ar" else _MOCK_EN

    if language == "ar":
        banner = (
            f"> **وضع التجربة** — هذا برومبت نموذجي مبني على قالب "
            f"`{framework_spec['name_ar']}` لأداة {tool_spec['name_ar']}، وليس "
            f"مولّدًا من نموذج. فعّل `PROMPT_MOCK=false` في ملف `.env` للحصول على "
            f"برومبت حقيقي من OpenRouter."
        )
    else:
        banner = (
            f"> **Mock mode** — a template prompt for `{framework_spec['name_ar']}` "
            f"/ {tool_spec['name_ar']}, not model-generated. Set "
            f"`PROMPT_MOCK=false` in `.env` for real OpenRouter output."
        )

    parts = [banner, "", f"# {subject}", ""]
    for section in framework_spec["sections"]:
        parts.append(
            f"## {section['name_ar']}\n\n{fillers.get(section['name_ar'], 'اكتب هنا ما يخص هذا القسم.')}"
        )

    return "\n".join(parts)


def _strip_preamble(text: str) -> str:
    """يحذف العبارات التمهيدية الشائعة التي قد يضيفها النموذج رغم التعليمات."""
    patterns = [
        r"^\s*(?:إليك|فيما يلي|هذا|هذا هو)[^\n:]{0,40}:\s*\n+",
        r"^\s*(?:here is|here's)[^\n:]{0,60}:\s*\n+",
    ]
    result = text.strip()
    for pattern in patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    return result.strip() or text.strip()


async def generate_prompt(
    raw_input: str,
    tool: str = DEFAULT_TOOL,
    framework: str = DEFAULT_FRAMEWORK,
    language: str = "ar",
    mock: bool | None = None,
) -> dict:
    """
    يولّد برومبتًا مهيكلًا من وصف خام.

    :param raw_input: وصف المستخدم — أي نص، حتى لو كان مقطعًا واحدًا
    :param tool: مفتاح من `TOOL_TEMPLATES` (chatgpt/claude/gemini/midjourney/cursor/general)
    :param framework: مفتاح من `FRAMEWORKS` (co-star/crispe/5c)
    :param language: "ar" أو "en"
    :param mock: True يفرض الوضع الوهمي، False يفرض الاتصال، None يتبع الإعدادات
    :returns: dict فيه البرومبت وبيانات التتبع
    :raises LLMError: عند فراغ الوصف أو فشل الاستدعاء الحقيقي
    """
    raw_input = (raw_input or "").strip()
    if not raw_input:
        raise LLMError("الوصف فارغ — اكتب ما تريد تحويله إلى برومبت", status_code=400)

    if tool not in TOOL_TEMPLATES:
        logger.warning("أداة غير معروفة (%s) — استُخدمت '%s'", tool, DEFAULT_TOOL)
        tool = DEFAULT_TOOL

    if framework not in FRAMEWORKS:
        logger.warning("إطار غير معروف (%s) — استُخدم '%s'", framework, DEFAULT_FRAMEWORK)
        framework = DEFAULT_FRAMEWORK

    if language not in ("ar", "en"):
        language = "ar"

    use_mock = settings.PROMPT_MOCK if mock is None else mock

    # الذاكرة المؤقتة تخصّ النتائج الحقيقية فقط — وضع التجربة فوري أصلًا،
    # وتخزينه يفسد الاختبارات التي تتوقّع كاشًا باردًا.
    cache_key = _cache_key(raw_input, tool, framework, language)
    if not use_mock:
        hit = _cache_get(cache_key)
        if hit is not None:
            logger.info(
                "ضربة ذاكرة مؤقتة — الإطار %s، الأداة %s (بدون استدعاء النموذج)",
                framework, tool,
            )
            return hit

    if use_mock:
        logger.info(
            "توليد برومبت في وضع التجربة (mock) — إطار %s، أداة %s", framework, tool
        )
        prompt_text = _mock_prompt(raw_input, tool, framework, language)
    else:
        if not settings.openrouter_ready:
            raise LLMError(
                "مفتاح OpenRouter غير مضبوط. أضف OPENROUTER_API_KEY في ملف .env ثم "
                "أعد تشغيل الخادم. (تجده في: https://openrouter.ai/keys)",
                status_code=503,
            )

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT if language == "ar" else SYSTEM_PROMPT_EN,
            },
            {
                "role": "user",
                "content": build_user_instructions(raw_input, tool, framework, language),
            },
        ]

        logger.info(
            "استدعاء OpenRouter — النموذج %s، إطار %s، أداة %s",
            settings.OPENROUTER_MODEL, framework, tool,
        )
        raw_text = await chat_completion(
            messages=messages,
            model=settings.OPENROUTER_MODEL,
            temperature=0.7,
        )
        prompt_text = _strip_preamble(raw_text)

    result = {
        "prompt": prompt_text,
        "framework": framework,
        "framework_name": FRAMEWORKS[framework]["name_ar"],
        "tool": tool,
        "tool_name": TOOL_TEMPLATES[tool]["name_ar"],
        "language": language,
        "mock_used": use_mock,
        "tokens_used": _estimate_tokens(prompt_text),
        "model": "mock" if use_mock else settings.OPENROUTER_MODEL,
        "cached": False,
    }

    if not use_mock:
        _cache_put(cache_key, result)

    return result


# ============================================================
# هـ) اقتراح الإطار الأنسب
# ============================================================

# كلمات مفتاحية لكل إطار — مجموع التطابقات هو درجة الاختيار.
_FRAMEWORK_KEYWORDS: dict[str, list[str]] = {
    "crispe": [
        "قائمة", "جدول", "خطوات", "إجراءات", "دليل", "مراجعة", "مقارنة",
        "تحليل", "تقرير", "منهجية", "خطة", "سير عمل", "تنسيق", "سيناريو",
        "list", "steps", "table", "report", "analyze", "compare", "review",
        "workflow", "checklist",
    ],
    "5c": [
        "سؤال", "اشرح", "اختصر", "لخّص", "لخص", "بسيط", "سريع", "قصير",
        "تعريف", "صياغة", "جاوب", "رد", "نقطة",
        "explain", "summarize", "short", "brief", "quick", "define", "rewrite",
        "answer", "tldr",
    ],
}

# كلمات تدل على CO-STAR: كتابة محتوى وتسويق وجمهور
_CO_STAR_KEYWORDS = [
    "مقال", "كتابة", "اكتب", "تسويق", "حملة", "محتوى", "بوست", "منشور",
    "بريد إلكتروني", "نشرة", "فيديو", "هوك", "جمهور", "نبرة", "مقنع", "إقناع",
    "وصف منتج", "صفحة هبوط", "كلام إعلاني", "إعلان", "منتج", "علامة تجارية",
    "article", "blog", "write", "marketing", "campaign", "content", "post",
    "email", "newsletter", "script", "audience", "tone", "copy", "landing",
    "persuasive",
]


def suggest_framework(raw_input: str) -> dict:
    """
    يقترح أنسب إطار بناءً على كلمات مفتاحية في النص.

    :returns: {"framework", "name_ar", "reason_ar", "confidence", "alternatives"}
    """
    text = (raw_input or "").strip().lower()

    if not text:
        return {
            "framework": DEFAULT_FRAMEWORK,
            "name_ar": FRAMEWORKS[DEFAULT_FRAMEWORK]["name_ar"],
            "reason_ar": "لم يُرسل نص — استُخدم الإطار الافتراضي",
            "confidence": 0.0,
            "alternatives": [],
        }

    hits: dict[str, list[str]] = {
        fw: [kw for kw in keywords if kw in text]
        for fw, keywords in _FRAMEWORK_KEYWORDS.items()
    }
    hits["co-star"] = [kw for kw in _CO_STAR_KEYWORDS if kw in text]

    # CO-STAR هو الافتراضي، فنمنحه حدًا أدنى من الدرجة عند غياب التطابق
    scored = {
        fw: len(words) + (0.5 if fw == "co-star" else 0.0)
        for fw, words in hits.items()
    }
    best = max(scored, key=lambda key: scored[key])

    if scored[best] <= 0.5:
        return {
            "framework": DEFAULT_FRAMEWORK,
            "name_ar": FRAMEWORKS[DEFAULT_FRAMEWORK]["name_ar"],
            "reason_ar": "النص عام ولا يحتوي كلمات دالة واضحة — اخترنا الإطار الأكثر توازنًا",
            "confidence": 0.2,
            "alternatives": ["crispe", "5c"],
        }

    matched = hits[best]
    alternatives = [fw for fw in scored if fw != best and scored[fw] > 0.5]
    alternatives.sort(key=lambda key: scored[key], reverse=True)

    if best == "co-star":
        reason = f"النص يركّز على المحتوى والتسويق والجمهور — ظهرت: {', '.join(matched[:3])}"
    elif best == "crispe":
        reason = f"النص يتطلب مخرجًا منظمًا (قائمة/جدول/تحليل) — ظهرت: {', '.join(matched[:3])}"
    else:
        reason = f"النص مباشر ويطلب ردًا بسيطًا — ظهرت: {', '.join(matched[:3])}"

    return {
        "framework": best,
        "name_ar": FRAMEWORKS[best]["name_ar"],
        "reason_ar": reason,
        "confidence": min(1.0, round(scored[best] / 3.0, 2)),
        "alternatives": alternatives,
    }


# ============================================================
# و) قواميس للواجهة
# ============================================================


def list_frameworks() -> list[dict]:
    """كل الأطر بصيغة صالحة للواجهة."""
    return [
        {
            "id": key,
            "name_ar": spec["name_ar"],
            "description_ar": spec["description_ar"],
            "sections": [
                {"key": s["key"], "name_ar": s["name_ar"], "hint_ar": s["hint_ar"]}
                for s in spec["sections"]
            ],
        }
        for key, spec in FRAMEWORKS.items()
    ]


def list_tools() -> list[dict]:
    """كل الأدوات بصيغة صالحة للواجهة."""
    return [
        {
            "id": key,
            "name_ar": spec["name_ar"],
            "description_ar": spec["description_ar"],
        }
        for key, spec in TOOL_TEMPLATES.items()
    ]