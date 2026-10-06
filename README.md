# PromptCraft

> حوّل وصفك النصي أو الصوتي إلى **برومبت احترافي مهيكلة**، جاهز للنسخ، لكل أدوات الذكاء الاصطناعي.

PromptCraft أداة مستقلة تعمل على جهازك أو سيرفرك الخاص. تصف ما تريده بكلماتك (أو بتسجيل صوتي)، تختار الأداة المستهدفة، وتخرج خلال ثوانٍ برومبتًا منظمًا يتضمن: الدور، السياق، المهمة، القيود، صيغة المخرجات، أمثلة Few-shot، والقيود السلبية — مضبوطًا على quirks كل أداة.

---

## 📍 الحالة الحالية — المرحلة 2 ✅

| # | المرحلة | المحتوى | الحالة |
|---|---|---|---|
| 1 | الباكند + تسجيل الدخول | FastAPI، SQLite، جدولا `users` و `sessions`، كوكي `session_token`، `get_current_user` | ✅ |
| **2** | **الواجهة + الصوت** | **`/login` + `/app` (RTL، Tailwind + Alpine)، رفع صوت (سحب/تصفح)، تسجيل مباشر (MediaRecorder)، تفريغ Whisper** | ✅ |
| 3 | محرك البرومبتات (نص) | `tool_profiles`، `prompt_engine`، جدول `prompts` | ⬜ |
| 4 | خط أنابيب الصوت | تقطيع للملفات الطويلة، SSE للتقدّم، WAV/MP3 normalization | ⬜ |
| 5 | التكرارات والإتقان | الإصدارات، الاختبارات، الإحصاءات | ⬜ |
| 6 | التصليب والتسليم | Docker، مراجعة أمنية | ⬜ |

الخطة الكاملة في **[PLAN.md](PLAN.md)**.

---

## 🔑 هل أحتاج `OPENAI_API_KEY` الآن؟

| الحالة | التفريغ الصوتي | الواجهة |
|---|---|---|
| `WHISPER_MOCK=true` (الحالي في `.env` المحلي) | ✅ يعمل — نص **وهمي** للمعاينة، بلا اتصال | تعمل كاملة |
| مفتاح مضبوط + `WHISPER_MOCK=false` | ✅ تفريغ حقيقي بـ Whisper | تعمل كاملة |
| بلا مفتاح + `WHISPER_MOCK=false` | ❌ يرجع `503` برسالة عربية واضحة | تعمل، مع تحذير برتقالي |

**لتفعيل التفريغ الحقيقي:**

```ini
# في ملف .env
OPENAI_API_KEY=sk-...
WHISPER_MOCK=false
```

ثم أعد تشغيل الخادم. بدون ذلك **كل شيء يعمل** عدا أن النص الناتج وهمي.

---

## 🔧 المتطلبات

| المتطلب | النسخة | ملاحظة |
|---|---|---|
| Python | 3.11+ (تم التطوير على 3.13) | إلزامي |
| SQLite | مدمج مع Python | لا يحتاج تثبيت |
| FFmpeg | — | مطلوب في **المرحلة 4** (تقطيع + تطبيع الصوت) |
| متصفح حديث | Chrome / Edge / Firefox / Safari | التسجيل المباشر يحتاج `MediaRecorder` + إذن الميكروفون |

---

## 🚀 تعليمات التشغيل

### 1) تثبيت الحزم

```bash
pip install -r requirements.txt
```

> 💡 بيئة افتراضية موصى بها:
> ```bash
> python -m venv .venv
> .venv\Scripts\activate          # ويندوز
> source .venv/bin/activate       # لينكس / ماك
> pip install -r requirements.txt
> ```

### 2) إعداد ملف البيئة

```bash
copy .env.example .env            # ويندوز
cp .env.example .env              # لينكس / ماك
```

```ini
SECRET_KEY=change_me             # ⚠️ ولّد مفتاحًا: python -c "import secrets; print(secrets.token_urlsafe(48))"
DATABASE_URL=sqlite:///./data/promptcraft.db
OPENAI_API_KEY=                  # اتركه فارغًا للتجربة
WHISPER_MOCK=true                 # true = نص وهمي بدون مفتاح
```

### 3) تشغيل الخادم

```bash
uvicorn app.main:app --reload
```

