# PromptCraft — خطة المشروع

> أداة مستقلة (standalone) لتحويل الأوصاف الصوتية والنصية إلى برومبتات احترافية مهيكلة، جاهزة للنسخ، ومخزّنة في مكتبة خاصة بكل مستخدم.

---

## 0. ملخص الرؤية

| البند | القيمة |
|---|---|
| المشكلة | المستخدم يصف ما يريده فوضويًا (نصًا أو صوتًا)، ويضيع وقتًا في إعادة صياغة الطلب حتى تصل النتيجة المطلوبة. |
| الحل | PromptCraft يحوّل الوصف الخام إلى **برومبت مهيكل** (دور + سياق + مهمة + قيود + صيغة مخرجات + أمثلة) مضبوط على quirks الأداة المستهدفة. |
| المستخدمون | مطورون، مصممون، صنّاع محتوى، رواد أعمال — Mausool / Murad / أي شخص. |
| قيد التصميم | تسجيل دخول باسم المستخدم فقط (بلا كلمة مرور) → الأمان يعتمد على **عدم معرفة الاسم** + كوكي جلسة + rate limiting، وليس على تشفير. |
| المكدس | FastAPI + SQLite (SQLAlchemy) + Jinja2 + TailwindCSS + Alpine.js + OpenAI (Whisper + GPT). |

### مبادئ التصميم
1. **Privacy-first** — كل استعلامات SQLite مُقيَّدة بـ `user_id`، ولا يوجد endpoint بدون تحقق من الجلسة.
2. **UX في 60 ثانية** — من فتح الصفحة إلى نسخ البرومبت أقل من دقيقة في الحالة النصية.
3. **Copy-first** — الزر الأساسي في كل مكان هو "نسخ"، والمحتوى يولّد داخل `<pre>` قابل للتحديد.
4. **قابل للتوسّع** — إضافة profile لأداة جديدة = ملف تعريف واحد داخل `tool_profiles.py`، بدون لمس الـ endpoints.
5. **تكلفة أقل** — نستخدم نموذجًا صغيرًا للتصنيف ونموذجًا قويًا للكتابة النهائية فقط عند الحاجة.

---

## 1. هيكل المجلدات المقترح

```
promptcraft/
│
├── app/
│   ├── __init__.py                  # إنشاء التطبيق (application factory)
│   ├── main.py                      # نقطة الدخول: app = create_app() + static/templates mount
│   ├── config.py                    # إعدادات من .env (pydantic-settings)
│   ├── database.py                  # engine, SessionLocal, get_db, init_db
│   ├── models.py                    # نماذج SQLAlchemy (كل الجداول)
│   ├── schemas.py                   # مخططات Pydantic للطلب/الاستجابة
│   ├── security.py                  # hashing الكوكيز، إنشاء الجلسات، rate limit
│   ├── deps.py                      # get_current_user, require_user (FastAPI dependencies)
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── pages.py                 # GET /, /login, /app, /library
│   │   ├── auth.py                  # login / logout / me / check-username
│   │   ├── uploads.py               # رفع الصوت والتحقق منه
│   │   ├── transcribe.py            # تفريغ Whisper (+ SSE للتقدّم)
│   │   ├── prompts.py               # توليد / جلب / تعديل / حذف / نسخ / إعادة توليد
│   │   ├── jobs.py                  # استعلام حالة المهام الطويلة
│   │   ├── library.py               # إحصاءات + تصدير + بحث متقدم
│   │   └── settings.py              # إعدادات المستخدم ومفتاح OpenAI الخاص به
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── openai_client.py         # عميل OpenAI موحّد (Chat + Whisper)، retry + timeout
│   │   ├── transcription.py         # تفريغ صوتي، تقطيع للملفات الطويلة، تنظيف النص
│   │   ├── prompt_engine.py         # بناء system/user prompt وتنسيق المخرجات
│   │   ├── tool_profiles.py         # ⚙️ تعريف الأدوات الست (القاعدة القابلة للتوسّع)
│   │   ├── refine.py                # تنظيف/توحيد صيغة المخرجات + التحقق من البنية
│   │   ├── audio.py                 # ffprobe للمدة/الصيغة + التحويل عبر FFmpeg
│   │   ├── storage.py               # تخزين الملفات، حدود الحجم، حذف آلي
│   │   └── prompts_bank.py          # قوالب Few-shot جاهزة لكل أداة
│   │
│   ├── templates/
│   │   ├── base.html                # الهيكل العام + Tailwind + Alpine + RTL/LTR
│   │   ├── login.html
│   │   ├── composer.html            # واجهة الإنشاء (نص/صوت + اختيار الأداة)
│   │   ├── library.html             # شبكة المكتبة + بحث + فلاتر
│   │   ├── prompt_detail.html       # تفاصيل + النسخ + الإصدارات
│   │   └── partials/
│   │       ├── _prompt_card.html
│   │       ├── _tool_picker.html
│   │       ├── _uploader.html
│   │       ├── _result_panel.html
│   │       └── _toast.html
│   │
│   └── static/
│       ├── css/app.css              # ألوان، خطوط، حركات، dark mode
│       ├── js/app.js                # Alpine stores/components
│       ├── js/composer.js
│       ├── js/library.js
│       └── vendor/
│           └── alpine.min.js        # vendored (لا نتبع CDN في الإنتاج)
│
├── data/                            # ⚠️ مُستثنى من Git
│   ├── promptcraft.db               # SQLite (WAL mode)
│   ├── uploads/
│   │   └── {user_id}/{uuid}.{ext}
│   └── logs/
│
├── scripts/
│   ├── seed_profiles.py             # بذر بيانات تجريبية + tool profiles في DB
│   ├── backup_db.py                 # نسخ احتياطي مجدول (sqlite .backup)
│   └── cleanup_uploads.py           # حذف الملفات الأيتيمة/القديمة
│
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_prompts_isolation.py    # ⭐ عزل البيانات بين المستخدمين
│   ├── test_prompt_engine.py
│   └── test_uploads.py
│
├── prompts_specs/                   # ملفات Markdown خارجية للتعديل بلا كود
│   ├── system_base.md
│   └── tools/{chatgpt,claude,gemini,midjourney,cursor,general}.md
│
├── requirements.txt
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── run.py                           # uvicorn محلي للتطوير
├── PLAN.md
└── README.md
```

