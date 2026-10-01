# -*- coding: utf-8 -*-
"""
HELPERS/railway_health.py — وب‌سرور سلامت (اختیاری، برای Railway / مانیتورینگ)

هر وقت Railway متغیر PORT بدهد (یعنی دامنه/پورت عمومی ساخته شده باشد) یا خودت
HEALTH_PORT را ست کنی، این سرور کوچک بالا می‌آید و این آدرس‌ها را جواب می‌دهد:

    GET /            اطلاعات کوتاه
    GET /health      سلامت (برای Healthcheck خودِ Railway)
    GET /healthz     مثل /health
    GET /ready       آمادگی (اگر پروسهٔ ربات مرده باشد 503 می‌دهد)

هیچ وابستگی سنگینی ندارد و روی همان پروسهٔ جداگانه اجرا می‌شود؛ اگر خراب شود
ربات هیچ آسیبی نمی‌بیند.
"""
import json
import os
import shutil
import time

try:
    from aiohttp import web
except Exception as exc:  # pragma: no cover - aiohttp همیشه در requirements هست
    raise SystemExit("aiohttp لازم است: %s" % exc)

START_TS = time.time()
DATA_DIR = os.environ.get("DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or ""


def _read_pid():
    candidates = [
        os.path.join(DATA_DIR, "bot.pid") if DATA_DIR else "",
        "/tmp/bot.pid",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            with open(path, "r") as handle:
                return int(handle.read().strip())
        except Exception:
            continue
    return 0


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return os.path.exists("/proc/%d" % pid)


def _is_mount(path):
    """آیا روی این مسیر واقعاً یک Volume مانت شده است؟"""
    if not path:
        return False
    try:
        with open("/proc/mounts", "r") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == path:
                    return True
    except Exception:
        pass
    return False


def _disk():
    path = DATA_DIR if (DATA_DIR and os.path.isdir(DATA_DIR)) else "/app"
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": path,
            "totalGB": round(usage.total / (1024 ** 3), 2),
            "freeGB": round(usage.free / (1024 ** 3), 2),
        }
    except Exception:
        return {}


def _payload():
    pid = _read_pid()
    alive = _pid_alive(pid)
    return {
        "status": "ok" if alive else "degraded",
        "service": "tg-ytdlp-bot",
        "botAlive": alive,
        "botPid": pid or None,
        "uptimeSec": int(time.time() - START_TS),
        "dataDir": DATA_DIR or "(ephemeral)",
        "volume": _is_mount(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or DATA_DIR),
        "disk": _disk(),
        "tz": os.environ.get("TZ", "UTC"),
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


async def _json(request):
    return web.json_response(_payload())


async def _ready(request):
    payload = _payload()
    strict = os.environ.get("HEALTH_STRICT", "").lower() in ("1", "true", "yes", "on")
    code = 200
    if strict and not payload["botAlive"]:
        code = 503
    return web.json_response(payload, status=code)


async def _root(request):
    payload = _payload()
    lines = [
        "tg-ytdlp-bot",
        "status   : %s" % payload["status"],
        "botAlive : %s" % payload["botAlive"],
        "uptime   : %ss" % payload["uptimeSec"],
        "dataDir  : %s" % payload["dataDir"],
        "health   : /health  (json)   ready: /ready",
        "diag     : /diag/info?token=…   /diag/log?token=…&tail=200",
    ]
    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")



# ───────────────────── عیب‌یابی از راهِ دور (/diag) ─────────────────────
# چرا: گاهی به لاگِ ریلویِ یک دیپلوی دسترسی نداریم (اکانت/پروژهٔ دیگر)، ولی دامنهٔ
# عمومی‌اش را داریم. این دو روتِ **قفل‌شده با توکن** اجازه می‌دهند همان لاگ و وضعیتِ
# دیسک را با curl بخوانیم:
#     GET /diag/info?token=…            وضعیتِ دیسک/مسیرها/لینک‌ها (json)
#     GET /diag/log?token=…&tail=200&grep=DIRECT   آخرین خط‌های bot.log
# توکن: env «DIAG_TOKEN» یا فایلی که خودش در «$DATA_DIR/diag.token» می‌سازد و
# **یک بار** برای آیدی‌های ADMIN در تلگرام می‌فرستد (تا صاحبِ ربات گمش نکند).
_SECRET_RE = None


def _redact(line: str) -> str:
    """توکن/رمزها را در خروجیِ لاگ می‌پوشاند (حتی اگر ناخواسته چاپ شده باشند)."""
    global _SECRET_RE
    import re as _re
    if _SECRET_RE is None:
        _SECRET_RE = _re.compile(
            r"(?i)\b(\d{6,10}:[A-Za-z0-9_-]{20,}|[A-Za-z0-9_-]{32,}|ghp_[A-Za-z0-9]{20,}"
            r"|railway_[A-Za-z0-9]{10,}|xox[baprs]-[A-Za-z0-9-]{10,})\b")
    try:
        return _SECRET_RE.sub(lambda m: (m.group(1)[:6] + "…" + "REDACTED"), line)
    except Exception:
        return line


def _diag_token_path() -> str:
    base = DATA_DIR if (DATA_DIR and os.path.isdir(DATA_DIR)) else "/app"
    return os.path.join(base, "diag.token")


def _announce_token(token: str) -> None:
    """توکنِ تازه را یک بار به ادمین‌ها خبر می‌دهد (Bot API، بدونِ وابستگی به pyrogram)."""
    import urllib.parse
    import urllib.request
    bot = (os.environ.get("BOT_TOKEN") or "").strip()
    admins = [x.strip() for x in (os.environ.get("ADMIN") or "").split(",") if x.strip().lstrip("-").isdigit()]
    if not bot or not admins:
        return
    host = ""
    for key in ("LINK_BASE_URL", "PUBLIC_URL"):
        val = (os.environ.get(key) or "").strip()
        if val:
            host = val.rstrip("/")
            break
    if not host:
        dom = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip()
        host = ("https://" + dom) if dom else ""
    text = ("🔑 توکنِ عیب‌یابیِ ربات (برای خواندنِ لاگ از راهِ دور):\n"
            "<code>%s</code>\n\n%s"
            % (token,
               (("🩺 <code>%s/diag/info?token=%s</code>\n📄 <code>%s/diag/log?token=%s&amp;tail=200</code>"
                 % (host, token, host, token)) if host else
                "/diag/info?token=… و /diag/log?token=… روی دامنهٔ ربات")))
    for chat in admins[:5]:
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                           "parse_mode": "HTML",
                                           "disable_web_page_preview": "true"}).encode()
            req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % bot,
                                         data=data,
                                         headers={"User-Agent": "Mozilla/5.0 (diag-announce)"})
            urllib.request.urlopen(req, timeout=10).read(64)
            print("[diag] توکن به %s فرستاده شد" % chat)
        except Exception as exc:
            print("[diag] ارسالِ توکن به %s نشد: %s" % (chat, exc))