| الرابط | الوصف |
|---|---|
| <http://127.0.0.1:8000/login> | صفحة تسجيل الدخول |
| <http://127.0.0.1:8000/app> | واجهة الإنشاء (محمية) |
| <http://127.0.0.1:8000/api/docs> | توثيق Swagger التفاعلي |
| <http://127.0.0.1:8000/api/health> | فحص الصحة |

---

## 🧭 كيف تعمل الواجهة؟

### صفحة الدخول `/login`
1. تكتب اسم المستخدم فقط ← لا كلمة مرور.
2. `POST /api/auth/login` عبر `fetch` (مع `credentials: same-origin`).
3. النجاح → `window.location.href = '/app'`.
4. الفشل → رسالة عربية داخل البطاقة (422 / 503 / خطأ شبكة).

### واجهة الإنشاء `/app`
| العنصر | السلوك |
|---|---|
| **textarea الوصف** | يُملأ يدويًا أو تلقائيًا بنص الصوت |
| **منطقة السحب والإفلات** | `@dragover/@drop` + زر "تصفّح من جهازك" |
| **زر التسجيل المباشر** | `MediaRecorder` — زر واحد يبدأ/يوقف، مع مؤقّت `mm:ss` ونقطة نابضة |
| **select الأداة** | ChatGPT · Claude · Gemini · Midjourney · Cursor · عام |
| **زر التوليد** | معطّل الآن — محرك البرومبتات في المرحلة 3 |
| **منطقة النتيجة** | حالة فارغة (تظهر في المرحلة 3) |

**رفع الملف:**
```
اختيار/سحب → فحص سريع (الحجم) → POST /api/transcribe (FormData)
   → uploading=true + "جارٍ الرفع والتفريغ…"
   → 200  → النص يُدمج في textarea + toast أخضر
   → 4xx → رسالة عربية داخل منطقة الرفع + toast أحمر
```
**التسجيل:** نفس المسار بعد `stop()` — الملف الناتج يُرفع تلقائيًا (`.webm` / `.mp4` حسب المتصفح).

> ⚠️ التسجيل المباشر يعمل على `localhost` أو `https` فقط (شرط المتصفح لواجهة `MediaRecorder`).

---

## 🔌 نقاط النهاية

| Method | Path | الوصف | الجلسات |
|---|---|---|---|
| `GET` | `/` | يحوّل إلى `/app` أو `/login` | — |
| `GET` | `/login` | صفحة الدخول | — |
| `GET` | `/app` | واجهة الإنشاء | ✅ |
| `GET` | `/session` | حالة الجلسة (JSON) | اختياري |
| `GET` | `/api/health` | صحة التطبيق | — |
| `GET` | `/api` | فهرس المسارات | — |
| `POST` | `/api/auth/login` | دخول/إنشاء حساب | — |
| `POST` | `/api/auth/logout` | حذف الجلسة | اختياري |
| `GET` | `/api/auth/me` | المستخدم الحالي | ✅ |
| `GET` | `/api/auth/check?username=` | فحص صلاحية الاسم | — |
| `GET` | `/api/auth/sessions` | جلسات المستخدم | ✅ |
| **`POST`** | **`/api/transcribe`** | **تفريغ ملف صوتي (multipart: file)** | **✅** |
| `GET` | `/api/transcribe/info` | حالة خدمة التفريغ | ✅ |

### `POST /api/transcribe`

```bash
curl -X POST http://localhost:8000/api/transcribe \
     -H "Cookie: session_token=YOUR_TOKEN" \
     -F "file=@sample.mp3" \
     -F "language=ar"          # اختياري: ar | en — بلاه يُكتشف تلقائيًا
```

**الرد الناجح 200:**
```json
{
  "success": true,
  "text": "النص المستخرج…",
  "language": "ar",
  "filename": "sample.mp3",
  "size_bytes": 96044,
  "model": "whisper-1",
  "duration_estimate_sec": 3.0,
  "segments": [{"start": 0.0, "end": 2.4, "text": "…"}],
  "mock": false
}
```

| رمز الخطأ | السبب | الرسالة |
|---|---|---|
| `401` | بدون جلسة | `يجب تسجيل الدخول أولًا — أدخل اسم المستخدم` |
| `413` | أكبر من 25MB | `حجم الملف 30.0 ميجابايت، والحد الأقصى 25 ميجابايت` |
| `415` | صيغة غير مدعومة / فارغ | `الصيغة .txt غير مدعومة…` |
| `500` | خطأ غير متوقع | `حدث خطأ غير متوقع أثناء تفريغ الصوت…` |
| `502` | فشل الاتصال بـ OpenAI | `تعذّر الاتصال بخدمة التفريغ…` |
| `503` | لا يوجد مفتاح | `مفتاح OpenAI غير مضبوط…` |