---

## 2. جداول قاعدة البيانات

> المحرك: SQLite مع `PRAGMA journal_mode=WAL` و `PRAGMA foreign_keys=ON`.
> كل الجداول النشطة تحمل `created_at` / `updated_at` بصيغة ISO-8601 UTC.

### 2.1 `users` — المستخدمون

| العمود | النوع | ملاحظات |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `username` | TEXT **UNIQUE NOT NULL** | `COLLATE NOCASE`، 3–32 حرفًا، `[a-z0-9_.-]` فقط |
| `display_name` | TEXT NULL | يظهر في الواجهة |
| `password_hash` | TEXT NULL | **يُترك NULL دائمًا** — محجوز إن أُضيفت مصادقة أقوى لاحقًا |
| `openai_api_key` | TEXT NULL | مفتاح المستخدم الخاص (اختياري، مشفّر Fernet في `security.py`) |
| `use_server_key` | INTEGER DEFAULT 1 | هل يخدم مفتاح السيرفر؟ |
| `preferences_json` | TEXT | `{"default_tool":"general","ui_lang":"ar","tone":"professional","output_format":"md"}` |
| `is_active` | INTEGER DEFAULT 1 | تعطيل يدوي |
| `role` | TEXT DEFAULT 'user' | `user` \| `admin` (للإحصاءات) |
| `created_at` / `last_login_at` | DATETIME | |

**فهارس:** `ux_users_username` (unique)، `idx_users_active`.

### 2.2 `sessions` — جلسات الدخول (كوكي موقّع)

| العمود | النوع | ملاحظات |
|---|---|---|
| `id` | TEXT PK | `secrets.token_urlsafe(32)` (الرمز نفسه لا يُخزّن) |
| `token_hash` | TEXT **UNIQUE NOT NULL** | `sha256(token)` — هاشنج، فالسرقة من DB لا تكفي |
| `user_id` | INTEGER FK → users.id (CASCADE) | |
| `created_at` | DATETIME | |
| `expires_at` | DATETIME | افتراضي 30 يومًا |
| `last_seen_at` | DATETIME | لتحديث الـ sliding expiration |
| `user_agent` / `ip` | TEXT NULL | للتشخيص |
| `revoked_at` | DATETIME NULL | logout = soft revoke |

**فهارس:** `ux_sessions_token_hash`، `idx_sessions_user`، `idx_sessions_expires`.

### 2.3 `prompts` — البرومبتات (المكتبة)

| العمود | النوع | ملاحظات |
|---|---|---|
| `id` | INTEGER PK | |
| `user_id` | INTEGER FK (CASCADE) | **كل استعلام مفلتر بهذا العمود** |
| `title` | TEXT NOT NULL | يُولَّد تلقائيًا من أول 60 حرفًا إن لم يحدده المستخدم |
| `source_type` | TEXT NOT NULL | `text` \| `audio` |
| `source_text` | TEXT | النص المكتوب يدويًا أو نص التفريغ |
| `transcript_language` | TEXT NULL | `ar` \| `en` \| `auto` |
| `audio_file_id` | TEXT NULL | FK → uploads.id |
| `audio_filename` / `audio_mime` / `audio_size_bytes` / `audio_duration_sec` | TEXT/INT/INT/FLOAT | بيانات وصفية |
| `target_tool` | TEXT NOT NULL | `chatgpt\|claude\|gemini\|midjourney\|cursor\|general` |
| `tone` | TEXT NULL | `professional\|casual\|technical\|persuasive\|academic` |
| `detail_level` | TEXT NULL | `concise\|balanced\|deep` |
| `output_format` | TEXT NULL | `markdown\|plain\|json` |
| `generated_prompt` | TEXT NOT NULL | ⭐ النص النهائي الجاهز للنسخ |
| `structured_json` | TEXT NULL | الأقسام مفصولة: `{role, context, task, constraints, output_format, examples[], negative[], variables[]}` |
| `quality_score` | FLOAT NULL | 0–100 من مقيّم ذاتي |
| `token_estimate` | INTEGER NULL | تقدير token للعرض فقط |
| `model_used` | TEXT NULL | مثل `gpt-4o-mini` / `gpt-4o` |
| `status` | TEXT DEFAULT 'ready' | `queued\|processing\|ready\|error` |
| `error_message` | TEXT NULL | |
| `is_favorite` | INTEGER DEFAULT 0 | ⭐ نجمة |
| `is_archived` | INTEGER DEFAULT 0 | إخفاء من المكتبة النشطة |
| `copy_count` | INTEGER DEFAULT 0 | كم مرة نسخه المستخدم |
| `regenerate_count` | INTEGER DEFAULT 0 | كم مرة أعاد توليده |
| `tags_json` | TEXT | `["marketing","blog"]` |
| `created_at` / `updated_at` | DATETIME | |

**فهارس:** `idx_prompts_user_created (user_id, created_at DESC)`، `idx_prompts_user_tool (user_id, target_tool)`، `idx_prompts_user_fav (user_id, is_favorite)`، `idx_prompts_status`، و**FTS5 virtual table** `prompts_fts` على `(title, source_text, generated_prompt)` للبحث الحر.

### 2.4 `prompt_versions` — تاريخ إعادة التوليد

| العمود | النوع | ملاحظات |
|---|---|---|
| `id` | INTEGER PK | |
| `prompt_id` | INTEGER FK → prompts.id (CASCADE) | |
| `user_id` | INTEGER FK | |
| `version_no` | INTEGER | 1, 2, 3… |
| `generated_prompt` | TEXT | نسخة النص في هذه المرحلة |
| `delta_instruction` | TEXT NULL | ما الذي طلبه المستخدم عند إعادة التوليد ("أضف أمثلة"، "اختصر") |
| `model_used` / `tokens_in` / `tokens_out` | TEXT/INT/INT | لتتبّع التكلفة |
| `latency_ms` | INTEGER | |
| `is_current` | INTEGER | النسخة المعروضة حاليًا |
| `created_at` | DATETIME | |

