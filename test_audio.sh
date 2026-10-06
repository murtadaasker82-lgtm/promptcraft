#!/usr/bin/env bash
# ==========================================================
#  PromptCraft — اختبار سريع لواجهة تفريغ الصوت
#  POST /api/transcribe  (multipart/form-data)
# ==========================================================
#
#  الاستخدام:
#     bash test_audio.sh                    # يولّد ملف WAV تجريبيًا تلقائيًا
#     bash test_audio.sh path/to/audio.mp3  # يستخدم ملفك
#
#  متغيرات اختيارية:
#     BASE_URL     (افتراضي: http://localhost:8000)
#     PC_USERNAME  (افتراضي: murad)
#
#  المتطلبات: curl + (python اختياري)
# ==========================================================

set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
# ملاحظة: نستخدم PC_USERNAME وليس USERNAME — الأخير متغير نظام على ويندوز
PC_USERNAME="${PC_USERNAME:-murad}"
COOKIE_JAR="$(mktemp -t pc-cookies.XXXXXX)"
GENERATED_AUDIO=""

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

# ---- اكتشاف مفسّر بايثون (اختياري) ----
PY_BIN=""
for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys' >/dev/null 2>&1; then
            PY_BIN="$candidate"
            break
        fi
    fi
done

say()  { printf "${CYAN}▶${NC} %s\n" "$1"; }
ok()   { printf "${GREEN}✔${NC} %s\n" "$1"; }
bad()  { printf "${RED}✘${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}!${NC} %s\n" "$1"; }

cleanup() {
    rm -f "$COOKIE_JAR"
    [ -n "$GENERATED_AUDIO" ] && rm -f "$GENERATED_AUDIO"
    return 0
}
trap cleanup EXIT

# ---------- 1) فحص الصحة ----------
say "فحص الخادم على $BASE_URL"
HEALTH=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/health" 2>/dev/null)
if [ "$HEALTH" != "200" ]; then
    bad "الخادم لا يستجيب ($HEALTH). شغّله أولًا: uvicorn app.main:app --reload"
    exit 1
fi
ok "الخادم يعمل"

# ---------- 2) تسجيل الدخول ----------
say "تسجيل الدخول باسم: $PC_USERNAME"
LOGIN=$(curl -s -c "$COOKIE_JAR" -X POST "$BASE_URL/api/auth/login" \
        -H 'Content-Type: application/json' \
        -d "{\"username\": \"$PC_USERNAME\"}")

case "$LOGIN" in
    *'"success":true'*|*'"success": true'*) ok "تم تسجيل الدخول" ;;
    *) bad "فشل تسجيل الدخول: $LOGIN"; exit 1 ;;
esac

TOKEN=$(awk '$6 == "session_token" { print $7 }' "$COOKIE_JAR" 2>/dev/null | tail -1)
if [ -n "$TOKEN" ]; then
    ok "كوكي session_token محفوظ (${TOKEN:0:10}…)"
else
    warn "لم يُحفظ كوكي session_token — سيُرجع 401"
fi

