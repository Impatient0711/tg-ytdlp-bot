#!/bin/bash
# ============================================================================
#  tg-ytdlp-bot · entrypoint برای Railway / Docker
#  کارهایی که انجام می‌دهد:
#   ۱) چک کردن متغیرهای اجباری (با پیام واضح، نه خطای مبهم)
#   ۲) آماده‌کردن مسیر دادهٔ پایدار (Volume) و لینک‌کردن کاربران/کوکی/کش به آن
#   ۳) نوشتن کوکی از متغیر محیطی (اگر COOKIES_CONTENT داده باشید)
#   ۴) بالا آوردن PO Token provider (اگر YOUTUBE_POT_ENABLED=true باشد)
#   ۵) بالا آوردن سرور سلامت روی PORT (اگر Railway پورت داده باشد)
#   ۶) اجرای ربات و انتقال سیگنال‌های خاموشی به همه
# ============================================================================
set -uo pipefail

APP_DIR="${APP_DIR:-/app}"
cd "$APP_DIR" || exit 1

log() { printf '%s\n' "$*"; }

# ── منطقهٔ زمانی ────────────────────────────────────────────────────────────
if [ -n "${TZ:-}" ] && [ ! -e "/usr/share/zoneinfo/${TZ}" ]; then
    log "⚠️  منطقهٔ زمانی «${TZ}» پیدا نشد ⇒ UTC استفاده می‌شود."
    TZ="UTC"
fi
export TZ="${TZ:-UTC}"

# ── ۱) متغیرهای اجباری ─────────────────────────────────────────────────────
missing=""
for name in BOT_TOKEN API_ID API_HASH; do
    value="$(printenv "$name" 2>/dev/null || true)"
    [ -n "${value// /}" ] || missing="$missing $name"
done
if [ -n "$missing" ]; then
    log ""
    log "❌ این متغیرها ست نشده‌اند:$missing"
    log "👉 Railway → سرویس → Variables → اضافه کنید و دوباره Deploy کنید."
    log "   • BOT_TOKEN  ← از @BotFather"
    log "   • API_ID / API_HASH ← از my.telegram.org"
    log "❌ Missing required variables:$missing"
    log "👉 Add them in Railway → your service → Variables, then redeploy."
    log ""
    exit 1
fi

# ── ۲) مسیر دادهٔ پایدار ────────────────────────────────────────────────────
DATA_DIR="${DATA_DIR:-${RAILWAY_VOLUME_MOUNT_PATH:-}}"
if [ -z "$DATA_DIR" ] && [ -d /data ] && [ -w /data ]; then
    DATA_DIR="/data"
fi
if [ -z "$DATA_DIR" ]; then
    DATA_DIR="$APP_DIR"
fi
mkdir -p "$DATA_DIR" 2>/dev/null
if [ ! -w "$DATA_DIR" ]; then
    log "⚠️  «$DATA_DIR» قابل‌نوشتن نیست ⇒ روی /app ادامه می‌دهیم (داده‌ها با هر دیپلوی پاک می‌شوند)."
    DATA_DIR="$APP_DIR"
fi
# «پایدار» یعنی واقعاً یک Volume روی این مسیر مانت شده باشد (نه فقط پوشهٔ داخل کانتینر)
is_mount() {
    [ -f /proc/mounts ] || return 1
    awk -v p="$1" '$2==p {found=1} END{exit !found}' /proc/mounts
}
PERSIST=0
if [ "$DATA_DIR" != "$APP_DIR" ] && is_mount "$DATA_DIR"; then
    PERSIST=1
fi
export DATA_DIR

free_mb() {  # فضایِ آزادِ (مگابایت) فایل‌سیستمِ یک مسیر
    df -Pm "$1" 2>/dev/null | awk 'NR==2 {print int($4)}'
}

persist_dir() {  # $1 = مسیر نسبی داخل /app (مثل users)
    local src="$APP_DIR/$1" dst="$DATA_DIR/$(basename "$1")"
    mkdir -p "$dst" 2>/dev/null
    if [ -L "$src" ]; then
        ln -sfn "$dst" "$src"
    elif [ -d "$src" ]; then
        if [ -n "$(ls -A "$src" 2>/dev/null)" ]; then
            cp -an "$src/." "$dst/" 2>/dev/null || true
        fi
        rm -rf "$src"
        ln -sfn "$dst" "$src"
    else
        ln -sfn "$dst" "$src"
    fi
}

persist_file() {  # $1 = مسیر نسبی  $2 = مقدار اولیه
    local src="$APP_DIR/$1" dst="$DATA_DIR/$(basename "$1")" seed="${2:-}"
    if [ ! -s "$dst" ]; then
        mkdir -p "$(dirname "$dst")" 2>/dev/null
        printf '%s' "$seed" > "$dst" 2>/dev/null || true
    fi
    if [ -L "$src" ]; then
        ln -sfn "$dst" "$src"
    else
        rm -f "$src" 2>/dev/null
        ln -sfn "$dst" "$src"
    fi
}

