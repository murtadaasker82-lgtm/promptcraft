/* ==========================================================
   PromptCraft — واجهة مكتبة البرومبتات
   تُحمَّل قبل Alpine.js (بدون defer) ليسجّل alpine:init
   ========================================================== */

const LIB_CFG = window.__PC_CONFIG__ || {};

/* ==========================================================
   أدوات مشتركة (نسخ من app.js)
   ========================================================== */

/** يحوّل استجابة fetch غير.OK إلى رسالة عربية */
async function libReadError(response) {
    let payload = null;
    try {
        payload = await response.json();
    } catch (_) {
        payload = null;
    }

    const detail = payload?.detail;
    if (Array.isArray(detail)) {
        return detail.map((d) => d?.msg || '').filter(Boolean).join(' · ') || 'طلب غير صالح';
    }
    if (typeof detail === 'string' && detail) return detail;

    const byStatus = {
        401: 'انتهت الجلسة — سجّل الدخول من جديد',
        404: 'البرومبت غير موجود',
        422: 'طلب غير صالح',
        500: 'خطأ في الخادم',
        502: 'فشل الاتصال بالخدمة',
        503: 'الخدمة غير متاحة الآن',
    };
    return byStatus[response.status] || `خطأ في الخادم (${response.status})`;
}

async function libFetch(url) {
    const response = await fetch(url, { credentials: 'same-origin' });

    if (response.status === 401) {
        window.location.href = '/login';
        throw new Error('انتهت الجلسة');
    }
    if (!response.ok) {
        throw new Error(await libReadError(response));
    }
    return response.json();
}

/** ينسخ نصًا إلى الحافظة مع بديل للمتصفحات القديمة */
async function libCopy(text) {
    if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return;
    }
    const helper = document.createElement('textarea');
    helper.value = text;
    helper.setAttribute('readonly', '');
    helper.style.position = 'fixed';
    helper.style.top = '-1000px';
    helper.style.opacity = '0';
    document.body.appendChild(helper);
    helper.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(helper);
    if (!ok) throw new Error('execCommand copy failed');
}