**فهرس:** `idx_versions_prompt (prompt_id, version_no DESC)`.

### 2.5 `uploads` — الملفات الصوتية

| العمود | النوع | ملاحظات |
|---|---|---|
| `id` | TEXT PK | uuid4 hex |
| `user_id` | INTEGER FK | |
| `original_filename` | TEXT | |
| `stored_path` | TEXT | مسار نسبي داخل `data/uploads` |
| `mime_type` / `extension` / `size_bytes` | TEXT/INT | |
| `duration_sec` | FLOAT NULL | من ffprobe |
| `sha256` | TEXT | كشف التكرار |
| `status` | TEXT | `uploaded\|processing\|ready\|failed\|deleted` |
| `transcript` | TEXT NULL | نص Whisper النهائي |
| `transcript_segments_json` | TEXT NULL | `[{start, end, text}]` |
| `created_at` / `expires_at` | DATETIME | TTL افتراضي 24 ساعة للحذف التلقائي |

**فهارس:** `idx_uploads_user (user_id, created_at DESC)`، `idx_uploads_expires`.

### 2.6 `jobs` — المهام الطويلة (تفريغ / توليد)

| العمود | النوع | ملاحظات |
|---|---|---|
| `id` | TEXT PK | uuid4 hex (يربطه بـ `prompt_id`) |
| `user_id` | INTEGER FK | |
| `prompt_id` | INTEGER FK NULL | |
| `upload_id` | TEXT NULL | |
| `kind` | TEXT | `transcribe\|generate\|refine` |
| `status` | TEXT | `queued\|running\|succeeded\|failed\|cancelled` |
| `progress` | INTEGER | 0–100 |
| `stage` | TEXT NULL | `uploading\|normalizing\|transcribing\|polishing\|writing` |
| `payload_json` / `result_json` | TEXT | |
| `error_message` | TEXT | |
| `attempts` | INTEGER DEFAULT 0 | |
| `created_at` / `started_at` / `finished_at` | DATETIME | |

**فهرس:** `idx_jobs_user (user_id, created_at DESC)`، `idx_jobs_status`.

### 2.7 `usage_events` — التكلفة والقياس (اختياري لكن مُستحسن)

| العمود | النوع | ملاحظات |
|---|---|---|
| `id` | INTEGER PK | |
| `user_id` / `prompt_id` | INTEGER | |
| `operation` | TEXT | `transcribe\|generate\|classify\|refine` |
| `model` | TEXT | |
| `input_tokens` / `output_tokens` / `audio_seconds` | INTEGER | |
| `estimated_cost_usd` | FLOAT | |
| `latency_ms` | INTEGER | |
| `created_at` | DATETIME | |

### 2.8 العلاقات (ERD مبسّط)

```
users 1 ──< sessions
      1 ──< prompts 1 ──< prompt_versions
      1 ──< uploads
      1 ──< jobs
      1 ──< usage_events
```

### 2.9 قواعد السلامة الإلزامية
- كل `SELECT/UPDATE/DELETE` على `prompts`, `uploads`, `jobs` يحمل `WHERE user_id = :current_user`.
- اختبارات `test_prompts_isolation.py` تتحقق أن المستخدم (أ) لا يستطيع قراءة/تعديل/حذف معرّف برومبت للمستخدم (ب) عبر ID مباشر — يرجع `404` لا `403` (حماية من تعداد المعرّفات).
- حذف حقيقي = `ON DELETE CASCADE`، وحذف ناعم = `is_archived=1`.

---

## 3. الـ API Endpoints

> كلها تحت `/api` ما عدا صفحات HTML. الاستجابة JSON موحّدة: `{"ok": true, "data": ...}` أو `{"ok": false, "error": {"code","message"}}`.

### 3.1 المصادقة — `/api/auth`

| Method | Path | Body / Query | الرد | ملاحظات |
|---|---|---|---|---|
| `GET` | `/api/auth/check` | `?username=` | `{available: bool, reason?}` | القيود: 3–32 حرفًا، `[a-z0-9_.-]` فقط، وليس اسمًا محجوزًا |
| `POST` | `/api/auth/login` | `{username, display_name?}` | `{user:{id,username,display_name}}` | ينشئ المستخدم إن لم يوجد (تسجيل ذاتي)، ينشئ جلسة، `Set-Cookie: pc_session` (HttpOnly, SameSite=Lax, Secure في الإنتاج) |
| `POST` | `/api/auth/logout` | — | `{ok:true}` | `revoked_at = now()` + مسح الكوكي |
| `GET` | `/api/auth/me` | — | `{user, counts:{prompts,favorites}}` | 401 إذا انتهت/ُلغيت الجلسة |
| `POST` | `/api/auth/refresh` | — | `{ok:true}` | تمديد انزلاقي للجلسة |

**حماية:** حد 5 محاولات دخول / 10 دقائق لكل IP + اسم، تأخير عشوائي 0.4–1.2 ثانية عند الفشل، ونفس الرسالة في كل حالات الفشل (لا يفضّح وجود المستخدم من عدمه).

### 3.2 الأدوات والبيانات المرجعية — `/api/meta`

| Method | Path | الرد |
|---|---|---|
| `GET` | `/api/tools` | `[{id,name,icon,description,defaults:{tone,detail_level,output_format,labels:[...],max_chars,sections:[...]}}]` |
| `GET` | `/api/tools/{id}` | ملف تعريف الأداة الكامل |
| `GET` | `/api/tones` | قائمة النبرات المتاحة |
| `GET` | `/api/health` | `{status:"ok", db:true, openai_configured:bool, ffmpeg:bool, version}` |

### 3.3 الرفع والتفريغ — `/api/uploads`, `/api/transcribe`

