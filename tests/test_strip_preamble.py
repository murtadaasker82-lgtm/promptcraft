"""اختبارات تنظيف رد النموذج من التمهيد وأسوار الكود."""

from app.services.prompt_engine import _strip_code_fence, _strip_preamble


# ============================================================
# أ) أسوار ```markdown
# ============================================================


def test_strips_closed_markdown_fence():
    text = "```markdown\n## السياق\nوصف\n```"
    assert _strip_code_fence(text) == "## السياق\nوصف"


def test_strips_plain_fence_without_language():
    text = "```\n## السياق\nوصف\n```"
    assert _strip_code_fence(text) == "## السياق\nوصف"


def test_strips_md_alias():
    text = "```md\n## الهدف\nهدف\n```"
    assert _strip_code_fence(text) == "## الهدف\nهدف"


def test_strips_unclosed_fence_truncated_by_max_tokens():
    """سور مفتوح فقط — يحدث حين يقطع حد الرموز الردّ."""
    text = "```markdown\n## السياق\nوصف"
    assert _strip_code_fence(text) == "## السياق\nوصف"


def test_leaves_plain_text_untouched():
    assert _strip_code_fence("## السياق\nوصف") == "## السياق\nوصف"


# ============================================================
# ب) عبارات التمهيد
# ============================================================


def test_removes_arabic_preamble_with_long_tail():
    """
    الحالة التي كشفها الفحص الحي: تمهيد طويل يتجاوز قصّating السابق.
    """
    text = (
        "إليك ثلاث فوائد رئيسية للذكاء الاصطناعي في التعليم:\n\n"
        "1. **التعليم المخصص:** تكييف المحتوى.\n"
        "2. **التقييم الفوري:** تصحيح آلي.\n"
    )
    assert _strip_preamble(text).startswith("1. **التعليم المخصص:**")


def test_removes_english_preamble():
    text = "Certainly! Here is the prompt:\n\n## Context\nSome context"
    assert _strip_preamble(text) == "## Context\nSome context"


def test_removes_sure_and_of_course():
    assert _strip_preamble("Sure — here it is:\n\n## Goal\nG").startswith("## Goal")
    assert _strip_preamble("Of course.\n\n## Goal\nG").startswith("## Goal")


def test_removes_multi_line_preamble():
    text = "بالطبع! يسعدني مساعدتك.\nإليك البرومبت:\n\n## الهدف\nH"
    assert _strip_preamble(text) == "## الهدف\nH"


def test_removes_preamble_wrapped_in_blockquote():
    text = "> إليك البرومبت:\n\n## الهدف\nH"
    assert _strip_preamble(text) == "## الهدف\nH"


def test_combines_fence_and_preamble():
    text = "```markdown\nإليك البرومبت:\n## الهدف\nH\n```"
    assert _strip_preamble(text) == "## الهدف\nH"


# ============================================================
# ج) حماية المحتوى
# ============================================================


def test_keeps_preamble_word_inside_body():
    """
    كلمة التمهيد في وسط البرومبت محتوى لا تمهيد — يجب ألا تُحذف.
    """
    text = "## السياق\nهذا المشروع يخدم الطلاب.\n\n## الهدف\nH"
    assert _strip_preamble(text) == text


def test_keeps_clean_prompt_unchanged():
    text = "## السياق\nالجمهور طلاب.\n\n## الهدف\nاكتب مقالًا."
    assert _strip_preamble(text) == text


def test_returns_original_when_everything_is_preamble():
    """لو لم يبقَ إلا تمهيد نُعيد الأصل حذرًا بدل ردّ فارغ."""
    text = "إليك البرومبت"
    assert _strip_preamble(text) == text


def test_does_not_touch_similar_headings():
    """عناوين تبدأ بحروف مشابهة يجب أن تبقى."""
    text = "## هذا هو الهدف\nوصف"
    assert _strip_preamble(text) == text


# ============================================================
# د) غلاف العنوان في السطر الأول
# ============================================================


def test_strips_title_marker_from_first_line_only():
    """الحالة المذكورة: الغلاف يُزال و`##` التالية لا تُمس."""
    text = "# البرومبت\n## السياق\nوصف"
    assert _strip_preamble(text) == "البرومبت\n## السياق\nوصف"


def test_keeps_all_inner_headings_intact():
    """كل `##` بعد السطر الأول تبقى كما هي بالترتيب."""
    text = "# الغلاف\n## السياق\n## الهدف\n## الأسلوب"
    result = _strip_preamble(text)
    assert result.startswith("الغلاف")
    assert result.count("##") == 3
    assert "## السياق\n## الهدف\n## الأسلوب" in result


def test_keeps_h2_when_it_is_the_first_line():
    """
    `##` علامات أقسام يطلبها النموذج — لا تُمس مهما كانت في السطر الأول.
    """
    assert _strip_preamble("## السياق\nوصف") == "## السياق\nوصف"


def test_strips_title_after_preamble_line_removed():
    """بعد حذف التمهيد يصبح العنوان هو السطر الأول فيُزال."""
    text = "إليك البرومبت:\n\n# الغلاف\n## السياق"
    assert _strip_preamble(text) == "الغلاف\n## السياق"


def test_preserves_hash_inside_line_content():
    """علامة `#` داخل نص السطر ليست عنوانًا."""
    text = "اكتب عن #الذكاء الاصطناعي في Schools"
    assert _strip_preamble(text) == text


def test_ignores_hash_without_space():
    """`#######` سبعة هاشات ليس عنوانًا، و`#بدون` ليست عنوانًا."""
    assert _strip_preamble("#لا مسافة\n## سياق") == "#لا مسافة\n## سياق"


def test_first_line_not_a_heading_is_untouched():
    """نص عادي في السطر الأول — لا تغيير إطلاقًا."""
    text = "1. تخصيص مسار التعلم.\n2. أتمتة المهام."
    assert _strip_preamble(text) == text