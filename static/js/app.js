/* ==========================================================
   PromptCraft — منطق Alpine.js + التعامل مع الـ API
   يُحمَّل قبل Alpine.js (بدون defer) ليسجّل alpine:init
   ========================================================== */

/* ---------------- إعدادات الصفحة (من Jinja2) ---------------- */

const CFG = window.__PC_CONFIG__ || {};

/* نسخة محلية من محرك البرومبتات — تُستخدم كاحتياطي فقط إذا فشل تحميل
   /api/prompt/frameworks، حتى تبقى القوائم قابلة للاستخدام دائمًا.
   المصدر الحقيقي هو المحرك في app/services/prompt_engine.py. */
const TOOLS_FALLBACK = [
    { id: 'chatgpt', name_ar: 'ChatGPT', description_ar: 'نماذج OpenAI المحادثة — رد نصي أو تحليلي منظّم.' },
    { id: 'claude', name_ar: 'Claude', description_ar: 'نماذج Anthropic — ممتازة للنصوص الطويلة والتحليل متعدد الخطوات.' },
    { id: 'gemini', name_ar: 'Gemini', description_ar: 'نماذج Google — قوية في الجداول والمقارنات وربط خدمات Google.' },
    { id: 'midjourney', name_ar: 'Midjourney', description_ar: 'توليد الصور — يحتاج وصفًا بصريًا دقيقًا ومعاملات إعدادات في النهاية.' },
    { id: 'cursor', name_ar: 'Cursor', description_ar: 'محرّر الكود بالذكاء الاصطناعي — يحتاج سياقًا وتعليمات تحرير.' },
    { id: 'general', name_ar: 'عام', description_ar: 'برومبت محايد يصلح لأي نموذج محادثة.' },
];

const FRAMEWORKS_FALLBACK = [
    {
        id: 'co-star',
        name_ar: 'CO-STAR',
        description_ar: 'سياق، هدف، أسلوب، نبرة، جمهور، صيغة — الأشمل وأنسب لمهام المحتوى والتسويق.',
    },
    {
        id: 'crispe',
        name_ar: 'CRISPE',
        description_ar: 'سعة، دور، رؤية، مطلوب، شخصية، تجربة — أدق في ضبط الدور والحدود ومخرجات ثابتة البنية.',
    },
    {
        id: '5c',
        name_ar: '5C',
        description_ar: 'شخصية، دافع، قيد، استثناء، معيار ثقة — الأقصر والأنسب للردود المباشرة.',
    },
];

/* كائن عام متاح لكل قوالب Alpine في الصفحة */
window.PC = {
    user: CFG.user || { username: '—' },
    maxUploadMb: CFG.max_upload_mb || 25,
    allowedExtensions: CFG.allowed_extensions || [],
    transcribeReady: CFG.transcribe_ready !== false,
    promptReady: CFG.prompt_ready !== false,
    promptMock: Boolean(CFG.prompt_mock),
    model: CFG.openrouter_model || '—',
    tools: TOOLS_FALLBACK,
    frameworks: FRAMEWORKS_FALLBACK,
};

/* ---------------- أدوات مشتركة ---------------- */

/** يحوّل استجابة fetch غير.OK إلى رسالة عربية */
async function readError(response) {
    let payload = null;
    try {
        payload = await response.json();
    } catch (_) {
        payload = null;
    }

    const detail = payload?.detail;

    if (Array.isArray(detail)) {
        // أخطاء تحقق Pydantic
        return detail.map((d) => d?.msg || '').filter(Boolean).join(' · ') || 'طلب غير صالح';
    }
    if (typeof detail === 'string' && detail) return detail;

    const byStatus = {
        400: 'طلب غير صالح',
        401: 'انتهت الجلسة — سجّل الدخول من جديد',
        403: 'لا تملك صلاحية لهذا الإجراء',
        404: 'المسار غير موجود',
        413: 'الملف كبير جدًا (الحد 25 ميجابايت)',
        415: 'نوع الملف غير مدعوم',
        429: 'النموذج مزدحم — انتظر قليلًا ثم أعد المحاولة',
        500: 'خطأ في الخادم',
        502: 'فشل الاتصال بخدمة OpenRouter',
        503: 'مفتاح OpenRouter غير مضبوط',
    };

    return byStatus[response.status] || `خطأ في الخادم (${response.status})`;
}

