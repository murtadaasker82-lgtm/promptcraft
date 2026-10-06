/* ==========================================================
   PromptCraft — منطق Alpine.js + التعامل مع الـ API
   يُحمَّل قبل Alpine.js (بدون defer) ليسجّل alpine:init
   ========================================================== */

/* ---------------- إعدادات الصفحة (من Jinja2) ---------------- */

const CFG = window.__PC_CONFIG__ || {};

/* قائمة الأدوات المستهدفة */
const TARGET_TOOLS = [
    { id: 'chatgpt', name: 'ChatGPT', hint: 'حوار عام، تحليل، كتابة' },
    { id: 'claude', name: 'Claude', hint: 'نصوص طويلة، كود، مستندات' },
    { id: 'gemini', name: 'Gemini', hint: 'بحث، Google-flavored' },
    { id: 'midjourney', name: 'Midjourney', hint: 'صور — visual prompt' },
    { id: 'cursor', name: 'Cursor', hint: 'تعديل كود داخل IDE' },
    { id: 'general', name: 'عام', hint: 'محايد لكل النماذج' },
];

/* كائن عام متاح لكل قوالب Alpine في الصفحة */
window.PC = {
    user: CFG.user || { username: '—' },
    maxUploadMb: CFG.max_upload_mb || 25,
    allowedExtensions: CFG.allowed_extensions || [],
    transcribeReady: CFG.transcribe_ready !== false,
    tools: TARGET_TOOLS,
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
        413: 'الملف كبير جدًا (الحد 25 ميجابايت)',
        415: 'نوع الملف غير مدعوم',
        429: 'محاولات كثيرة — انتظر قليلًا ثم أعد المحاولة',
        500: 'خطأ في الخادم',
        502: 'فشل الاتصال بخدمة OpenAI',
        503: 'مفتاح OpenAI غير مضبوط',
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

        get displayName() {
            return this.username.trim();
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
            if (name.length < 3) {
                this.error = 'اسم المستخدم قصير جدًا — 3 أحرف على الأقل';
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
        tools: window.PC.tools,

        // ---- الحالة ----
        inputText: '',
        targetTool: 'general',
        generateNotice: '',

        // ---- الصوت ----
        audioFile: null,
        audioError: '',
        uploadStatus: '',
        uploading: false,
        dragActive: false,
        isMock: false,

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

        get currentToolHint() {
            const tool = this.tools.find((t) => t.id === this.targetTool);
            return tool ? tool.hint : '';
        },

        /* ---------------- الوصف النصي ---------------- */

        clearError(kind) {
            if (kind === 'text') this.generateNotice = '';
            if (kind === 'audio') this.audioError = '';
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
            this.isMock = false;

            if (!file) return;

            // فحص سريع قبل الشبكة
            if (file.size === 0) {
                this.audioError = 'الملف فارغ';
                return;
            }
            if (file.size > this.maxUploadMb * 1024 * 1024) {
                this.audioError =
                    `حجم الملف ${formatSize(file.size)} — الحد الأقصى ${this.maxUploadMb} ميجابايت`;
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
                    this.isMock = Boolean(data.mock);
                    this.uploadStatus = 'تم التفريغ بنجاح';
                    this.transcribeReady = true;
                    this.$store.toast.ok(
                        data.mock
                            ? 'تم (وضع التجربة) — النص وهمي'
                            : `تم تفريغ ${formatSize(file.size)} بنجاح`
                    );
                } else {
                    this.audioError = 'لم يُكتشف كلام في هذا الملف';
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

        async toggleRecording() {
            if (this.isRecording) {
                this.stopRecording();
                return;
            }
            await this.startRecording();
        },

        async startRecording() {
            this.audioError = '';

            if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
                this.mediaRecorderSupported = false;
                this.audioError = 'متصفحك لا يدعم التسجيل المباشر — استخدم رفع الملف';
                return;
            }

            try {
                this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch (_) {
                this.audioError =
                    'تم رفض إذن الميكروفون — فعّله من إعدادات المتصفح ثم أعد المحاولة';
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
        /* ملاحظة: زر الهيدر خارج نطاق هذا المكوّن، لذلك يستخدم الدالة العامة pcLogout */

        init() {
            // تحذير قبل مغادرة الصفحة أثناء التسجيل أو الرفع
            window.addEventListener('beforeunload', (event) => {
                if (this.isRecording || this.uploading) {
                    event.preventDefault();
                    event.returnValue = '';
                }
            });

            // تحرير الميكروفون عند الخروج
            window.addEventListener('pagehide', () => this.releaseMic());
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