/** تنسيق تاريخ ISO → نص عربي مقروء (بلا اعتماد على Intl.RelativeTimeFormat) */
function libFormatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleDateString('ar-EG', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

/* ==========================================================
   مكوّن المكتبة
   ========================================================== */

function libraryApp() {
    return {
        // ---- من إعدادات الصفحة ----
        auth_user: LIB_CFG.user || { username: '—' },
        model: LIB_CFG.llm_model || '—',
        prefill: LIB_CFG.prefill || null,

        // ---- القوائم (نفس معرّفات المحرك) ----
        tools: [
            { id: 'chatgpt', name_ar: 'ChatGPT' },
            { id: 'claude', name_ar: 'Claude' },
            { id: 'gemini', name_ar: 'Gemini' },
            { id: 'midjourney', name_ar: 'Midjourney' },
            { id: 'cursor', name_ar: 'Cursor' },
            { id: 'general', name_ar: 'عام' },
            { id: 'enhance', name_ar: 'تحسين' },
        ],
        frameworks: [
            { id: 'co-star', name_ar: 'CO-STAR' },
            { id: 'crispe', name_ar: 'CRISPE' },
            { id: '5c', name_ar: '5C' },
        ],

        // ---- الفلاتر ----
        search: '',
        toolFilter: '',
        frameworkFilter: '',
        sort: 'newest',
        limit: 20,
        offset: 0,

        // ---- النتائج ----
        items: [],
        total: 0,
        stats: { total: 0, by_tool: {}, by_framework: {}, last_7_days: 0 },

        isLoading: false,
        isLoadingStats: false,
        error: '',
        selected: null,
        copiedId: null,
        deleteArmed: null,
        _searchTimer: null,

        /* ---------------- خصائص مشتقة ---------------- */

        get hasFilters() {
            return Boolean(this.search.trim() || this.toolFilter || this.frameworkFilter);
        },

        get page() {
            return Math.floor(this.offset / this.limit) + 1;
        },

        get pageCount() {
            return Math.max(1, Math.ceil(this.total / this.limit));
        },

        get hasPrev() {
            return this.offset > 0;
        },

        get hasNext() {
            return this.offset + this.limit < this.total;
        },

        get rangeLabel() {
            if (!this.total) return 'لا نتائج';
            const from = this.offset + 1;
            const to = Math.min(this.offset + this.limit, this.total);
            return `${from}–${to} من ${this.total}`;
        },

        /** أكثر أداة استخدامًا — أقصى قيمة في موزّع by_tool */
        get topTool() {
            return libTop(this.stats.by_tool);
        },

        /** أكثر إطار استخدامًا */
        get topFramework() {
            return libTop(this.stats.by_framework);
        },

        /* ---------------- التحميل ---------------- */

        async loadStats() {
            this.isLoadingStats = true;
            try {
                this.stats = await libFetch('/api/prompts/stats');
            } catch (err) {
                this.error = err.message || 'تعذّر تحميل الإحصاءات';
                this.$store.toast.error(this.error);
            } finally {
                this.isLoadingStats = false;
            }
        },

        async loadPrompts() {
            this.isLoading = true;
            this.error = '';
            try {
                const params = new URLSearchParams({
                    limit: String(this.limit),
                    offset: String(this.offset),
                    sort: this.sort,
                });
                if (this.search.trim()) params.set('search', this.search.trim());
                if (this.toolFilter) params.set('tool', this.toolFilter);
                if (this.frameworkFilter) params.set('framework', this.frameworkFilter);

                const data = await libFetch(`/api/prompts?${params.toString()}`);
                this.items = data.items || [];
                this.total = data.total || 0;
            } catch (err) {
                this.error = err.message || 'تعذّر تحميل السجل';
                this.items = [];
                this.total = 0;
                this.$store.toast.error(this.error);
            } finally {
                this.isLoading = false;
            }
        },

        /* ---------------- الفلاتر ---------------- */

        /** يصفّر الصفحة: أي تغيير في الفلتر يعيدنا لأول صفحة وإلا قدFormats عشوائية */
        applyFilters() {
            this.offset = 0;
            this.loadPrompts();
        },

        /** بحث مؤجّل 300ms حتى لا نضرب الخادم مع كل حرف */
        onSearchInput() {
            if (this._searchTimer) clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(() => this.applyFilters(), 300);
        },

        clearFilters() {
            this.search = '';
            this.toolFilter = '';
            this.frameworkFilter = '';
            this.applyFilters();
        },

        /* ---------------- الترقيم ---------------- */

        nextPage() {
            if (!this.hasNext) return;
            this.offset += this.limit;
            this.loadPrompts();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        prevPage() {
            if (!this.hasPrev) return;
            this.offset = Math.max(0, this.offset - this.limit);
            this.loadPrompts();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        /* ---------------- عنصر واحد ---------------- */

        openPrompt(item) {
            this.selected = item;
            this.deleteArmed = null;
        },

        closePrompt() {
            this.selected = null;
            this.deleteArmed = null;
        },

        /* ---------------- الإجراءات ---------------- */

        async copyPrompt(item) {
            try {
                await libCopy(item.generated_prompt);
                this.copiedId = item.id;
                this.$store.toast.ok('تم نسخ البرومبت');
                setTimeout(() => {
                    this.copiedId = null;
                }, 2000);
            } catch (_) {
                this.$store.toast.error('تعذّر النسخ — افتح البرومبت وانسخه يدويًا');
            }
        },

        /**
         * يؤكّد قبل الحذف: ضغطة واحدة تسلّح، والثانية تنفّذ.
         * حذف غير قابل للتراجع — خطوة التأكيد جزء من التصميم لا تحسين.
         */
        async deletePrompt(item) {
            if (this.deleteArmed !== item.id) {
                this.deleteArmed = item.id;
                setTimeout(() => {
                    if (this.deleteArmed === item.id) this.deleteArmed = null;
                }, 4000);
                return;
            }

            this.deleteArmed = null;

            try {
                await libFetch(`/api/prompts/${item.id}`, { method: 'DELETE' });
                this.$store.toast.ok('تم حذف البرومبت');

                if (this.selected?.id === item.id) this.selected = null;
                await Promise.all([this.loadPrompts(), this.loadStats()]);
            } catch (err) {
                this.$store.toast.error(err.message || 'تعذّر الحذف');
            }
        },

        /**
         * ينقل المستخدم إلى /app معبّئًا مربع الوصف.
         *
         * نمرّر `raw_input` لا `generated_prompt` — مربع /app يستقبل *الوصف*
         * ويولّد منه برومبتًا جديدًا، ولو وضعنا فيه البرومبت الجاهز لولّد
         * فوقه برومبتًا ثانٍ. نخزّن البرومبت الجاهز أيضًا ليمكن لصقه يدويًا.
         */
        usePrompt(item) {
            try {
                sessionStorage.setItem('pc:prefill', JSON.stringify({
                    raw: item.raw_input,
                    prompt: item.generated_prompt,
                    tool: item.tool,
                    framework: item.framework,
                }));
            } catch (_) {
                // التخزين قد يكون محظورًا — نكمل بلا تعبئة
            }
            window.location.href = '/app';
        },

        logout() {
            return pcLogout();
        },

        /* ---------------- الإقلاع ---------------- */

        init() {
            this.loadStats();
            this.loadPrompts();

            // إغلاق الـ modal بمفتاح Escape
            window.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.selected) this.closePrompt();
            });
        },
    };
}

/** يُعيد [المفتاح, العدد] لأعلى قيمة في موزّع إحصاءات */
function libTop(map) {
    const entries = Object.entries(map || {});
    if (!entries.length) return null;
    return entries.reduce((best, cur) => (cur[1] > best[1] ? cur : best));
}

/* ==========================================================
   قائمة التنبيهات — نفس مخزن Alpine المستخدم في app.html
   ========================================================== */

function libToastStack() {
    return {
        get toasts() {
            return this.$store.toast.items;
        },
        dismiss(id) {
            this.$store.toast.dismiss(id);
        },
    };
}

/* ==========================================================
   تسجيل المكونات
   ========================================================== */

document.addEventListener('alpine:init', () => {
    if (!window.Alpine.store('toast')) {
        window.Alpine.store('toast', {
            items: [],
            _seq: 0,

            push(text, kind = 'ok', ttl = 4500) {
                const id = ++this._seq;
                this.items.push({ id, text, kind });
                setTimeout(() => this.dismiss(id), ttl);
            },

            dismiss(id) {
                this.items = this.items.filter((t) => t.id !== id);
            },

            ok(text) {
                this.push(text, 'ok');
            },

            error(text) {
                this.push(text, 'error', 7000);
            },
        });
    }

    window.Alpine.data('libraryApp', libraryApp);
    window.Alpine.data('libToastStack', libToastStack);
});

window.PC_LIB_FORMAT_DATE = libFormatDate;