link_to_data() {  # فقط لینک (بدون ساختن فایل) — برای فایل‌هایی که خود برنامه می‌سازد
    local src="$APP_DIR/$1" dst="$DATA_DIR/$(basename "$1")"
    if [ -L "$src" ]; then
        ln -sfn "$dst" "$src"
    else
        rm -f "$src" 2>/dev/null
        ln -sfn "$dst" "$src"
    fi
}

mkdir -p "$DATA_DIR/users"
if [ "$DATA_DIR" != "$APP_DIR" ]; then
    # ── دانلودها روی کدام دیسک؟ ─────────────────────────────────────────────
    # فایل‌های دانلودی **موقتی**‌اند (بعدِ آپلود به تلگرام پاک می‌شوند)، ولی والیومِ
    # ریلوی اغلب کوچک است (پیش‌فرضِ ۵۰۰MB و بزرگ‌کردنش هم سقف دارد) درحالی‌که دیسکِ
    # خودِ کانتینر گیگابایت‌ها جایِ آزاد دارد. اگر users/ روی والیومِ کوچک باشد، هر
    # دانلودِ چندصد‌مگابایتی با «❌ فضای دیسک کافی نیست» رد می‌شود.
    # پس: دادهٔ **ماندگار** (session/کوکی/کش/لینک‌های فایل/لاگ) روی والیوم،
    #     دانلودهای **موقتی** روی دیسکِ بزرگ‌تر.
    # رفتارِ قدیم (users روی والیوم، برای ماندنِ .part بین دیپلوی‌ها): PERSIST_USERS=1
    vol_free=$(free_mb "$DATA_DIR")
    app_free=$(free_mb "$APP_DIR")
    users_on_volume=1
    case "$(printf '%s' "${PERSIST_USERS:-}" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on)  users_on_volume=1 ;;
        0|false|no|off) users_on_volume=0 ;;
        *)
            if [ "${vol_free:-0}" -lt 4096 ] && [ "${app_free:-0}" -gt $(( 2 * ${vol_free:-0} + 1024 )) ]; then
                users_on_volume=0
            fi
            ;;
    esac
    if [ "$users_on_volume" = "1" ]; then
        persist_dir "users"
        log "📁 دانلودها روی والیوم: $APP_DIR/users → $DATA_DIR/users (آزاد: ${vol_free:-?}MB)"
    else
        [ -L "$APP_DIR/users" ] && rm -f "$APP_DIR/users"
        mkdir -p "$APP_DIR/users"
        if [ "$PERSIST" = "1" ] && [ -d "$DATA_DIR/users" ]; then
            old_mb=$(du -sm "$DATA_DIR/users" 2>/dev/null | awk '{print int($1)}')
            rm -rf "$DATA_DIR/users" 2>/dev/null || true
            log "🧹 ${old_mb:-0}MB ماندهٔ دانلود از والیوم پاک شد (users/ موقتی است)"
        fi
        log "📁 دانلودها روی دیسکِ کانتینر: $APP_DIR/users (آزاد: ${app_free:-?}MB) — والیومِ ${vol_free:-?}MB فقط برای دادهٔ ماندگار"
    fi
    link_to_data "magic.session"
    persist_file "dump.json" "{}"
    persist_file "TXT/cookie.txt" ""
    persist_file "bot.log" ""
    if [ "$PERSIST" = "1" ]; then
        log "📦 دادهٔ پایدار روی «$DATA_DIR» ✅ (Volume شناسایی شد)"
    else
        log "⚠️  «$DATA_DIR» یک Volume نیست — کاربران/کوکی‌ها با هر دیپلوی پاک می‌شوند (در Railway مسیر /data را Volume کنید)."
    fi
else
    rm -f "$APP_DIR/bot.log" 2>/dev/null
    ln -sfn /dev/null "$APP_DIR/bot.log" 2>/dev/null || true
    log "⚠️  Volume وصل نیست — کاربران/کوکی‌ها با هر دیپلوی پاک می‌شوند."
fi

# ── ۳) کوکی از متغیر محیطی ─────────────────────────────────────────────────
write_cookie_seed() {
    local content="$1"
    case "$content" in
        base64:*) content="$(printf '%s' "${content#base64:}" | base64 -d 2>/dev/null || true)" ;;
    esac
    [ -n "$content" ] || return 0
    printf '%s\n' "$content" > "$DATA_DIR/cookie.txt" 2>/dev/null || return 0
    log "🍪 کوکی از متغیر محیطی نوشته شد ($(wc -l < "$DATA_DIR/cookie.txt" 2>/dev/null | tr -d ' ') خط) → $DATA_DIR/cookie.txt"
}
if [ -n "${YOUTUBE_COOKIES_CONTENT:-}" ]; then
    write_cookie_seed "$YOUTUBE_COOKIES_CONTENT"