| Method | Path | Body | الرد |
|---|---|---|---|
| `POST` | `/api/uploads/audio` | `multipart/form-data: file` | `{upload:{id,filename,duration_sec,mime,size_bytes}}` — يقبل: `mp3, m4a, wav, webm, ogg, flac, mp4, mpeg, mpga`، حد 25MB |
| `GET` | `/api/uploads/{id}` | — | بيانات الملف |
| `DELETE` | `/api/uploads/{id}` | — | حذف الملف والسجل |
| `POST` | `/api/transcribe` | `{upload_id}` أو `{audio_url?}` | `{job:{id,status}}` → غير متزامن |
| `POST` | `/api/transcribe/sync` | `{upload_id, language?}` | `{text, language, duration_sec, segments}` — للملفات القصيرة (< 60 ثانية) |
| `GET` | `/api/jobs/{id}` | — | `{status, stage, progress, result?, error?}` — polling كل 1s |
| `GET` | `/api/jobs/{id}/stream` | — | **SSE** لبثّ التقدّم اللحظي |

**سلوك النظام:**
1. التحقق من الحجم وتوقيع الصيغة (magic bytes) — لا يُعتمد على الـ Content-Type وحده.
2. `ffprobe` لاستخراج المدة + رفع تحذير إذا كانت > 10 دقائق.
3. تطبيع إلى `mp3 16kHz mono 64kbps` (لتقليل التكلفة + تسريع Whisper) عبر FFmpeg.
4. إذا المدة > 600 ثانية: تقطيع إلى مقاطع 5 دقائق مع 2 ثانية تداخل، ثم تفريغ كل مقطع ودمج النص.
5. تنظيف: إزالة تكرارات filler، توحيد الترقيم، تصحيح تلقائي لاتجاه النص (RTL/LTR).

### 3.4 البرومبتات — `/api/prompts`  ⭐ الأساسية

| Method | Path | Body / Query | الرد |
|---|---|---|---|
| `POST` | `/api/prompts/generate` | `{source_type:"text"\|"audio", text?, upload_id?, target_tool, tone?, detail_level?, output_format?, extra_notes?, language?}` | `201 {prompt:{...}}` — البرومبت الكامل + `structured_json` |
| `POST` | `/api/prompts/generate/async` | نفس الحقول | `{job:{id}}` — للملفات الصوتية الطويلة |
| `GET` | `/api/prompts` | `?q=&tool=&favorite=&archived=&status=&tag=&page=&per_page=&sort=` | `{items:[...], total, page, per_page, has_more}` |
| `GET` | `/api/prompts/{id}` | — | `{prompt:{..., versions:[...]}}` |
| `PATCH` | `/api/prompts/{id}` | `{title?, is_favorite?, is_archived?, tags?}` | `{prompt:{...}}` |
| `DELETE` | `/api/prompts/{id}` | — | `{ok:true}` (soft أو hard عبر `?hard=1`) |
| `POST` | `/api/prompts/{id}/copy` | — | `{ok:true, copy_count}` — يتتبّع النسخ |
| `POST` | `/api/prompts/{id}/regenerate` | `{delta_instruction?, tone?, detail_level?, target_tool?}` | `{prompt:{...}, new_version_no}` — يُنشئ صفًا في `prompt_versions` |
| `GET` | `/api/prompts/{id}/versions` | — | `[{version_no, generated_prompt, delta_instruction, created_at, is_current}]` |
| `POST` | `/api/prompts/{id}/restore/{version_no}` | — | استرجاع نسخة قديمة كنسخة حالية |
| `POST` | `/api/prompts/{id}/duplicate` | — | نسخة جديدة بنفس الإعدادات |
| `GET` | `/api/prompts/{id}/export` | `?fmt=md\|txt\|json` | ملف قابل للتنزيل |
| `GET` | `/api/prompts/{id}/share` | — | رابط عرض للقراءة فقط (token موقّع، 7 أيام) |

### 3.5 الإحصاءات — `/api/library`

| Method | Path | الرد |
|---|---|---|
| `GET` | `/api/stats` | `{total, by_tool:{...}, by_status, favorites, this_week, copy_count, tokens_saved_estimate}` |
| `GET` | `/api/search/suggest` | `?q=` → عناوين مقترحة (autocomplete من FTS) |
| `GET` | `/api/export/all` | `?fmt=json\|md` → نسخة كاملة من المكتبة |

### 3.6 الإعدادات — `/api/settings`

| Method | Path | Body |
|---|---|---|
| `GET` | `/api/settings` | `{preferences, openai_key_present, use_server_key}` |
| `PATCH` | `/api/settings/preferences` | جزئي: `{default_tool?, ui_lang?, tone?, detail_level?, theme?}` |
| `POST` | `/api/settings/openai-key` | `{api_key}` → تُشفَّر وتُحفظ، ترجع `403` إذا رُفضت عند اختبار الاتصال |
| `DELETE` | `/api/settings/openai-key` | حذف المفتاح |

### 3.7 صفحات HTML

| Method | Path | الوصف |
|---|---|---|
| `GET` | `/` | يحوّل إلى `/app` إن كانت جلسة سارية وإلا `/login` |
| `GET` | `/login` | صفحة الدخول |
| `GET` | `/app` | واجهة الإنشاء (Composer) — تتطلب جلسة |
| `GET` | `/library` | المكتبة |
| `GET` | `/p/{id}` | صفحة تفاصيل البرومبت |

### 3.8 قواعد الـ API الموحّدة
- كل الردود JSON تمر عبر `success_response()` / `error_response()`.
- معالجة الأخطاء: `RequestValidationError` → 422 ببنية موحّدة، `Exception` → 500 مع `request_id`.
- حد المعدّل: 30 طلبًا/دقيقة للمستخدم (تفريغ: 5/دقيقة) عبر token bucket في الذاكرة.
- `security headers`: CSP، `X-Content-Type-Options: nosniff`، `Referrer-Policy`.

---

## 4. تدفق المستخدم (User Flow)

### 4.1 المسار الرئيسي — من الوصف إلى البرومبت