/** طلب عام: يرمي Error برسالة عربية جاهزة للعرض */
async function apiFetch(url, options = {}) {
    const isFormData = options.body instanceof FormData;

    const response = await fetch(url, {
        credentials: 'same-origin',
        ...options,
        headers: {
            ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
            ...(options.headers || {}),
        },
    });

    if (response.status === 401 && !url.includes('/api/auth/login')) {
        window.location.href = '/login';
        throw new Error('انتهت الجلسة');
    }

    if (!response.ok) {
        throw new Error(await readError(response));
    }

    return response.status === 204 ? null : response.json();
}

/** نسخ نص إلى الحافظة مع بديل للمتصفحات التي لا تدعم الحافظة الحديثة */
async function copyToClipboard(text) {
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

/** تنسيق الثواني → mm:ss */
function formatTime(totalSeconds) {
    const s = Math.max(0, Math.floor(totalSeconds || 0));
    const minutes = String(Math.floor(s / 60)).padStart(2, '0');
    const seconds = String(s % 60).padStart(2, '0');
    return `${minutes}:${seconds}`;
}

/** تنسيق البايت → ك.ب / م.ب */
function formatSize(bytes) {
    if (!bytes) return '0 ب';
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} ك.ب`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} م.ب`;
}

/* ==========================================================
   صفحة تسجيل الدخول
   ========================================================== */

function loginForm() {
    return {
        username: '',
        loading: false,
        error: '',

        // أي حرف خارج (حروف عربية/إنجليزية/مسافة) يمنع الإرسال ويظهر التنبيه.
        // بلا راية `g` حتى لا يتأثر lastIndex بين الاستدعاءات.
        INVALID_CHARS: /[^A-Za-z؀-ي ]/,

        get displayName() {
            return this.username.trim();
        },

        get hasInvalidChars() {
            return this.INVALID_CHARS.test(this.username);
        },

        prefillDisplayName() {
            this.error = '';
        },

        clearError() {
            this.error = '';
        },

        async submit() {
            this.error = '';

            const name = this.username.trim();
            if (!name) {
                this.error = 'اكتب اسم المستخدم أولًا';
                return;
            }
            if (this.hasInvalidChars) {
                this.error = 'الاسم يجب أن يحتوي على حروف فقط (عربية أو إنجليزية)';
                return;
            }
            if (name.length < 2) {
                this.error = 'اسم المستخدم قصير جدًا — حرفان على الأقل';
                return;
            }

            this.loading = true;
            try {
                await apiFetch('/api/auth/login', {
                    method: 'POST',
                    body: JSON.stringify({ username: name }),
                });
                window.location.href = '/app';
            } catch (err) {
                this.error = err.message || 'تعذّر تسجيل الدخول';
            } finally {
                this.loading = false;
            }
        },
    };
}

/* ==========================================================
   واجهة الإنشاء (Composer)
   ========================================================== */