elif [ -n "${COOKIES_CONTENT:-}" ]; then
    write_cookie_seed "$COOKIES_CONTENT"
fi

# ── ۴) PO Token provider (bgutil) ──────────────────────────────────────────
POT_PID=""
pot_enabled="$(printf '%s' "${YOUTUBE_POT_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')"
case "$pot_enabled" in
    true|1|yes|on|enabled)
        if [ -f /opt/bgutil/build/main.js ]; then
            pot_port="4416"
            case "${YOUTUBE_POT_BASE_URL:-}" in
                *:*) pot_port="${YOUTUBE_POT_BASE_URL##*:}" ;;
            esac
            case "$pot_port" in ''|*[!0-9]*) pot_port="4416" ;; esac
            (cd /opt/bgutil && node build/main.js --host 127.0.0.1 --port "$pot_port") >"$DATA_DIR/pot-provider.log" 2>&1 &
            POT_PID=$!
            pot_ready=""
            for _ in $(seq 1 30); do
                if ! kill -0 "$POT_PID" 2>/dev/null; then
                    log "⚠️  PO Token provider کرش کرد (پایین را در $DATA_DIR/pot-provider.log ببین) ⇒ بدون PO token ادامه می‌دهیم."
                    POT_PID=""
                    break
                fi
                if (exec 3<>"/dev/tcp/127.0.0.1/$pot_port") 2>/dev/null; then
                    exec 3>&- 2>/dev/null || true
                    pot_ready="yes"
                    break
                fi
                sleep 1
            done
            if [ -n "$pot_ready" ]; then
                log "✅ PO Token provider آماده است (127.0.0.1:$pot_port)"
            elif [ -n "$POT_PID" ]; then
                log "⚠️  PO Token provider در ۳۰ ثانیه آماده نشد ⇒ بدون PO token ادامه می‌دهیم."
            fi
        else
            log "⚠️  YOUTUBE_POT_ENABLED=true است ولی provider داخل ایمیج نیست ⇒ بدون PO token ادامه می‌دهیم."
        fi
        ;;
    *) log "ℹ️  PO Token provider خاموش است (YOUTUBE_POT_ENABLED=false)." ;;
esac

# ── ۵) سرور سلامت (اختیاری) ───────────────────────────────────────────────
HEALTH_PID=""
if [ -n "${PORT:-}${HEALTH_PORT:-}" ]; then
    python -m HELPERS.railway_health &
    HEALTH_PID=$!
fi

# ── خاموشی تمیز ────────────────────────────────────────────────────────────
cleanup() {
    log "⏹  دریافت سیگنال خاموشی — بستن پروسه‌ها…"
    for pid in "${BOT_PID:-}" "$HEALTH_PID" "$POT_PID"; do
        [ -n "$pid" ] && kill "$pid" 2>/dev/null
    done
    sleep 1
    for pid in "${BOT_PID:-}" "$HEALTH_PID" "$POT_PID"; do
        [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null
    done
    exit 0
}
trap cleanup SIGTERM SIGINT SIGQUIT

# ── اطلاعات محیط (برای دیباگ در لاگ Railway) ───────────────────────────────
log "──────────────────────────────────────────────────────────"
log "🐍 Python    : $(python -V 2>&1)"
log "🎬 ffmpeg    : $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f1-3)"
log "🟩 Node      : $(node -v 2>/dev/null || echo 'نصب نیست')"
log "📺 yt-dlp    : $(python -c 'import yt_dlp; print(yt_dlp.version.__version__)' 2>/dev/null || echo '?')"
log "🕒 TZ        : $TZ"
log "📦 DATA_DIR  : $DATA_DIR $([ "$PERSIST" = 1 ] && echo '(پایدار)' || echo '(موقت)')"
log "💾 فضای آزاد : $(df -h "$DATA_DIR" 2>/dev/null | awk 'NR==2{print $4}')"
log "──────────────────────────────────────────────────────────"

# ── ۶) اجرای ربات ──────────────────────────────────────────────────────────
python magic.py &
BOT_PID=$!
echo "$BOT_PID" > "$DATA_DIR/bot.pid" 2>/dev/null || true
log "🚀 ربات اجرا شد (PID=$BOT_PID)"

wait "$BOT_PID"
exit_code=$?
log "⚠️  ربات با کد $exit_code خارج شد."

for pid in "$HEALTH_PID" "$POT_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
done
exit "$exit_code"