**الصيغ المدعومة:** `mp3 · mp4 · m4a · wav · webm · ogg · mpeg · mpga · flac` — والحد الأقصى 25 ميجابايت.

---

## 🧪 اختبار سريع

### `test_audio.sh` (يتطلب `bash` + `curl`)

```bash
bash test_audio.sh                  # يولّد WAV تجريبيًا ويرفعه
bash test_audio.sh path/to/audio.mp3
PC_USERNAME=someone bash test_audio.sh
```

السكربت: يفحص الصحة → يسجّل الدخول → يولّد/يحمّل ملفًا → يرفعه → يطبع النص أو سبب الفشل برمز HTTP، ويحذف ملفه المؤقت.

### من بايثون

```python
import httpx

with httpx.Client(base_url="http://localhost:8000") as c:
    c.post("/api/auth/login", json={"username": "murad"})

    with open("sample.mp3", "rb") as f:
        r = c.post("/api/transcribe", files={"file": ("sample.mp3", f, "audio/mpeg")})

    print(r.status_code, r.json()["text"])
```

---

## 🗂️ هيكل المشروع (الحالي)

```
promptcraft/
├── app/
│   ├── __init__.py
│   ├── main.py               # app + CORS + static + صفحات HTML + /api/health
│   ├── config.py             # إعدادات pydantic-settings (uploads, whisper, حدود)
│   ├── database.py           # engine، SessionLocal، get_db، init_db، PRAGMAs
│   ├── models.py             # User، Session (ORM)
│   ├── schemas.py            # مخططات Pydantic للمصادقة
│   ├── auth.py               # create_session، الكوكيز، get_current_user، get_optional_user
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth_router.py    # /api/auth/*
│   │   └── audio_router.py   # /api/transcribe
│   └── services/
│       ├── __init__.py
│       └── transcription.py  # async transcribe_audio() عبر Whisper
├── templates/
│   ├── login.html            # صفحة الدخول (Tailwind + Alpine)
│   └── app.html              # واجهة الإنشاء + الصوت
├── static/
│   ├── css/style.css         # تخصيصات فوق Tailwind
│   └── js/app.js             # Alpine components + fetch + MediaRecorder
├── data/
│   ├── .gitkeep
│   ├── promptcraft.db        # SQLite
│   └── uploads/              # ملفات صوتية مؤقتة (تُحذف بعد التفريغ)
├── .env.example
├── .gitignore
├── requirements.txt
├── test_audio.sh
├── PLAN.md
└── README.md
```

---

## 🐛 حل المشاكل السريع

| المشكلة | الحل |
|---|---|
| `ModuleNotFoundError: No module named 'app'` | شغّل الأمر من جذر المشروع `promptcraft/` |
| الصفحة تُعيدني إلى `/login` دائمًا | الكوكي غير محفوظ — تحقّق من `SECRET_KEY` ثابت بين التشغيلات، ومن أن المتصفح يقبل الكوكي على `localhost` |
| زر التسجيل معطّل | المتصفح لا يدعم `MediaRecorder`، أو الإذن مرفوض — استخدم رفع الملف |
| التسجيل لا يعمل على IP الشبكة | `MediaRecorder` يحتاج `localhost` أو HTTPS |
| `503` عند تفريغ الصوت | `OPENAI_API_KEY` غير مضبوط — أضفه في `.env` واضبط `WHISPER_MOCK=false` |
| `413` رغم أن الملف صغير | تحقق من `MAX_UPLOAD_MB` في `.env` |
| `422` على تسجيل الدخول | الاسم خارج القواعد: 3–32 حرفًا، إنجليزي/أرقام و `_ . -` فقط، وغير محجوز |
| نسيت كلمة المرور | لا توجد كلمة مرور! أدخل نفس الاسم مجددًا |

**السجلات:** كل الأحداث في الطرفية باسم المستخدم والوقت. `DEBUG=true` في `.env` لمزيد من التفاصيل.

---

## 📄 الرخصة

مشروع شخصي — استخدمه وعدّله كما تشاء.