function composer() {
    return {
        // ---- من إعدادات الصفحة ----
        auth_user: window.PC.user,
        maxUploadMb: window.PC.maxUploadMb,
        allowedExtensions: window.PC.allowedExtensions,
        transcribeReady: window.PC.transcribeReady,
        promptReady: window.PC.promptReady,
        promptMock: window.PC.promptMock,
        model: window.PC.model,

        // ---- القوائم (تُحدَّث من /api/prompt/frameworks عند الإقلاع) ----
        tools: window.PC.tools,
        frameworks: window.PC.frameworks,

        // ---- حالة النموذج ----
        inputText: '',
        selectedTool: 'general',
        selectedFramework: 'co-star',
        selectedLanguage: 'ar',
        autoFramework: false,
        suggestNotice: '',

        // ---- حالة التشغيل ----
        isLoading: false,
        isEnhancing: false,
        result: null,
        error: '',
        copied: false,

        // ---- الصوت ----
        audioFile: null,
        audioError: '',
        uploadStatus: '',
        uploading: false,
        dragActive: false,
        transcribeMock: false,

        // ---- التسجيل ----
        isRecording: false,
        recSeconds: 0,
        mediaRecorderSupported:
            typeof window.MediaRecorder !== 'undefined' &&
            !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
        _recorder: null,
        _chunks: [],
        _stream: null,
        _timer: null,

        /* ---------------- خصائص مشتقة ---------------- */

        get currentTool() {
            return this.tools.find((t) => t.id === this.selectedTool) || null;
        },

        get currentToolHint() {
            const tool = this.currentTool;
            return tool ? tool.description_ar : '';
        },

        get currentFramework() {
            return this.frameworks.find((f) => f.id === this.selectedFramework) || null;
        },

        get currentFrameworkHint() {
            const fw = this.currentFramework;
            return fw ? fw.description_ar : '';
        },

        get trimmedInput() {
            return this.inputText.trim();
        },

        get canGenerate() {
            return this.trimmedInput.length >= 3 && !this.isLoading;
        },

        get metaChips() {
            if (!this.result) return [];
            const r = this.result;
            return [
                { label: 'الإطار', value: r.framework_name || r.framework || '—' },
                { label: 'الأداة', value: r.tool_name || r.tool || '—' },
                { label: 'الرمز', value: `${r.tokens_used ?? '—'} رمز` },
                { label: 'النموذج', value: r.mock_used ? 'وضع التجربة' : (r.model || this.model) },
            ];
        },

        /* ---------------- تحميل القوائم ---------------- */

        async loadCatalog() {
            try {
                const data = await apiFetch('/api/prompt/frameworks');
                if (Array.isArray(data.tools) && data.tools.length) this.tools = data.tools;
                if (Array.isArray(data.frameworks) && data.frameworks.length) {
                    this.frameworks = data.frameworks;
                }
                if (data.default_framework) this.selectedFramework = data.default_framework;
                if (data.default_tool) this.selectedTool = data.default_tool;
                this.promptReady = data.ready !== false;
                this.promptMock = Boolean(data.mock_mode);
                this.model = data.model || this.model;
            } catch (_) {
                // نُبقي النسخة المحلية — القوائم تعمل بلا اتصال
            }
        },

        /* ---------------- اقتراح الإطار ---------------- */

        async applySuggestedFramework() {
            const text = this.trimmedInput;
            if (text.length < 3) return null;

            const data = await apiFetch(
                `/api/prompt/suggest?text=${encodeURIComponent(text)}`
            );
            this.selectedFramework = data.framework;
            this.suggestNotice = data.reason_ar || '';
            return data;
        },

        async suggestFramework() {
            this.error = '';

            if (this.trimmedInput.length < 3) {
                this.error = 'اكتب وصفًا أولًا — الاقتراح يحتاج 3 أحرف على الأقل';
                this.$store.toast.error(this.error);
                return;
            }

            this.isLoading = true;
            try {
                const data = await this.applySuggestedFramework();
                if (data) {
                    this.$store.toast.ok(`الإطار المقترح: ${data.framework_name}`);
                }
            } catch (err) {
                this.error = err.message || 'فشل اقتراح الإطار';
                this.$store.toast.error(this.error);
            } finally {
                this.isLoading = false;
            }
        },

        /* ---------------- التوليد ---------------- */

        async submitGenerate() {
            this.error = '';

            const text = this.trimmedInput;
            if (text.length < 3) {
                this.error = 'الوصف قصير جدًا — اكتب 3 أحرف على الأقل';
                this.$store.toast.error(this.error);
                return;
            }

            this.isLoading = true;

            try {
                // اقتراح الإطار تلقائيًا قبل التوليد (لا يُفشل التوليد إن أخفق)
                if (this.autoFramework) {
                    try {
                        await this.applySuggestedFramework();
                    } catch (_) {
                        this.suggestNotice = '';
                    }
                }

                const data = await apiFetch('/api/prompt/generate', {
                    method: 'POST',
                    body: JSON.stringify({
                        input: text,
                        tool: this.selectedTool,
                        framework: this.selectedFramework,
                        language: this.selectedLanguage,
                        save: true,
                    }),
                });

                this.result = { ...data, enhanced: false };
                this.copied = false;

                const src = data.mock_used ? 'وضع التجربة' : (data.model || 'النموذج');
                this.$store.toast.ok(`تم التوليد عبر ${src} (${data.tokens_used} رمز)`);

                this.$nextTick(() => {
                    const el = document.getElementById('result-card');
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                });
            } catch (err) {
                this.error = err.message || 'فشل توليد البرومبت';
                this.$store.toast.error(this.error);
            } finally {
                this.isLoading = false;
            }
        },

        /* ---------------- تحسين النتيجة ---------------- */

        async enhanceResult() {
            this.error = '';

            const current = this.result?.prompt;
            if (!current) {
                this.error = 'لا يوجد برومبت لتحسينه — ولّد برومبتًا أولًا';
                this.$store.toast.error(this.error);
                return;
            }

            this.isEnhancing = true;

            try {
                const data = await apiFetch('/api/prompt/enhance', {
                    method: 'POST',
                    body: JSON.stringify({
                        prompt: current,
                        language: this.selectedLanguage,
                        save: false,
                    }),
                });

                this.result = {
                    ...this.result,
                    prompt: data.prompt,
                    tokens_used: data.tokens_used,
                    mock_used: data.mock_used,
                    model: data.model,
                    enhanced: true,
                };

                this.$store.toast.ok('تم تحسين البرومبت');
            } catch (err) {
                this.error = err.message || 'فشل تحسين البرومبت';
                this.$store.toast.error(this.error);
            } finally {
                this.isEnhancing = false;
            }
        },

        /* ---------------- نسخ النتيجة ---------------- */

        async copyResult() {
            const text = this.result?.prompt;
            if (!text) {
                this.$store.toast.error('لا يوجد برومبت لنسخه');
                return;
            }

            try {
                await copyToClipboard(text);
                this.copied = true;
                this.$store.toast.ok('تم نسخ البرومبت إلى الحافظة');
                setTimeout(() => {
                    this.copied = false;
                }, 2000);
            } catch (_) {
                this.$store.toast.error('تعذّر النسخ — حدّد النص وانسخه يدويًا');
            }
        },

        /* ---------------- الوصف النصي ---------------- */

        clearError(kind) {
            if (kind === 'text') this.error = '';
        },

        /* ---------------- اختيار/سحب الملف ---------------- */

        onPick(event) {
            const file = event.target.files?.[0];
            if (file) this.uploadAudio(file);
            event.target.value = '';
        },

        onDrop(event) {
            this.dragActive = false;
            const file = event.dataTransfer?.files?.[0];
            if (file) this.uploadAudio(file);
        },

        /* ---------------- الرفع والتفريغ ---------------- */

        async uploadAudio(file) {
            this.audioError = '';
            this.uploadStatus = '';
            this.transcribeMock = false;

            if (!file) return;

            // فحص سريع قبل الشبكة
            if (file.size === 0) {
                this.audioError = 'الملف فارغ';
                this.$store.toast.error(this.audioError);
                return;
            }
            if (file.size > this.maxUploadMb * 1024 * 1024) {
                this.audioError =
                    `حجم الملف ${formatSize(file.size)} — الحد الأقصى ${this.maxUploadMb} ميجابايت`;
                this.$store.toast.error(this.audioError);
                return;
            }

            this.audioFile = file;
            this.uploading = true;
            this.uploadStatus = 'جارٍ الرفع والتفريغ…';

            try {
                const form = new FormData();
                form.append('file', file, file.name);

                const data = await apiFetch('/api/transcribe', { method: 'POST', body: form });

                const text = (data.text || '').trim();
                if (text) {
                    this.inputText = this.inputText ? `${this.inputText}\n\n${text}` : text;
                    this.transcribeMock = Boolean(data.mock);
                    this.uploadStatus = 'تم التفريغ بنجاح';
                    this.transcribeReady = true;
                    this.$store.toast.ok(
                        data.mock
                            ? 'تم (وضع التجربة) — النص وهمي'
                            : `تم تفريغ ${formatSize(file.size)} بنجاح`
                    );
                } else {
                    this.audioError = 'لم يُكتشف كلام في هذا الملف';
                    this.$store.toast.error(this.audioError);
                }
            } catch (err) {
                this.audioError = err.message || 'فشل تفريغ الصوت';
                if (String(err.message || '').includes('انتهت الجلسة')) return;
                this.$store.toast.error(this.audioError);
            } finally {
                this.uploading = false;
                this.audioFile = null;
            }
        },

        /* ---------------- التسجيل المباشر ---------------- */

        toggleRecording() {
            if (this.isRecording) {
                this.stopRecording();
            } else {
                this.startRecording();
            }
        },

        async startRecording() {
            this.audioError = '';

            if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
                this.mediaRecorderSupported = false;
                this.audioError = 'متصفحك لا يدعم التسجيل المباشر — استخدم رفع الملف';
                this.$store.toast.error(this.audioError);
                return;
            }

            try {
                this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch (_) {
                this.audioError =
                    'تم رفض إذن الميكروفون — فعّله من إعدادات المتصفح ثم أعد المحاولة';
                this.$store.toast.error(this.audioError);
                return;
            }

            const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg', ''];
            const mimeType = candidates.find((m) =>
                m ? MediaRecorder.isTypeSupported?.(m) : true
            );

            try {
                this._recorder = mimeType
                    ? new MediaRecorder(this._stream, { mimeType })
                    : new MediaRecorder(this._stream);
            } catch (_) {
                this._recorder = new MediaRecorder(this._stream);
            }

            this._chunks = [];
            this._recorder.ondataavailable = (event) => {
                if (event.data && event.data.size > 0) this._chunks.push(event.data);
            };

            this._recorder.onstop = async () => {
                const type = this._recorder?.mimeType || 'audio/webm';
                const blob = new Blob(this._chunks, { type });
                this.releaseMic();

                const ext = type.includes('mp4')
                    ? 'mp4'
                    : type.includes('ogg')
                      ? 'ogg'
                      : 'webm';
                const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
                const file = new File([blob], `recording-${stamp}.${ext}`, { type });

                if (file.size < 1200) {
                    this.audioError = 'التسجيل قصير جدًا — تحدث أكثر ثم أعد المحاولة';
                    this.$store.toast.error(this.audioError);
                    return;
                }

                await this.uploadAudio(file);
            };

            this._recorder.start(250);
            this.isRecording = true;
            this.recSeconds = 0;
            this._timer = setInterval(() => {
                this.recSeconds += 1;
            }, 1000);
        },

        stopRecording() {
            if (this._recorder && this._recorder.state !== 'inactive') {
                this._recorder.stop(); // onstop يتولى الإرسال
            }
            this.clearTimer();
            this.isRecording = false;
        },

        clearTimer() {
            if (this._timer) {
                clearInterval(this._timer);
                this._timer = null;
            }
        },

        releaseMic() {
            this.clearTimer();
            if (this._stream) {
                this._stream.getTracks().forEach((track) => track.stop());
                this._stream = null;
            }
            this.isRecording = false;
        },

        /* ---------------- تسجيل الخروج ---------------- */

        logout() {
            return pcLogout();
        },

        /* ---------------- الإقلاع ---------------- */

        init() {
            // تحذير قبل مغادرة الصفحة أثناء التسجيل أو الرفع
            window.addEventListener('beforeunload', (event) => {
                if (this.isRecording || this.uploading || this.isLoading) {
                    event.preventDefault();
                    event.returnValue = '';
                }
            });

            // تحرير الميكروفون عند الخروج
            window.addEventListener('pagehide', () => this.releaseMic());

            this.loadCatalog();
            this.consumePrefill();
        },

        /**
         * يقرأ وصفًا محفوظًا من "استخدمه" في المكتبة ويملأ مربع الوصف.
         *
         * نضع `raw_input` لا البرومبت الجاهز: هذا المربع يستقبل *الوصف* ويولّد
         * منه برومبتًا جديدًا، ولو وضعنا فيه برومبتًا جاهزًا لتولّد فوقه الثاني.
         * نحدّد الأداة والإطار أيضًا إن كانا معروفين لدى المحرك.
         */
        consumePrefill() {
            let payload;
            try {
                const raw = sessionStorage.getItem('pc:prefill');
                if (!raw) return;
                sessionStorage.removeItem('pc:prefill');
                payload = JSON.parse(raw);
            } catch (_) {
                return;
            }

            if (!payload) return;

            if (payload.raw) this.inputText = payload.raw;
            if (payload.tool && this.tools.some((t) => t.id === payload.tool)) {
                this.selectedTool = payload.tool;
            }
            if (payload.framework && this.frameworks.some((f) => f.id === payload.framework)) {
                this.selectedFramework = payload.framework;
            }

            this.$store.toast.ok('تم جلب الوصف من مكتبتك — عدّل ثم ولّد');
        },
    };
}

/* ==========================================================
   تسجيل الخروج — دالة عامة (قابلة للاستدعاء من أي نطاق Alpine)
   ========================================================== */

async function pcLogout() {
    try {
        await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch (_) {
        // حتى لو فشل الطلب، نخرج من الواجهة
    }
    window.location.href = '/login';
}

window.pcLogout = pcLogout;

/* ==========================================================
   قائمة التنبيهات (Toast) — عبر Alpine store
   ========================================================== */

function toastStack() {
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
   تسجيل المكونات مع Alpine
   ========================================================== */

document.addEventListener('alpine:init', () => {
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

    window.Alpine.data('loginForm', loginForm);
    window.Alpine.data('composer', composer);
    window.Alpine.data('toastStack', toastStack);
});

/* إتاحة الأدوات للتنقيح */
window.PC_FORMAT_TIME = formatTime;
window.PC_FORMAT_SIZE = formatSize;