```
[افتح /]
     │
     ├─ جلسة سارية؟ ── نعم ──► /app
     │
     └─ لا
          ▼
   ┌──────────────────────────────────────────┐
   │  صفحة الدخول: "ما اسمك؟"                │
   │  [ حقل اسم المستخدم ] [ ⏎ دخول ]       │
   │  ✓ تحقق فوري: التوفر + الصيغة           │
   │  تلميح: "لا كلمة مرور — لا تُشارك اسمك" │
   └──────────────────────────────────────────┘
          ▼  (POST /api/auth/login)
   إنشاء المستخدم + الجلسة + كوكي 30 يومًا
          ▼
   ┌────────────────────────────────────────────────────────┐
   │  Composer — الخطوة 1: المصدر                           │
   │  [ ✍️ نص ]  [ 🎙️ صوت ]                                │
   │                                                        │
   │  ✍️ نص: textarea + عدّاد أحرف + كشف اللغة (عربي/إنجليزي) │
   │  🎙️ صوت: سحب وإفلات / نقر → شريط رفع + معاينة +       │
   │          waveform تقريبي + ⏱️ المدة + حجم              │
   │          ⚠️ "اقبلنا mp3, m4a, wav, webm, ogg — حتى 25MB"│
   └────────────────────────────────────────────────────────┘
          ▼
   ┌────────────────────────────────────────────────────────┐
   │  الخطوة 2: الأداة المستهدفة (بطاقات قابلة للنقر)       │
   │  [ChatGPT][Claude][Gemini][Midjourney][Cursor][عام]   │
   │  ← اختيار الأداة يغيّر الحقول النصية أدناه فورًا      │
   └────────────────────────────────────────────────────────┘
          ▼
   ┌────────────────────────────────────────────────────────┐
   │  الخطوة 3: الضبط الدقيق (يختلف حسب الأداة)             │
   │  النبرة: [احترافي|ودّي|تقني|إقناعي|أكاديمي]           │
   │  العمق: [مختصر|متوازن|عميق]                            │
   │  المخرجات: [Markdown|نص عادي|JSON]                      │
   │  "تعليمات إضافية": textarea اختياري                     │
   │  # قالب Midjourney: --ar --v --style --stylize        │
   │  # قالب Cursor: تفاصيل الملفات، قاعدة الكود           │
   └────────────────────────────────────────────────────────┘
          ▼
   [ ✨ أنشئ البرومبت ]
          ▼
   ══════════════ شاشة المعالجة (شريط مرحلة) ══════════════
   رفع → تطبيع → تفريغ Whisper → تلميع → كتابة GPT
   (SSE حيّ، أو تغذية راجعة نصية بسيطة مثل "عم نحلّل...")
          ▼
   ┌────────────────────────────────────────────────────────┐
   │  النتيجة                                                 │
   │  ┌── نظرة عامة ( tabs ):[البرومبت][التحليل][المخرجات] ─┐│
   │  │  <pre> قابل للتحديد + syntax highlight              ││
   │  │ شريط chips لكل قسم: [الدور][السياق][المهمة][القيود]…  ││
   │  └────────────────────────────────────────────────────┘│
   │  [📋 نسخ البرومبت]  [♻️ أعد التوليد]  [🗂 احفظ] ✅    │
   │  [📤 تصدير .md]  [🔄 جمّل]  [✏️ عدّل يدويًا]           │
   │  ⚡ تحذير: "لاحظ: كل نموذج له quirks — راجع قبل الإرسال"│
   └────────────────────────────────────────────────────────┘
          ▼
   (حفظ تلقائي في المكتبة — status = ready)
          ▼
   [ عرض المكتبة ] ──► البحث + الفلاتر + شبكة + نسخ سريع
```

### 4.2 المسار الصوتي بالتفصيل

```
اختيار ملف
   → تحقق من النوع/الحجم (فوري، بلا خادم)
   → POST /api/uploads/audio
   → شريط تقدّم (XHR upload progress)
   → POST /api/transcribe  →  job_id
   → SSE /api/jobs/{id}/stream
        stage=normalizing  "جاري تطبيع الصوت…"
        stage=transcribing "جاري تفريغ الصوت… (Whisper)"
        stage=polishing    "جاري تنظيف النص…"
        progress 0→100
   → النص المفرّغ يظهر في textarea (قابل للتعديل!)
   → ⚠️ "راجع النص المفرّغ قبل التوليد — الأفضل أن يكون الوصف نصًا واضحًا"
   → مُتابعة بنفس المسار النصي من الخطوة 2
```

### 4.3 إعادة التوليد (Refine Loop)

```
[♻️ أعد التوليد] → نافذة صغيرة:
   "ما الذي تريد تغييره؟"
   ☐ أضف أمثلة Few-shot
   ☐ اجعله أقصر بـ 40%
   ☐ أضف متغيّرات [{{project_name}}]
   ☐ ركّز على قيد محدّد (مثال: لا جمل marketing)
   [textarea: تعليمات حرة]
        ▼
   POST /api/prompts/{id}/regenerate
        ▼
   Version N+1 تُحفظ ← المستخدم يبدّل بين النسخ (chips: v1 v2 v3)
```

### 4.4 حالات الحافة

| الحالة | السلوك |
|---|---|
| اسم مستخدم مكرر | رسالة "هذا الاسم محجوز، جرّب غيره" (لا تكشف إن كان مسجّلًا — لكن ندعم الدخول به!) |
| ملف صوتي تالف/مفقود codec | رسالة واضحة + اقتراح التحويل لـ mp3 |
| ملف > 25MB | رفض فوري + نص: "قسّم المقطع أو اضغط المسجّل" |
| صوت > 10 دقائق | تحذير + عرض التكلفة التقديرية + خيار "متابعة" |
| فشل Whisper | عرض آخر مقتطف قبل الفشل + زر "أدخل النص يدويًا" |
| فشل OpenAI | `error_message` محفوظ + زر "إعادة المحاولة" (3 محاولات مع backoff) |
| انقطاع الشبكة أثناء التوليد | يُحفظ كـ `status=error` ويظهر ✕ قابل لإعادة المحاولة |
| لا يوجد مفتاح OpenAI | شاشة إعداد واضحة في `/settings` مع شرح لطريقة الحصول على المفتاح |
| كوكي منتهٍ | redirect إلى `/login` مع رسالة "انتهت الجلسة" |
| لوحة فراغ (0 برومبتات) | Empty state بثلاثة أمثلة جاهزة بضغطة واحدة |

---

## 5. هندسة البرومبتات — كيف نولّد؟ (ملخص تنفيذي)

> الشرح الكامل في المرحلة 3؛ هنا المخطط العام.

