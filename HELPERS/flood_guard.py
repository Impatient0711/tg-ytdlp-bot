# -*- coding: utf-8 -*-
"""HELPERS/flood_guard.py — معافیتِ ادمین از FloodWait تلگرام.

سه چیز را مرکز می‌کند تا همه‌جا یک‌دست باشد:
  1) bypass_enabled(chat_id): ادمین بودن + روشن‌بودنِ ADMIN_NO_FLOOD_BLOCK
  2) admin_auto_wait_max():   سقفِ انتظارِ خودکارِ ادمین روی FloodWait (ثانیه)
  3) low_flood_mode(chat_id): ADMIN_LOW_FLOOD_MODE ⇒ ادیت‌های پیشرفت/انیمیشنِ کمتر

هیچ وابستگی سنگینی ندارد (فقط CONFIG) تا از هر ماژولی قابلِ ایمپورت باشد.
همهٔ فراخوان‌ها با try/except محافظت می‌شوند؛ خرابیِ این ماژول نباید ربات را بیندازد.
"""
from CONFIG.config import Config
from CONFIG.limits import LimitsConfig


def admin_ids():
    """مجموعهٔ آیدی‌های عددیِ ادمین (خالی در صورت خطا)."""
    try:
        return {int(x) for x in (getattr(Config, "ADMIN", None) or []) if int(x) > 0}
    except Exception:
        return set()


def is_admin_chat(chat_id) -> bool:
    try:
        return int(chat_id) in admin_ids()
    except Exception:
        return False


def bypass_enabled(chat_id=None) -> bool:
    """True ⇒ این چت نباید با تایمر/پیامِ FloodWait بلاک شود."""
    if chat_id is None or not getattr(LimitsConfig, "ADMIN_NO_FLOOD_BLOCK", False):
        return False
    return is_admin_chat(chat_id)


def admin_auto_wait_max() -> int:
    """سقفِ انتظارِ خودکار برای ادمین (ثانیه) — پیش‌فرض ۱۸۰۰ (۳۰ دقیقه)."""
    try:
        return max(0, int(getattr(LimitsConfig, "ADMIN_FLOOD_AUTO_WAIT_MAX", 1800)))
    except Exception:
        return 1800


def low_flood_mode(chat_id=None) -> bool:
    """True ⇒ ارسال‌های کم‌اهمیت برای ادمین کمتر می‌شود."""
    if chat_id is None or not getattr(LimitsConfig, "ADMIN_LOW_FLOOD_MODE", False):
        return False
    return is_admin_chat(chat_id)


def progress_edit_interval() -> float:
    try:
        return max(1.0, float(getattr(LimitsConfig, "ADMIN_PROGRESS_EDIT_INTERVAL", 8.0)))
    except Exception:
        return 8.0
