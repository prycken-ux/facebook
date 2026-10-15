import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import fb_upload as upload


class ManualRecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(upload, "ROOT", self.root)
        self.root_patch.start()
        self.entry = {"account": "fb07", "target": "personal", "type": "personal",
                      "workflow": "personal_recording_v1", "name": "Example Person",
                      "url": "https://www.facebook.com/profile.php?id=1007", "enabled": False}
        self.folder = upload.inbox_for(self.entry)
        self.folder.mkdir(parents=True)
        self.video = self.folder / "manual.mp4"
        self.video.write_bytes(b"actual manually uploaded video fixture")
        self.video.with_suffix(".txt").write_text("Fixture caption")
        for path in (self.video, self.video.with_suffix(".txt")):
            os.utime(path, (time.time() - 120, time.time() - 120))
        self.state_path = self.root / "logs" / "publish_state.json"
        self.state = {"different-old-video": {"account": "fb04", "target": "personal",
                                             "status": "needs_review", "video": "older.mp4"}}
        upload.save_json(self.state_path, self.state)
        self.link = "https://www.facebook.com/reel/1000007"
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()

    def tearDown(self):
        self.silence.__exit__(None, None, None)
        self.root_patch.stop()
        self.temporary.cleanup()

    def register(self, video=None, link=None):
        return upload.record_manual_post(self.entry, self.state, self.state_path,
                                         video or self.video, link or self.link)

    def test_registration_backs_up_state_preserves_unrelated_review_and_keeps_files(self):
        previous = self.state_path.read_bytes()
        old = dict(self.state["different-old-video"])
        key = self.register()
        saved = upload.read_json(self.state_path, {})
        self.assertEqual(saved["different-old-video"], old)
        self.assertEqual(saved[key]["status"], "published")
        self.assertEqual(saved[key]["confirmation_method"], "user_verified_manual_post")
        self.assertEqual(saved[key]["permalink"], self.link)
        self.assertTrue(self.video.exists())
        self.assertTrue(self.video.with_suffix(".txt").exists())
        self.assertEqual(next((self.root / "backups").glob("*/publish_state.json")).read_bytes(), previous)

    def test_same_content_is_blocked_after_registration_even_if_renamed(self):
        self.register()
        renamed = self.folder / "renamed.mp4"
        self.video.rename(renamed)
        self.video.with_suffix(".txt").rename(renamed.with_suffix(".txt"))
        self.assertEqual(list(upload.pending_jobs(self.entry, self.state)), [])

    def test_repeated_registration_with_same_link_is_idempotent(self):
        key = self.register()
        snapshot = self.state_path.read_bytes()
        self.assertEqual(self.register(), key)
        self.assertEqual(self.state_path.read_bytes(), snapshot)
        self.assertEqual(len(list((self.root / "backups").iterdir())), 1)

    def test_same_reel_cannot_be_assigned_to_different_content(self):
        self.register()
        snapshot = self.state_path.read_bytes()
        other = self.folder / "other.mp4"
        other.write_bytes(b"different video bytes")
        with self.assertRaisesRegex(ValueError, "已登记到另一个视频"):
            self.register(video=other)
        self.assertEqual(self.state_path.read_bytes(), snapshot)

    def test_existing_different_permalink_is_not_overwritten(self):
        self.register()
        snapshot = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "已关联不同 Reel"):
            self.register(link="https://www.facebook.com/reel/1000008")
        self.assertEqual(self.state_path.read_bytes(), snapshot)

    def test_same_content_review_record_is_confirmed_with_history_retained(self):
        key = upload.job_key(self.entry, self.video)
        self.state[key] = {"account": "fb07", "target": "personal", "status": "needs_review",
                           "created": "original time", "error": "old receipt timeout"}
        self.register()
        self.assertEqual(self.state[key]["status"], "published")
        self.assertEqual(self.state[key]["created"], "original time")
        self.assertEqual(self.state[key]["error"], "old receipt timeout")

    def test_folder_or_nonreel_link_cannot_register_as_success(self):
        snapshot = self.state_path.read_bytes()
        for video, link in ((self.folder, self.link), (self.video, "https://www.facebook.com/profile.php?id=1007")):
            with self.subTest(video=video, link=link), self.assertRaises(ValueError):
                self.register(video=video, link=link)
        self.assertEqual(self.state_path.read_bytes(), snapshot)

    def test_cli_is_local_only_and_respects_existing_upload_lock(self):
        config = self.root / "upload_config.json"
        upload.save_json(config, {"targets": [self.entry]})
        args = ["fb_upload.py", "record-manual", "--account", "fb07", "--target", "personal",
                "--video", str(self.video), "--url", self.link]
        with patch.object(upload, "CONFIG", config), patch("sys.argv", args), \
                patch.object(upload, "launch_context") as browser:
            lock = self.root / "logs" / "upload.lock"
            lock.write_text("other process")
            self.assertEqual(upload.main(), 2)
            self.assertEqual(lock.read_text(), "other process")
            lock.unlink()
            self.assertEqual(upload.main(), 0)
        browser.assert_not_called()
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