```
                     ┌─────────────────────────┐
  الوصف الخام ──────►│ normalizer (cheap LLM)  │  نص واحد → نص نظيف
  (نص/صوت)          │ gpt-4o-mini             │  لغة، صوت، نبرة، غموض
                     └───────────┬─────────────┘
                                 ▼
                     ┌─────────────────────────┐
                     │ classifier              │  هل الوصف غامض؟
                     │ gpt-4o-mini             │  هل ينقصه سياق؟
                     └───────────┬─────────────┘
                       نعم │              │ لا
                     ┌─────▼─────┐   ┌────▼─────┐
                     │ clarifier │   │ builder  │ gpt-4o
                     │ سؤال ذكي  │   │ tool_    │ (أو نموذج استدلالي)
                     │ واحد فقط  │   │ profile  │
                     └─────┬─────┘   └────┬─────┘
                           └──────┬───────┘
                                  ▼
                     ┌─────────────────────────┐
                     │ validator               │  هل يحتوي كل الأقسام؟
                     │ (regex + LLM نقدي)      │  هل الطول أقل من الحد؟
                     └───────────┬─────────────┘
                                 ▼
                     ┌─────────────────────────┐
                     │ formatter               │  تسميات، markdown،
                     │                        │  variables قابلة للملء
                     └─────────────────────────┘
```

### أقسام البرومبت النهائي (Canonical Structure)

```markdown
# 🎯 الدور (Role)
أنت [خبير متخصص في ...] ...

# 📌 السياق (Context)
- الجمهور المستهدف: ...
- المنصة: ...
- القيد الزمني: ...

# 🔧 المهمة (Task)
1. ...
2. ...
3. ...

# 📐 المتطلبات والقيود (Constraints)
- لا تتجاوز ...
- يجب أن ...

# 📤 صيغة المخرجات (Output Format)
[جدول بأعمدة X | Y | Z] أو [JSON schema] ...

# 💡 أمثلة (Few-shot)
مثال 1 → مثال 2 →

# 🚫 تجنّب (Negative)
- لا تستخدم ... / لا تخترع ...

# 🔤 المتغيّرات (Variables — املأها قبل الاستخدام)
{{project_name}} = ...
{{tone}} = ...
```

### `tool_profiles.py` — الفروق بين الأدوات

| الأداة | الطول المثالي | الأقسام الإضافية | quirks يجب مراعاتها |
|---|---|---|---|
| **ChatGPT** | 150–400 كلمة | Instructions متدرجة، "افترض…" | يحب Markdown، dislikes "step by step" المتكرر، أعطه examples |
| **Claude** | 300–700 كلمة | XML tags (`<context>`)، تفكير متدرّج | يستجيب ممتازًا للـ XML، ويدعم Artifacts للملفات |
| **Gemini** | 100–300 كلمة | Google-flavored، تمرير تدرج | يفضل الإيجاز، استخدم bullet صارم |
| **Midjourney** | 30–80 كلمة فقط | `--ar --v --style --stylize --chaos --no` | ⚠️ **لا يحب النص!** يُولَّد كـ "visual prompt" فقط، keywords لا جمل، language في `--ar`، يحب الأرقام للترتيب |
| **Cursor** | 200–500 كلمة | بنية كود، file paths، tech stack | أَذِن صراحةً: "احترم الأنماط الموجودة في المستودع"، وأعطِ أمثلة كود |
| **عام** | 200–400 كلمة | البنية الأساسية فقط | محايد يصلح لأي نموذج |

### Few-shot examples جاهزة (3 لكل أداة) في `prompts_bank.py` — تُحقن كـ messages `user`→`assistant` لتثبيت الشكل.

### حواجز الجودة (Quality Gates)
1. الحد الأدنى للأطوال (يختلف لكل أداة) — يمنع البرومبتات الهشّة.
2. فحص إلزامي لوجود كل الأقسام الستة الأساسية.
3. **اكتشاف البرومبت الرديء**: إذا طوّل النموذج أو أضاف حشوًا → إعادة توليد تلقائية مرة واحدة مع تعليمات "أكثر إحكامًا".
4. تقييم ذاتي 0–100 (سهولة، وضوح، قابلية التنفيذ) يُعرض كشارة في المكتبة.

---

## 6. خطة التنفيذ على 6 مراحل

### 🟢 المرحلة 1 — التأسيس والدخول (الأساس)
**الهدف:** تطبيق يعمل بـ `uvicorn` + قاعدة بيانات + مستخدم يدخل باسمه فقط.
- [ ] تهيئة المشروع: `requirements.txt`, `.env.example`, `.gitignore`, هيكل المجلدات
- [ ] `config.py` + قراءة `OPENAI_API_KEY`, `DATABASE_URL`, `SESSION_TTL_DAYS`
- [ ] `database.py`: SQLite + WAL + `init_db()` + Alembic-lite (أو `create_all` للبداية)
- [ ] `models.py`: `users`, `sessions` فقط في هذه المرحلة
- [ ] `security.py`: توليد token، هاشد sha256، كوكي HttpOnly، `get_current_user`
- [ ] `routers/auth.py`: `check`, `login`, `logout`, `me`, `refresh`
- [ ] `templates/base.html` + `login.html` مع Tailwind (CDN في التطوير) و Alpine.js
- [ ] صفحة `/app` فارغة لكن محمية (middleware يحوّل غير المسجّل لـ `/login`)
- [ ] Logging أساسي (لوحة مفاتيح الدخول + الأخطاء)

**معيار الإنجاز:** `python run.py` → فتح `http://localhost:8000` → إدخال اسم → الوصول لـ `/app`. `curl` بدون كوكي على `/api/auth/me` يرجع 401.

**المخاطر:** اختيار بين كوكي موقّع (itsdangerous) و`opaque token` في DB — **نختار opaque + hash** لقابلية الإلغاء الفوري.

---