def _diag_token() -> str:
    """توکنِ فعال (از env یا فایلِ پایدار). خطا ⇒ رشتهٔ خالی یعنی /diag خاموش."""
    env_tok = (os.environ.get("DIAG_TOKEN") or "").strip()
    if env_tok:
        return env_tok
    path = _diag_token_path()
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                tok = fh.read().strip()
            if len(tok) >= 16:
                return tok
    except Exception:
        pass
    try:
        import secrets as _secrets
        tok = _secrets.token_hex(24)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(tok)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        print("[diag] توکنِ عیب‌یابی ساخته شد → %s" % path)
        _announce_token(tok)
        return tok
    except Exception as exc:
        print("[diag] ساختِ توکن ناموفق: %s" % exc)
        return ""


def _diag_authorized(request) -> bool:
    import hmac
    tok = _diag_token()
    if not tok:
        return False
    given = (request.query.get("token") or request.headers.get("X-Diag-Token") or "").strip()
    try:
        return bool(given) and hmac.compare_digest(given, tok)
    except Exception:
        return False


def _bot_log_path() -> str:
    for cand in (os.path.join(DATA_DIR, "bot.log") if DATA_DIR else "",
                 "/app/bot.log", os.path.abspath("bot.log")):
        if cand and os.path.exists(cand):
            return cand
    return ""


def _tail_lines(path: str, limit: int, needle: str = "") -> list:
    """آخرین «limit» خطِ فایل (کارآمد: از انتها می‌خواند)."""
    out, block, data = [], 65536, b""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            while size > 0 and len(out) < limit:
                read_size = min(block, size)
                size -= read_size
                fh.seek(size)
                data = fh.read(read_size) + data
                out = data.split(b"\n")
                if size > 0 and len(out) < limit:
                    continue
            lines = [ln.decode("utf-8", "replace") for ln in out]
    except Exception as exc:
        return ["(خواندنِ لاگ ناموفق: %s)" % exc]
    lines = [ln for ln in lines if ln.strip()]
    if needle:
        low = needle.lower()
        lines = [ln for ln in lines if low in ln.lower()]
    return [_redact(ln) for ln in lines[-limit:]]


