import contextlib
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fb_upload as upload


class PermalinkTests(unittest.TestCase):
    def test_accepts_and_preserves_direct_video_and_reel_paths(self):
        for link in ("https://www.facebook.com/reel/2004/", "https://facebook.com/1004/videos/2004/"):
            with self.subTest(link=link):
                self.assertEqual(upload.normalize_video_permalink(link), link.rstrip("/"))

    def test_rejects_profile_links_external_hosts_and_nonhttps(self):
        links = (None, "https://www.facebook.com/profile.php?id=1004", "http://www.facebook.com/reel/2004",
                 "https://www.facebook.com.evil.test/reel/2004", "https://user@www.facebook.com/reel/2004",
                 "https://www.facebook.com:8443/reel/2004", "https://www.facebook.com/1004/videos/not-a-number")
        for link in links:
            with self.subTest(link=link), self.assertRaises(ValueError):
                upload.normalize_video_permalink(link)

    def fixture(self, root):
        video = root / "videos" / "fb04" / "personal" / "inbox" / "fixture.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"published video fixture")
        video.with_suffix(".txt").write_text("Fixture caption")
        key = "a" * 64
        state_path = root / "logs" / "publish_state.json"
        state = {key: {"account": "fb04", "target": "personal", "status": "needs_review",
                       "video": str(video), "caption": str(video.with_suffix(".txt")),
                       "identity_validation": {"session_marker": hashlib.sha256(b"personal:1004").hexdigest()},
                       "error": "original receipt timeout"},
                 "other": {"account": "fb07", "target": "personal", "status": "published", "video": "other.mp4"}}
        upload.save_json(state_path, state)
        config = root / "upload_config.json"
        upload.save_json(config, {"targets": []})
        return config, state_path, state, video, key

    def test_confirm_existing_video_url_preserves_other_jobs_backs_up_and_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, state_path, state, video, key = self.fixture(root)
            before = state_path.read_bytes()
            link = "https://www.facebook.com/1004/videos/2004/"
            with patch.object(upload, "ROOT", root), patch.object(upload, "CONFIG", config), \
                    patch("sys.argv", ["fb_upload.py", "confirm", "--job", key[:12], "--url", link]), \
                    patch.object(upload, "launch_context") as browser, \
                    patch.object(upload, "run_entry") as run, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(upload.main(), 0)
            browser.assert_not_called()
            run.assert_not_called()
            saved = upload.read_json(state_path, {})
            self.assertEqual(saved["other"], state["other"])
            self.assertEqual(saved[key]["status"], "published")
            self.assertEqual(saved[key]["permalink"], link.rstrip("/"))
            self.assertEqual(saved[key]["error"], "original receipt timeout")
            self.assertTrue((video.parent.parent / "completed" / video.name).is_file())
            self.assertFalse(video.exists())
            self.assertEqual(next((root / "backups").glob("*/publish_state.json")).read_bytes(), before)

    def test_invalid_confirmation_url_leaves_state_and_files_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, state_path, _, video, key = self.fixture(root)
            before = state_path.read_bytes()
            with patch.object(upload, "ROOT", root), patch.object(upload, "CONFIG", config), \
                    patch("sys.argv", ["fb_upload.py", "confirm", "--job", key[:12], "--url", "https://example.test/reel/2004"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(upload.main(), 1)
            self.assertEqual(state_path.read_bytes(), before)
            self.assertTrue(video.exists())
            self.assertFalse((root / "backups").exists())

    def test_video_link_for_other_owner_cannot_confirm_personal_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, state_path, _, video, key = self.fixture(root)
            before = state_path.read_bytes()
            with patch.object(upload, "ROOT", root), patch.object(upload, "CONFIG", config), \
                    patch("sys.argv", ["fb_upload.py", "confirm", "--job", key[:12], "--url", "https://www.facebook.com/1005/videos/2004/"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(upload.main(), 1)
            self.assertEqual(state_path.read_bytes(), before)
            self.assertTrue(video.exists())
            self.assertFalse((root / "backups").exists())


if __name__ == "__main__":
    unittest.main()