### 🟡 المرحلة 2 — الواجهة والمكتبة (UIs)
**الهدف:** واجهة جميلة RTL/responsive + CRUD كامل على المكتبة (ببيانات وهمية).
- [ ] تثبيت Tailwind عبر CLI (وليس CDN) + ملف `input.css` + `app.css` مخصّص
- [ ] تنزيل Alpine.js محليًا إلى `static/vendor/`
- [ ] `static/js/app.js`: Alpine stores (`auth`, `toast`, `theme`, `composer`, `library`)
- [ ] `composer.html`: اختيار المصدر (نص/صوت)، اختيار الأداة كبطاقات، حقول الضبط (مربّاة بـ Alpine)
- [ ] `library.html`: Grid/Table toggle، بحث debounce، فلاتر (أداة/مفضّلة/مؤرشف)، pagination، empty states
- [ ] `partials/_prompt_card.html`: معاينة، أزرار نسخ/مفضّلة/حذف، badges الأداة والنبرة
- [ ] `models.py`: إضافة `prompts` (بكل الأعمدة) + FTS5
- [ ] `routers/prompts.py`: `GET /api/prompts` (مع فلاتر وترقيم), `GET/PATCH/DELETE /api/prompts/{id}`
- [ ] Toast + تأكيد الحذف (Alpine)
- [ ] دعم `dir="rtl"` كامل + خط عربي (Cairo/Tajawal) + Dark mode

**معيار الإنجاز:** زر "مثال تجريبي" يزرع 5 برومبتات وهمية؛ البحث والفلاتر تعمل؛ الحذف والتعديل والمفضّلة تعمل من الواجهة.

---

### 🔵 المرحلة 3 — محرك البرومبتات (نص)
**الهدف:** من نص خام إلى برومبت احترافي — قلب المنتج.
- [ ] `openai_client.py`: غلاف واحد لـ Chat + Whisper، timeout 60s، retry 3× مع exponential backoff، تسجيل `usage`
- [ ] `tool_profiles.py`: تعريف الأدوات الست كاملة (أقسام، حدود، quirks، أمثلة)
- [ ] `prompts_bank.py`: 3 few-shot examples لكل أداة + القوالب العامة الستة
- [ ] `prompt_engine.py`: 
  - `normalize(text, lang)` 
  - `classify_intent(text)` → `{tool_hint, is_ambiguous, missing:[]}`
  - `build(source, profile, options)` → البرومبت النهائي
  - `structured_output()` → إرجاع JSON حقيقي عبر `response_format="json_object"` عندما يكون `output_format=json`
- [ ] `refine.py`: التحقق من الأقسام، الحد الأدنى للطول، إعادة توليد واحدة عند الفشل، `quality_score`
- [ ] `POST /api/prompts/generate` كامل + `structured_json`
- [ ] لوحة النتائج: tabs (برومبت / تحليل / متغيّرات)، نسخ بضغطة، highlight، تحذير quirks
- [ ] تسجيل `usage_events` لكل عملية
- [ ] **اختبار يدوي:** 5 أوصاف نصية مختلفة × 6 أدوات = 30 حالة، تقييم يدوي للجودة

**معيار الإنجاز:** 80%+ من حالات الاختبار تُنتج برومبت يحتوي كل الأقسام الستة ويبدو جاهزًا للنسخ بلا تعديل.

---

### 🟣 المرحلة 4 — خط أنابيب الصوت
**الهدف:** من ملف صوتي إلى برومبت — المسار الكامل.
- [ ] اختيار وتوثيق FFmpeg: تثبيت + `ffprobe` في PATH، فحص عند الإقلاع (`/api/health`)
- [ ] `audio.py`: التحقق بالـ magic bytes، `ffprobe` للمدة، التحويل إلى `mp3 16k mono 64k`، رفع صيغ
- [ ] `POST /api/uploads/audio`: رفع متعدد الأجزاء مبسّط، حد 25MB، كتابة آمنة (uuid)، فهرسة SHA256
- [ ] `transcription.py`: Whisper `verbose_json` + language detect + segments
- [ ] تقطيع الملفات > 10 دقائق (5 دقائق + 2 ثانية overlap) ودمج النتائج
- [ ] تنظيف النص: حذف filler، تصحيح الترقيم، كشف تكرار مفرط (hallucination guard: "شكراً شكراً شكراً")
- [ ] نظام المهام `jobs` + **SSE** لشريط التقدّم بمراحل واضحة
- [ ] واجهة الرفع: سحب وإفلات، معاينة صوتية، waveform تقريبي، حالة المدة، زر "تراجع واستخدم mp3"
- [ ] حقل النص المفرّغ قابل للتعديل + تحذير "راجع قبل التوليد"
- [ ] TTL التنظيف: `cleanup_uploads.py` + `/api/uploads/{id}` DELETE

**معيار الإنجاز:** ملفات 30 ثانية و3 دقائق و12 دقيقة تُفرَّغ بنجاح، والمستخدم يقرأ نصًا مفهومًا ويولّد منه برومبتًا.

---

### 🟠 المرحلة 5 — التكرارات والإتقان
**الهدف:** تحويل الأداة من "يولّد مرة" إلى "أداة عمل يومية".
- [ ] `prompt_versions` + `POST /regenerate` مع تعليمات دلتا
- [ ] شريط إصدارات (v1 v2 v3) + استرجاع نسخة + مقارنة جنبًا لجنب
- [ ] Clarifier flow: عند الغموض اطرح سؤالًا واحدًا ذكيًا (chips جاهزة)
- [ ] تعديل يدوي للبرومبت الناتج + "حفظ المسودة"
- [ ] "جمّل النص" منفصل (improver) لأوصاف رديئة الصياغة
- [ ] وسوم (tags) + فلاتر + autocomplete
- [ ] نسخ متقدم: نسخ النص، نسخ Markdown، نسخ JSON، نسخ مع ترويسة "تم التوليد بـ PromptCraft"
- [ ] `share` برابط قراءة فقط + `export` (md/txt/json) + تصدير المكتبة كاملة
- [ ] لوحة الإحصاءات: عدد البرومبتات، توزيع الأدوات، الأكثر نسخًا، توفير الوقت التقديري
- [ ] اختصارات لوحة المفاتيح (`/` تركيز البحث، `Ctrl+Enter` توليد، `Esc` إغلاق)
- [ ] اختبارات آلية: `test_auth`, `test_prompts_isolation`, `test_prompt_engine`, `test_uploads` (pytest + httpx ASGI)
- [ ] ترقيد Rate limiting لكل مستخدم + تنبيه التكلفة

