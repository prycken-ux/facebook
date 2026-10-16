import contextlib
import io
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fb_upload as uploader


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(uploader, "ROOT", self.root)
        self.root_patch.start()
        self.entry = {"account": "fb02", "target": "page01", "type": "page",
                      "name": "Donna Merrill", "url": "https://www.facebook.com/profile.php?id=61595182473231",
                      "enabled": True, "excluded_files": ["2026-10-13_01.mp4"]}
        self.folder = uploader.inbox_for(self.entry)
        self.folder.mkdir(parents=True)
        self.video = self.folder / "new.mp4"
        self.video.write_bytes(b"test queue content")
        self.caption = self.video.with_suffix(".txt")
        self.caption.write_text("Example caption", encoding="utf-8")
        for path in (self.video, self.caption):
            os.utime(path, (time.time() - 120, time.time() - 120))
        self.state_path = self.root / "logs" / "publish_state.json"
        self.state_path.parent.mkdir()
        self.state = {}
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.root_patch.stop()
        self.temporary.cleanup()

    def run_browser(self, button=None, prepare_error=None, notification_error=None, publish=True,
                    actor_error=None, actor_matches=True):
        button = button or MagicMock()
        browser = MagicMock()
        browser.pages = [MagicMock()]
        with patch("playwright.sync_api.sync_playwright") as playwright, \
                patch.object(uploader, "launch_context", return_value=browser), \
                patch.object(uploader, "prepare_reel", return_value=(button, {"method": "page_actor_id_match"}), side_effect=prepare_error), \
                patch.object(uploader, "page_actor_matches", return_value=actor_matches, side_effect=actor_error), \
                patch.object(uploader, "install_receipt_watch"), \
                patch.object(uploader, "wait_for_receipt", return_value="Your reel is published.", side_effect=notification_error), \
                patch("builtins.input", return_value=""):
            result = uploader.run_entry(self.entry, self.state, self.state_path, publish)
        return result, button, browser

    def test_duplicate_content_blocked_despite_new_filename_and_caption(self):
        key = uploader.job_key(self.entry, self.video)
        self.state[key] = {"status": "published"}
        self.video.rename(self.folder / "renamed.mp4")
        self.caption.rename(self.folder / "renamed.txt")
        caption = self.folder / "renamed.txt"
        caption.write_text("Changed caption", encoding="utf-8")
        os.utime(caption, (time.time() - 120, time.time() - 120))
        self.assertEqual(list(uploader.pending_jobs(self.entry, self.state)), [])

    def test_recorded_video_excluded_without_claiming_it_was_published(self):
        self.video.rename(self.folder / "2026-10-13_01.mp4")
        self.caption.rename(self.folder / "2026-10-13_01.txt")
        self.assertEqual(list(uploader.pending_jobs(self.entry, {})), [])
        self.assertEqual(self.state, {})

    def test_prepare_never_clicks_post_or_changes_state(self):
        prepared, button, browser = self.run_browser(publish=False)
        self.assertTrue(prepared)
        button.click.assert_not_called()
        self.assertEqual(self.state, {})
        self.assertFalse(self.state_path.exists())
        browser.close.assert_called_once()

    def test_failure_before_post_is_distinct_from_uncertain_post(self):
        with self.assertRaises(RuntimeError):
            self.run_browser(prepare_error=RuntimeError("Login challenge"))
        self.assertEqual(next(iter(self.state.values()))["status"], "failed_before_post")
        self.assertEqual(list(uploader.pending_jobs(self.entry, self.state)), [])

    def test_ambiguous_click_is_not_retried_and_blocks_queue(self):
        button = MagicMock()
        button.click.side_effect = RuntimeError("Connection interrupted")
        with self.assertRaises(RuntimeError):
            self.run_browser(button=button)
        self.assertEqual(next(iter(self.state.values()))["status"], "needs_review")
        with patch.object(uploader, "launch_context") as launch:
            with self.assertRaises(RuntimeError):
                uploader.run_entry(self.entry, self.state, self.state_path, True)
            launch.assert_not_called()
        button.click.assert_called_once()
        self.assertTrue(self.video.exists())

    def test_missing_success_notification_does_not_claim_published(self):
        with self.assertRaises(RuntimeError):
            self.run_browser(notification_error=RuntimeError("No confirmation"))
        self.assertEqual(next(iter(self.state.values()))["status"], "needs_review")
        self.assertTrue(self.video.exists())

    def test_identity_change_during_video_preparation_prevents_post(self):
        for matches, error in ((False, None), (False, RuntimeError("wrong actor"))):
            with self.subTest(matches=matches, error=error):
                self.state.clear()
                button = MagicMock()
                with self.assertRaises(RuntimeError):
                    self.run_browser(button=button, actor_matches=matches, actor_error=error)
                button.click.assert_not_called()
                self.assertEqual(next(iter(self.state.values()))["status"], "failed_before_post")
                self.assertTrue(self.video.exists())

    def test_success_persists_before_archiving_and_next_run_does_not_post(self):
        _, button, _ = self.run_browser()
        self.assertEqual(next(iter(uploader.read_json(self.state_path, {}).values()))["status"], "published")
        self.assertFalse(self.video.exists())
        self.assertTrue((self.folder.parent / "completed" / "new.mp4").exists())
        with patch.object(uploader, "launch_context") as launch:
            uploader.run_entry(self.entry, self.state, self.state_path, True)
            launch.assert_not_called()
        button.click.assert_called_once()

    def test_target_validation_and_deduplication_across_id_query_tracking(self):
        self.assertEqual(uploader.target_key(self.entry["url"] + "&sk=reels_tab"),
                         uploader.target_key(self.entry["url"]))
        for url in ("http://www.facebook.com/test", "https://facebook.com.evil.test/page", "https://www.facebook.com/login"):
            with self.assertRaises(ValueError):
                uploader.target_key(url)

    def test_profile_launch_retains_sandbox_and_uses_independent_folder(self):
        (self.root / "profiles" / "fb02").mkdir(parents=True)
        playwright = MagicMock()
        uploader.launch_context(playwright, self.entry)
        args, kwargs = playwright.chromium.launch_persistent_context.call_args
        self.assertEqual(Path(args[0]), self.root / "profiles" / "fb02")
        self.assertTrue(kwargs["chromium_sandbox"])
        self.assertEqual(kwargs["channel"], "chrome")
        playwright.chromium.launch_persistent_context.return_value.add_cookies.assert_called_once_with([
            {"name": "locale", "value": "en_US", "domain": ".facebook.com", "path": "/", "secure": True}])

    def test_language_query_preserves_target_identity_and_other_query_values(self):
        url = self.entry["url"] + "&sk=reels_tab&locale=zh_CN"
        normalized = uploader.english_url(url)
        self.assertEqual(uploader.target_key(normalized), uploader.target_key(url))
        self.assertIn("sk=reels_tab", normalized)
        self.assertIn("locale=en_US", normalized)
        self.assertNotIn("zh_CN", normalized)

    def test_actual_meta_success_message_and_suffix_are_supported(self):
        text = "Your reel is published. You can also share to Stories, groups and other places."
        self.assertIsNotNone(re.fullmatch(uploader.SUCCESS_PATTERN, text, re.I))
        self.assertIsNone(re.fullmatch(uploader.SUCCESS_PATTERN, "Your reel is safe to publish!", re.I))
        self.assertIsNone(re.fullmatch(uploader.SUCCESS_PATTERN, "Checking for copyrighted content", re.I))

    def test_receipt_requires_composer_to_close(self):
        page = MagicMock()
        page.url = self.entry["url"]
        page.evaluate.return_value = "Your reel is published."
        button = MagicMock()
        button.wait_for.side_effect = RuntimeError("Composer still open")
        with self.assertRaises(RuntimeError):
            uploader.wait_for_receipt(page, button)
        button.wait_for.assert_called_once_with(state="hidden", timeout=30000)

    def test_click_intent_is_saved_before_network_or_browser_can_fail(self):
        button = MagicMock()
        def before_click():
            persisted = uploader.read_json(self.state_path, {})
            self.assertEqual(next(iter(persisted.values()))["status"], "posting")
            raise RuntimeError("Browser disconnected after Post")
        button.click.side_effect = before_click
        with self.assertRaises(RuntimeError):
            self.run_browser(button=button)
        self.assertEqual(next(iter(self.state.values()))["status"], "needs_review")

    def test_receipt_timeout_is_deferred_without_success_or_archiving(self):
        with self.assertRaises(uploader.ReceiptNeedsReview):
            self.run_browser(notification_error=uploader.ReceiptNeedsReview("receipt timeout"))
        row = next(iter(self.state.values()))
        self.assertEqual(row["status"], "needs_review")
        self.assertEqual(row["review_reason"], "publication_receipt_timeout")
        self.assertTrue(self.video.exists())
        self.assertFalse((self.folder.parent / "completed").exists())

    def test_receipt_wait_timeout_has_distinct_type(self):
        from playwright.sync_api import TimeoutError
        page, button = MagicMock(), MagicMock()
        page.url = self.entry["url"]
        page.wait_for_function.side_effect = TimeoutError("Timeout 120000ms exceeded")
        with self.assertRaises(uploader.ReceiptNeedsReview):
            uploader.wait_for_receipt(page, button)
        button.wait_for.assert_not_called()

    def test_receipt_timeout_during_login_is_an_operational_stop(self):
        from playwright.sync_api import TimeoutError
        page = MagicMock()
        page.url = "https://www.facebook.com/checkpoint/"
        page.wait_for_function.side_effect = TimeoutError("Timeout")
        with self.assertRaises(RuntimeError) as raised:
            uploader.wait_for_receipt(page, MagicMock())
        self.assertNotIsInstance(raised.exception, uploader.ReceiptNeedsReview)

    def test_post_click_timeout_is_not_a_deferred_receipt(self):
        from playwright.sync_api import TimeoutError
        button = MagicMock()
        button.click.side_effect = TimeoutError("Click timed out")
        with self.assertRaises(RuntimeError) as raised:
            self.run_browser(button=button)
        self.assertNotIsInstance(raised.exception, uploader.ReceiptNeedsReview)
        self.assertNotIn("review_reason", next(iter(self.state.values())))

    def test_cli_returns_review_code_and_releases_lock(self):
        config = self.root / "upload_config.json"
        uploader.save_json(config, {"targets": [self.entry]})
        with patch.object(uploader, "CONFIG", config), \
                patch("sys.argv", ["fb_upload.py", "publish", "--account", "fb02"]), \
                patch.object(uploader, "run_entry", side_effect=uploader.ReceiptNeedsReview("receipt timeout")):
            self.assertEqual(uploader.main(), 3)
        self.assertFalse((self.state_path.parent / "upload.lock").exists())


if __name__ == "__main__":
    unittest.main()