async def _diag_info(request):
    if not _diag_authorized(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    info = _payload()
    try:
        paths = {}
        for name in ("users", "bot.log", "magic.session", "dump.json", "filelinks"):
            src = os.path.join("/app", name)
            entry = {"exists": os.path.exists(src), "symlink": os.path.islink(src)}
            if entry["symlink"]:
                try:
                    entry["target"] = os.readlink(src)
                except Exception:
                    pass
            paths[name] = entry
        info["paths"] = paths
        disks = {}
        for label, path in (("data", DATA_DIR or "/data"), ("app", "/app")):
            try:
                usage = shutil.disk_usage(path)
                disks[label] = {"path": path, "totalMB": round(usage.total / 1048576, 1),
                                "freeMB": round(usage.free / 1048576, 1)}
            except Exception as exc:
                disks[label] = {"path": path, "error": str(exc)}
        info["disks"] = disks
        info["logFile"] = _bot_log_path() or "(پیدا نشد)"
        try:
            info["logSizeKB"] = round(os.path.getsize(info["logFile"]) / 1024, 1)
        except Exception:
            info["logSizeKB"] = None
        # خلاصهٔ لینک‌های فایل (بدونِ افشای مسیرِ کامل/محتوا)
        try:
            from HELPERS.filelink_routes import load as _load_links, keep_after_exp_sec
            recs = _load_links()
            now = time.time()
            sizes = sum(int(r.get("size") or 0) for r in recs.values())
            info["links"] = {"count": len(recs), "totalMB": round(sizes / 1048576, 2),
                             "expired": sum(1 for r in recs.values()
                                            if (r.get("exp") or 0) and now > r["exp"]),
                             "keepAfterExpHours": round(keep_after_exp_sec() / 3600, 1),
                             "oldestIn": round(min([(r.get("created") or now) for r in recs.values()]
                                                   or [now]) - now, 1)}
        except Exception as exc:
            info["links"] = {"error": str(exc)}
        keys = ("PORT", "HEALTH_PORT", "DATA_DIR", "RAILWAY_VOLUME_MOUNT_PATH", "TZ",
                "LINK_BASE_URL", "RAILWAY_PUBLIC_DOMAIN", "MAX_FILE_SIZE_GB",
                "DISK_MIN_FREE_MB", "LINK_DEFAULT_TTL", "FILELINK_KEEP_HOURS",
                "FILELINK_MIN_FREE_MB", "DIRECT_LINK_DISABLE", "DIRECT_LINK_LOCAL_MIRROR",
                "DIRECT_LINK_LOCAL_SELF", "DIAG_TOKEN")
        info["env"] = {k: (("<set len=%d>" % len(os.environ.get(k, "")))
                           if k in ("DIAG_TOKEN",) else os.environ.get(k))
                       for k in keys if os.environ.get(k) is not None}
        info["cwd"] = os.getcwd()
    except Exception as exc:
        info["diagError"] = str(exc)
    return web.json_response(info)


async def _diag_log(request):
    if not _diag_authorized(request):
        return web.Response(text="unauthorized\n", status=401, content_type="text/plain")
    try:
        tail = int(request.query.get("tail") or "200")
    except Exception:
        tail = 200
    tail = max(1, min(tail, 2000))
    needle = (request.query.get("grep") or "").strip()[:80]
    path = _bot_log_path()
    if not path:
        return web.Response(text="bot.log پیدا نشد (DATA_DIR=%s)\n" % DATA_DIR,
                            status=404, content_type="text/plain")
    lines = _tail_lines(path, tail, needle)
    head = "# %s | %d خط | فیلتر=%r\n" % (path, len(lines), needle or "-")
    return web.Response(text=head + "\n".join(lines) + "\n", content_type="text/plain")


def build_app():
    app = web.Application()
    app.router.add_get("/", _root)
    app.router.add_get("/health", _json)
    app.router.add_get("/healthz", _json)
    app.router.add_get("/ready", _ready)
    # عیب‌یابی از راهِ دور (قفل‌شده با توکن)
    try:
        app.router.add_get("/diag/info", _diag_info)
        app.router.add_get("/diag/log", _diag_log)
    except Exception as exc:
        print("[diag] routes not registered: %s" % exc)
    # فایل → لینکِ مستقیم: روت‌های /d/<token>/<name> (ماژولِ سبک، بدونِ وابستگی به ربات)
    try:
        from HELPERS.filelink_routes import register_routes
        register_routes(app)
    except Exception as exc:            # هرگز سرورِ سلامت را نباید از کار بیندازد
        print("[filelink] routes not registered: %s" % exc)
    return app


def main():
    port = 0
    for key in ("HEALTH_PORT", "PORT"):
        raw = (os.environ.get(key) or "").strip()
        if raw.isdigit():
            port = int(raw)
            break
    if not port:
        print("ℹ️  HEALTH_PORT/PORT ست نشده — سرور سلامت خاموش است (ربات بدون پورت هم کار می‌کند).")
        return
    print("🩺 سلامت روی 0.0.0.0:%d — /health و /ready" % port)
    web.run_app(build_app(), host="0.0.0.0", port=port, access_log=None, print=None)


if __name__ == "__main__":
    main()