**معيار الإنجاز:** دورة "توليد → نقد → إعادة توليد → اعتماد" كاملة داخل الواجهة، مع عزل بيانات مُختبَر ومكتبة قابلة للتصدير.

---

### 🔴 المرحلة 6 — التصليب والتسليم
**الهدف:** جاهز للاستخدام الحقيقي واليومي.
- [ ] مراجعة أمنية: sanitization للمخرجات (بلا `innerHTML` خام)، رفع الملفات، التحقق من الحجم، rate limits، security headers، CORS مغلق
- [ ] تنقية سرية مفتاح OpenAI: تشفير Fernet + `.env` لا يُرفع أبدًا + `.env.example` فقط
- [ ] Docker: `Dockerfile` (python:3.12-slim + ffmpeg) + `docker-compose.yml` مع volume mounts
- [ ] السكربتات: `seed_profiles.py`, `backup_db.py` (نسخة يومية)، `cleanup_uploads.py` (cron)
- [ ] مراقبة: `/api/health` يفحص DB + FFmpeg + OpenAI، صفحة `/status` بسيطة
- [ ] التوثيق في README: التثبيت، المتغيرات البيئية، FFmpeg، النشر، استكشاف الأخطاء
- [ ] تحسين التكلفة: تصنيف بالنموذج الصغير، تخزين مؤقت fingerprint→prompt لتكرار نفس الوصف، batching
- [ ] UX polish: حالات تحميل وهمية واقعية، أخطاء بلغة عربية مفهومة، دعم RTL/LTR
- [ ] اختبار حمل مبسّط: 50 طلبًا متوازيًا على `/api/prompts`
- [ ] تسليم: نسخة تشغيل محلي + نسخة Docker، وثلاثة أمثلة برومبتات موثّقة لكل أداة

**معيار الإنجاز:** `docker compose up` → تنتهي الأداة جاهزة للاستخدام؛ لا أخطاء 5xx في 100 طلب متتالٍ؛ المستخدم يجد ملفاته محفوظة بعد إعادة التشغيل.

---

## 7. خريطة الاعتماديات بين المراحل

```
M1 (تأسيس + دخول)
 ├──▶ M2 (واجهة + مكتبة CRUD)
 │      └──▶ M3 (محرك البرومبتات النصي)
 │              ├──▶ M4 (خط الصوت)
 │              │      └──▶ M5 (التكرارات + إتقان + اختبارات)
 │              └──▶ M5
 └──▶ M6 (تصليب + تسليم)  [يعتمد على الكل]
```

---

## 8. قرارات معمارية مفتّحة

| القرار | الخيار المبدئي | السبب | يُراجَع في |
|---|---|---|---|
| مصادقة بلا كلمة مرور | opaque token + hash في DB + rate limit | إلغاء فوري، بسيط، صعب التعداد | M6 |
| تخزين المفاتيح | Fernet في SQLite | يدعم BYOK ومفتاح السيرفر معًا | M6 |
| تشغيل المهام | BackgroundTasks داخل العملية (v1) | بلا Redis؛ كافٍ لـ 100 مستخدم | M5 (إن تجاوز 500) |
| التقدّم اللحظي | SSE مع polling احتياطي | UX حيّ بلا تعقيد WebSocket | M4 |
| تخزين الملفات | محلي `data/uploads` + TTL 24 ساعة | بساطة، بلا S3 | M6 |
| محرك القوالب | ملفات `.md` في `prompts_specs/` | تعديل القوالب بلا كود | M3 |
| نموذج التوليد | `gpt-4o` للكتابة، `gpt-4o-mini` للتصنيف | جودة/تكلفة | M6 |

---

## 9. الميزات المستقبلية (خارج النطاق الحالي)

- 🎨 معرض برومبتات عام (opt-in) مع إعجابات وإحصاء نسخ إجمالي
- 🧩 قوالب برومبت قابلة للحفظ ومشاركتها داخل الفريق
- 🔌 تصدير كـ Claude Projects / ChatGPT Custom GPTs
- 🌍 توليد متعدد اللغات (ترجمة تلقائية للبرومبت)
- 📊 A/B testing بين نسختي برومبت مع قياس جودة المخرجات
- 🤖 GPT Critic يقيس برومبتات المستخدم ويقترح تحسينات
- 🔗 Zapier/n8n/webhook لإرسال البرومبت لأنظمة أخرى
- 🧬 نسخة Electron / تطبيق PWA للعمل دون اتصال

---

## 10. سجل القرارات (ADR — مختصر)

| # | القرار | البدائل المرفوضة |
|---|---|---|
| 1 | تسجيل دخول بالاسم فقط | كلمات مرور، OAuth، Magic link (يحتاج بريد) |
| 2 | SQLite | Postgres (تعقيد بلا فائدة في المقياس الحالي) |
| 3 | Jinja2 + Alpine بدل React | بنية أهدأ بلا build step، كافٍ تمامًا للحاجة |
| 4 | Tailwind عبر CLI بدل CDN | أسرع في الإنتاج، حجم أصغر |
| 5 | SSE بدل WebSocket | الاتجاه واحد يكفي، وإعادة الاتصال أسهل |
| 6 | `structured_json` + نص مطبَّع بدل JSON فقط | النص جاهز للنسخ، وJSON للقراءة الآلية |
| 7 | أداة = profile واحد | جدول أدوات في DB (لا نحتاج إدارة ديناميكية الآن) |

---

## 11. سجل التسليم

| التاريخ | المرحلة | ما أُنجز | الحالة |
|---|---|---|---|
| — | — | الخطة (هذا المستند) | ✅ |
| — | 1 | التأسيس والدخول | ⬜ |
| — | 2 | الواجهة والمكتبة | ⬜ |
| — | 3 | محرك البرومبتات | ⬜ |
| — | 4 | خط الصوت | ⬜ |
| — | 5 | التكرارات والإتقان | ⬜ |
| — | 6 | التصليب والتسليم | ⬜ |