# ---------- 3) تجهيز ملف صوتي ----------
make_wav_python() {
    "$PY_BIN" - "$1" <<'PY'
import math, struct, sys, wave
path = sys.argv[1]
rate, seconds, freq = 16000, 3, 440.0
with wave.open(path, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    frames = bytearray()
    for i in range(rate * seconds):
        frames += struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
    w.writeframes(bytes(frames))
PY
}

# بديل بدون بايثون: ملف WAV صامت 8-bit / 8kHz لمدة 0.5 ثانية
make_wav_shell() {
    local out="$1"
    local data_size=4000
    local riff_size=$((36 + data_size))
    # RIFF header (44 بايت)
    printf 'RIFF' > "$out"
    printf "$(printf '\\x%02x\\x%02x\\x%00\\x00' \
        $((riff_size % 256)) $((riff_size / 256)))" >> "$out"
    printf 'WAVEfmt ' >> "$out"
    printf "$(printf '\\x10\\x00\\x00\\x00\\x01\\x00\\x01\\x00')" >> "$out"
    printf "$(printf '\\x40\\x1f\\x00\\x00')" >> "$out"   # sample rate 8000
    printf "$(printf '\\x40\\x1f\\x00\\x00')" >> "$out"   # byte rate 8000
    printf "$(printf '\\x01\\x00\\x08\\x00')" >> "$out"   # block align 1, 8 bits
    printf 'data' >> "$out"
    printf "$(printf '\\x%02x\\x%02x\\x%00\\x00' \
        $((data_size % 256)) $((data_size / 256)))" >> "$out"
    head -c "$data_size" /dev/zero | tr '\000' '\200' >> "$out"
}

if [ -z "${1:-}" ]; then
    say "لم يُحدَّد ملف — توليد WAV تجريبي"
    AUDIO_FILE="$PWD/.pc-test-sample.wav"
    if [ -n "$PY_BIN" ]; then
        make_wav_python "$AUDIO_FILE" && ok "تم إنشاء: $AUDIO_FILE (باستخدام $PY_BIN)"
    else
        warn "بايثون غير متوفر — نولّد WAV صامتًا بطريقة بديلة"
        make_wav_shell "$AUDIO_FILE" && ok "تم إنشاء: $AUDIO_FILE"
    fi
    GENERATED_AUDIO="$AUDIO_FILE"
elif [ ! -f "$1" ]; then
    bad "الملف غير موجود: $1"
    exit 1
else
    AUDIO_FILE="$1"
    ok "استخدام الملف: $AUDIO_FILE"
fi

SIZE=$(wc -c < "$AUDIO_FILE" 2>/dev/null | tr -d ' ')
say "حجم الملف: ${SIZE:-0} بايت"

# ---------- 4) طلب التفريغ ----------
say "POST $BASE_URL/api/transcribe"
if [ -n "$TOKEN" ]; then
    RESPONSE=$(curl -s -w '\n__STATUS__%{http_code}' \
        -X POST "$BASE_URL/api/transcribe" \
        -H "Cookie: session_token=$TOKEN" \
        -F "file=@$AUDIO_FILE")
else
    RESPONSE=$(curl -s -w '\n__STATUS__%{http_code}' \
        -X POST "$BASE_URL/api/transcribe" \
        -b "$COOKIE_JAR" \
        -F "file=@$AUDIO_FILE")
fi

STATUS=$(printf '%s' "$RESPONSE" | tail -1 | sed 's/.*__STATUS__//')
BODY=$(printf '%s' "$RESPONSE" | sed '$d')
echo

pretty() {
    if [ -n "$PY_BIN" ]; then
        printf '%s' "$BODY" | "$PY_BIN" -c "
import json, sys
raw = sys.stdin.read().strip()
try:
    d = json.loads(raw)
except Exception:
    print('  الرد:', raw[:400]); raise SystemExit
if 'text' in d:
    print('  النص   :', (d.get('text') or '(فارغ)')[:300])
    print('  اللغة  :', d.get('language'))
    print('  النموذج:', d.get('model'), '| تجريبي:', d.get('mock'))
    print('  الحجم  :', d.get('size_bytes'), 'بايت')
    print('  المدة  :', d.get('duration_estimate_sec'), 'ثانية (تقديري)')
else:
    print('  التفاصيل:', d.get('detail'))
"
    else
        printf '  الرد: %s\n' "$(printf '%s' "$BODY" | head -c 400)"
    fi
}

if [ "$STATUS" = "200" ]; then
    ok "التفريغ نجح (HTTP 200)"
    pretty
    exit 0
fi

bad "فشل التفريغ (HTTP ${STATUS:-غير معروف})"
pretty
case "$STATUS" in
    401) bad "الكوكي غير صالح — تحقق من ملف الكوكيز" ;;
    413) bad "الملف أكبر من الحد المسموح" ;;
    415) bad "صيغة غير مدعومة (المقبولة: mp3, mp4, m4a, wav, webm, ogg, flac)" ;;
    500) bad "خطأ داخلي — راجع سجل الخادم" ;;
    502) bad "فشل الاتصال بـ OpenAI — تحقق من المفتاح والإنترنت" ;;
    503) bad "OPENAI_API_KEY غير مضبوط في .env — شغّل الخادم بعد إضافته" ;;
    000) bad "تعذّر الاتصال بالخادم — تأكد أنه يعمل على $BASE_URL" ;;
esac
exit 1
