# -*- coding: utf-8 -*-
"""روت‌های دانلودِ لینکِ مستقیم — بدونِ وابستگی به CONFIG.

چرا جدا: این روت‌ها هم داخلِ پروسهٔ ربات ثبت می‌شوند و هم داخلِ وب‌سرورِ سلامت
(``HELPERS/railway_health.py`` که از ``scripts/docker-entrypoint.sh`` بالا می‌آید و
روی پورتِ عمومیِ Railway گوش می‌دهد). آن پروسه فقط ``os``/``json``/``aiohttp``
می‌شناسد، پس این ماژول هم باید سبک و بدونِ CONFIG باشد تا سرورِ سلامت هیچ‌وقت
به‌خاطرِ ما از کار نیفتد.

اشتراکِ داده با پروسهٔ ربات از راهِ همان فایلِ ``links.json`` در پوشهٔ داده است.
"""
from __future__ import annotations

import json
import os
import urllib.parse


def data_dir() -> str:
    return (os.environ.get("DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
            or "/data")


def links_dir() -> str:
    d = os.path.join(data_dir(), "filelinks")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def store_path() -> str:
    return os.path.join(links_dir(), "links.json")


def load() -> dict:
    try:
        with open(store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def free_mb(path: str | None = None) -> float:
    """فضای آزادِ دیسکِ پوشهٔ لینک‌ها (مگابایت). خطا ⇒ عددِ بزرگ (سخت‌گیری نکن)."""
    try:
        st = os.statvfs(path or links_dir())
        return (st.f_bavail * st.f_frsize) / (1024.0 * 1024.0)
    except Exception:
        return 10 ** 9


def min_free_mb() -> float:
    """آستانهٔ فضایِ آزاد (پیش‌فرض ۱۵۰ مگابایت). زیرِ این ⇒ لینکِ تازه ساخته نمی‌شود."""
    try:
        return max(0.0, float((os.environ.get("FILELINK_MIN_FREE_MB") or "150").strip()))
    except Exception:
        return 150.0


def keep_after_exp_sec() -> int:
    """چند ساعت فایل بعد از انقضای لینک روی دیسک بماند.

    لینکِ عمومی سرِ موعدش ۴۰۴ می‌شود، ولی خودِ ربات باید بتواند «همان لینکِ خودش»
    را دوباره دانلود کند؛ پس فایل را پاک نمی‌کنیم و فقط بعد از این مهلت می‌بریم.
    """
    try:
        hours = float((os.environ.get("FILELINK_KEEP_HOURS") or "72").strip())
    except Exception:
        hours = 72.0
    return int(max(0.0, hours) * 3600)


def resolve(token: str, allow_expired: bool = False):
    """رکوردِ لینک اگر وجود داشته باشد و فایلش روی دیسک باشد.

    ``allow_expired=True`` ⇒ رکوردِ منقضی هم برگردانده می‌شود (برای خودِ ربات که
    بخواهد از کپیِ محلی استفاده کند). لینکِ عمومیِ منقضی همان‌طور ۴۰۴ می‌ماند.
    """
    import time
    rec = load().get(token)
    if not rec:
        return None
    expired = bool(rec.get("exp")) and time.time() > rec["exp"]
    if expired and not allow_expired:
        return None
    path = rec.get("path") or ""
    if not os.path.exists(path):
        return None
    if expired:
        rec = dict(rec)
        rec["expired"] = True
    return rec


def sweep_files() -> list:
    """رکوردهای «گذشته از مهلتِ نگه‌داری» را پاک می‌کند.

    لینکِ منقضی ⇒ رکورد می‌ماند و فایل هم تا ``FILELINK_KEEP_HOURS`` (پیش‌فرض ۷۲
    ساعت) روی دیسک می‌ماند؛ فقط بعد از آن پاک می‌شود. این‌طوری «فایل بده → لینک
    بگیر → همان لینک را بده» حتی بعد از انقضای لینکِ عمومی هم کار می‌کند.
    """
    import time
    now = time.time()
    recs = load()
    keep = keep_after_exp_sec()
    torn = []
    changed = False
    for token, rec in list(recs.items()):
        exp = rec.get("exp") or 0
        if not exp or now <= exp:
            continue
        # لینک منقضی است؛ فایل تا مهلتِ نگه‌داری می‌ماند (رکورد هم می‌ماند)
        if now <= exp + keep:
            continue
        torn.append(rec)
        recs.pop(token, None)
        changed = True
    # ── گاردِ فضایِ دیسک: نگه‌داشتنِ فایلِ منقضی نباید دیسک را پُر کند ──
    # (روی والیومِ کوچکِ ریلوی، مثلاً ۰٫۴ گیگابایت، چند کلیپِ ۱۰ مگابایتی کافی است)
    kept = [(token, rec) for token, rec in recs.items()
            if (rec.get("exp") or 0) and now > rec["exp"]]
    if kept and free_mb() < min_free_mb():
        kept.sort(key=lambda kv: kv[1].get("exp") or 0)   # قدیمی‌ترین انقضا اول
        for token, rec in kept:
            if free_mb() >= min_free_mb():
                break
            recs.pop(token, None)
            torn.append(rec)
            changed = True

    if changed:
        try:
            with open(store_path(), "w", encoding="utf-8") as f:
                json.dump(recs, f, ensure_ascii=False)
        except Exception:
            pass
        for rec in torn:
            try:
                os.remove(rec.get("path") or "")
            except Exception:
                pass
    return torn


def register_routes(app) -> bool:
    """روت‌های ``/d/<token>`` (و ``/d/<token>/<name>``) را به یک اپِ aiohttp اضافه می‌کند."""
    try:
        from aiohttp import web
    except Exception:
        return False

    async def _download(request):
        rec = resolve(request.match_info.get("token", ""))
        if not rec:
            return web.Response(status=404, text="لینک منقضی شده یا وجود ندارد.")
        path = rec.get("path") or ""
        if not os.path.exists(path):
            return web.Response(status=404, text="فایل پیدا نشد.")
        resp = web.FileResponse(path)          # پشتیبانی از Range برای دانلود‌منیجر
        resp.headers["Content-Disposition"] = ('attachment; filename="%s"'
                                               % urllib.parse.quote(os.path.basename(path)))
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Accept-Ranges"] = "bytes"
        return resp

    for path in ("/d/{token}", "/d/{token}/{name}"):
        # add_get خودش HEAD را هم ثبت می‌کند (allow_head=True) — ثبتِ دوبارهٔ HEAD را
        # aiohttp با خطا رد می‌کند و آن‌وقت بعضی روت‌ها ثبت نمی‌شوند.
        app.router.add_get(path, _download, allow_head=True)
    return True
