# -*- coding: utf-8 -*-
"""تستِ «معافیتِ ادمین از FloodWait» — tg-ytdlp-bot

اجرا از ریشهٔ ریپو:
    python3 scripts/test_admin_flood_bypass.py

چیزی که تست می‌شود:
  ۱) فلگ‌های کانفیگ و مقادیرِ پیش‌فرض (CONFIG/limits.py)
  ۲) تشخیصِ ادمین و دو تابعِ main (HELPERS/flood_guard.py)
  ۳) نوشته‌نشدنِ flood_wait.txt برای ادمین و نوشتنِ آن برای کاربرِ عادی
  ۴) برگشتِ (None, None) از read_flood_wait_remaining برای ادمین + پاک‌شدنِ فایلِ کهنه
  ۵) ریاضیِ فاصلهٔ انیمیشن/پیشرفت در HELPERS/download_status.py
  ۶) throttle شدنِ ادیتِ پیشرفت برای ادمین
  ۷) «گاردِ سورس»: هر ۴ گیتِ FloodWait واقعاً flood_guard را چک می‌کنند
"""
import os
import sys
import time
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

ADMIN_ID = 111000111
USER_ID = 222000222

# مقادیرِ اجباری تا CONFIG.config وسطِ ایمپورت متوقف نشود
os.environ.setdefault("BOT_TOKEN", "123456:TESTTESTTESTTESTTESTTESTTESTTEST")
os.environ.setdefault("API_ID", "1234567")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("ADMIN", str(ADMIN_ID))
os.environ.setdefault("TZ", "Asia/Tehran")


class FloodBypassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        cls._tmp = tempfile.mkdtemp(prefix="flood-test-")
        os.chdir(cls._tmp)  # users/ اینجا ساخته می‌شود، نه در ریپو

        from CONFIG.limits import LimitsConfig
        from HELPERS import flood_guard
        from HELPERS import safe_messeger
        from HELPERS import download_status
        cls.LimitsConfig = LimitsConfig
        cls.guard = flood_guard
        cls.sm = safe_messeger
        cls.ds = download_status

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    def _flood_path(self, uid):
        return os.path.join("users", str(uid), "flood_wait.txt")

    # ۱) فلگ‌های کانفیگ
    def test_01_config_flags(self):
        L = self.LimitsConfig
        self.assertTrue(L.ADMIN_NO_FLOOD_BLOCK)
        self.assertTrue(L.ADMIN_LOW_FLOOD_MODE)
        self.assertEqual(L.ADMIN_FLOOD_AUTO_WAIT_MAX, 1800)
        self.assertEqual(L.ADMIN_PROGRESS_EDIT_INTERVAL, 8.0)

    # ۲) تشخیصِ ادمین
    def test_02_admin_detection(self):
        self.assertTrue(self.guard.is_admin_chat(ADMIN_ID))
        self.assertFalse(self.guard.is_admin_chat(USER_ID))
        self.assertTrue(self.guard.bypass_enabled(ADMIN_ID))
        self.assertFalse(self.guard.bypass_enabled(USER_ID))
        self.assertFalse(self.guard.bypass_enabled(None))
        self.assertTrue(self.guard.low_flood_mode(ADMIN_ID))
        self.assertFalse(self.guard.low_flood_mode(USER_ID))

    def test_03_flag_off_disables_bypass(self):
        L = self.LimitsConfig
        old = L.ADMIN_NO_FLOOD_BLOCK
        L.ADMIN_NO_FLOOD_BLOCK = False
        try:
            self.assertFalse(self.guard.bypass_enabled(ADMIN_ID))
        finally:
            L.ADMIN_NO_FLOOD_BLOCK = old
        self.assertTrue(self.guard.bypass_enabled(ADMIN_ID))

    # ۳) نوشتنِ فایلِ تایمر
    def test_04_write_skipped_for_admin(self):
        self.sm._write_flood_wait_file(ADMIN_ID, 600)
        self.assertFalse(os.path.exists(self._flood_path(ADMIN_ID)),
                         "برای ادمین نباید flood_wait.txt نوشته شود")

        self.sm._write_flood_wait_file(USER_ID, 600)
        self.assertTrue(os.path.exists(self._flood_path(USER_ID)))
        with open(self._flood_path(USER_ID)) as f:
            stored = int(f.read().strip())
        self.assertAlmostEqual(stored, int(time.time()) + 600, delta=5)

    # ۴) خواندنِ تایمر
    def test_05_read_returns_none_for_admin(self):
        os.makedirs(os.path.join("users", str(ADMIN_ID)), exist_ok=True)
        with open(self._flood_path(ADMIN_ID), "w") as f:
            f.write(str(int(time.time()) + 500))

        self.assertEqual(self.sm.read_flood_wait_remaining(ADMIN_ID), (None, None))
        self.assertFalse(os.path.exists(self._flood_path(ADMIN_ID)),
                         "فایلِ کهنهٔ ادمین باید پاک شود")

        self.sm._write_flood_wait_file(USER_ID, 500)
        remaining, text = self.sm.read_flood_wait_remaining(USER_ID)
        self.assertIsInstance(remaining, int)
        self.assertGreater(remaining, 400)
        self.assertIn("m", text)

    # ۵) ریاضیِ فاصلهٔ انیمیشن
    def test_06_adaptive_interval(self):
        # کاربرِ عادی: همان رفتارِ قبلی
        self.assertEqual(self.ds._adaptive_interval(0), 3.0)
        self.assertEqual(self.ds._adaptive_interval(300), 4.0)
        self.assertEqual(self.ds._adaptive_interval(3600), 90.0)
        # ادمین: ×۳ با حداقل ۱۰ ثانیه
        self.assertEqual(self.ds._adaptive_interval(0, ADMIN_ID), 10.0)
        self.assertEqual(self.ds._adaptive_interval(300, ADMIN_ID), 12.0)
        self.assertEqual(self.ds._adaptive_interval(3600, ADMIN_ID), 270.0)
        # ادمین با خاموشیِ حالتِ کم‌فلوود: مثل کاربرِ عادی
        L = self.LimitsConfig
        old = L.ADMIN_LOW_FLOOD_MODE
        L.ADMIN_LOW_FLOOD_MODE = False
        try:
            self.assertEqual(self.ds._adaptive_interval(0, ADMIN_ID), 3.0)
        finally:
            L.ADMIN_LOW_FLOOD_MODE = old

    # ۶) throttle ادیتِ پیشرفت
    def test_07_progress_throttle(self):
        calls = []

        def fake_edit(user_id, msg_id, text):
            calls.append((user_id, msg_id, text))
            return True

        old_edit = self.ds.safe_edit_message_text
        self.ds.safe_edit_message_text = fake_edit
        try:
            now = time.time()
            # کاربرِ عادی با ۲ ثانیه فاصله ⇒ ادیت می‌شود (آستانه=۱)
            self.ds._last_upload_update_ts[(USER_ID, 1)] = now - 2.0
            self.ds.progress_bar(1, 10, USER_ID, 1, "t")
            self.assertEqual(len(calls), 1, "کاربرِ عادی باید ادیت شود")
            # ادمین با ۲ ثانیه فاصله ⇒ سرکوب می‌شود (آستانه=۸)
            self.ds._last_upload_update_ts[(ADMIN_ID, 2)] = now - 2.0
            self.ds.progress_bar(1, 10, ADMIN_ID, 2, "t")
            self.assertEqual(len(calls), 1, "ادیتِ ادمین باید throttle شود")
            # ادمین با ۹ ثانیه فاصله ⇒ ادیت می‌شود
            self.ds._last_upload_update_ts[(ADMIN_ID, 3)] = now - 9.0
            self.ds.progress_bar(1, 10, ADMIN_ID, 3, "t")
            self.assertEqual(len(calls), 2, "ادیتِ ادمین بعد از ۸ ثانیه باید انجام شود")
        finally:
            self.ds.safe_edit_message_text = old_edit

    # ۷) گاردِ سورس (هر ۴ گیت + sender)
    def test_08_source_guards(self):
        gates = [
            "DOWN_AND_UP/down_and_up.py",
            "DOWN_AND_UP/down_and_audio.py",
            "DOWN_AND_UP/always_ask_menu.py",
            "DOWN_AND_UP/live_stream_downloader.py",
        ]
        for rel in gates:
            with open(os.path.join(REPO, rel), encoding="utf-8") as f:
                src = f.read()
            self.assertIn("flood_guard", src, rel)
            self.assertIn("_admin_flood_free", src, rel)
            # گیت باید واقعاً «رد شدن برای ادمین» را داشته باشد
            self.assertIn("if not _admin_flood_free:", src, rel)

        with open(os.path.join(REPO, "DOWN_AND_UP/sender.py"), encoding="utf-8") as f:
            sender = f.read()
        self.assertIn("admin_auto_wait_max", sender)
        self.assertIn("_auto_wait_max", sender)

        with open(os.path.join(REPO, "HELPERS/safe_messeger.py"), encoding="utf-8") as f:
            sm = f.read()
        self.assertIn("def _write_flood_wait_file", sm)
        self.assertIn("bypass_enabled", sm)
        self.assertIn("bypass_enabled", sm.split("def read_flood_wait_remaining")[1][:600])

        with open(os.path.join(REPO, "CONFIG/limits.py"), encoding="utf-8") as f:
            limits = f.read()
        for flag in ("ADMIN_NO_FLOOD_BLOCK", "ADMIN_FLOOD_AUTO_WAIT_MAX",
                     "ADMIN_LOW_FLOOD_MODE", "ADMIN_PROGRESS_EDIT_INTERVAL"):
            self.assertIn(flag, limits)
            self.assertIn(f'_env_' , limits)
            self.assertIn(f'"{flag}"', limits, f"{flag} باید از env خوانده شود")


if __name__ == "__main__":
    unittest.main(verbosity=2)
