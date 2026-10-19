import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import apply_common_caption as app


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(app, "ROOT", self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entries = []
        for number in range(1, 14):
            personal = number in {3, 4, 7, 8, 9, 10, 11}
            row = dict(account="fb%02d" % number, target="personal" if personal else "page01",
                       type="personal" if personal else "page", name="Fixture %d" % number,
                       url="https://www.facebook.com/fixture%d" % number, enabled=False)
            if personal:
                row["workflow"] = "personal_recording_v1"
            self.entries.append(row)
        app.upload.save_json(self.root / "upload_config.json", {"targets": self.entries})
        app.upload.save_json(self.root / "logs/publish_state.json", {})
        self.accounts = [r["account"] for r in self.entries]
        self.text = "Common caption\nhttps://example.com/?a=1&b=2"

    def video(self, row, name="1.mp4", area="inbox"):
        path = self.root / "videos" / row["account"] / row["target"] / area / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((row["account"] + name).encode())
        old = time.time() - 120
        os.utime(path, (old, old))
        return path

    def test_all_thirteen_same_stem_txt_without_changing_media_or_state(self):
        videos = [self.video(r, "今天 01.MP4") for r in self.entries]
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in videos}
        state = (self.root / "logs/publish_state.json").read_bytes()
        config = (self.root / "upload_config.json").read_bytes()
        counts = app.apply(self.accounts, self.text)
        self.assertEqual(counts, {a: 1 for a in self.accounts})
        for p in videos:
            self.assertEqual(p.with_suffix(".txt").read_text(), self.text + "\n")
            self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before[p])
        self.assertEqual((self.root / "logs/publish_state.json").read_bytes(), state)
        self.assertEqual((self.root / "upload_config.json").read_bytes(), config)

    def test_archives_and_unselected_accounts_unchanged(self):
        selected = self.video(self.entries[0])
        other = self.video(self.entries[1])
        archived = self.video(self.entries[0], area="completed")
        archived.with_suffix(".txt").write_text("historical caption")
        app.apply([self.accounts[0]], self.text)
        self.assertTrue(selected.with_suffix(".txt").is_file())
        self.assertFalse(other.with_suffix(".txt").exists())
        self.assertEqual(archived.with_suffix(".txt").read_text(), "historical caption")

    def test_old_caption_backed_up_and_repeated_run_does_not_refresh_mtime(self):
        video = self.video(self.entries[0])
        txt = video.with_suffix(".txt")
        txt.write_bytes(b"original caption\r\n")
        app.apply([self.accounts[0]], self.text)
        backups = list((self.root / "backups").iterdir())
        self.assertEqual((backups[0] / txt.relative_to(self.root)).read_bytes(), b"original caption\r\n")
        old_time = txt.stat().st_mtime_ns
        app.apply([self.accounts[0]], self.text)
        self.assertEqual(txt.stat().st_mtime_ns, old_time)
        self.assertEqual(list((self.root / "backups").iterdir()), backups)

    def test_recorded_content_skipped_for_every_status(self):
        state = {}
        for row, status in zip(self.entries, ("published", "needs_review", "failed_before_post", "posting")):
            video = self.video(row)
            video.with_suffix(".txt").write_text("retain recorded caption")
            state[app.upload.job_key(row, video)] = {"status": status}
        app.upload.save_json(self.root / "logs/publish_state.json", state)
        app.apply(self.accounts[:4], self.text)
        for row in self.entries[:4]:
            txt = self.root / "videos" / row["account"] / row["target"] / "inbox/1.txt"
            self.assertEqual(txt.read_text(), "retain recorded caption")

    def test_recent_video_prevents_all_writes(self):
        first = self.video(self.entries[0])
        second = self.video(self.entries[1])
        os.utime(second, None)
        with self.assertRaises(ValueError):
            app.apply(self.accounts[:2], self.text)
        self.assertFalse(first.with_suffix(".txt").exists())
        self.assertFalse(second.with_suffix(".txt").exists())

    def test_write_failure_rolls_back_created_and_replaced_captions(self):
        videos = [self.video(r) for r in self.entries[:3]]
        videos[0].with_suffix(".txt").write_text("old first")
        original = app.atomic_caption
        calls = []

        def fail_third(path, text):
            calls.append(path)
            if len(calls) == 3:
                raise OSError("fixture failure")
            original(path, text)

        with patch.object(app, "atomic_caption", side_effect=fail_third):
            with self.assertRaises(OSError):
                app.apply(self.accounts[:3], self.text)
        self.assertEqual(videos[0].with_suffix(".txt").read_text(), "old first")
        self.assertFalse(videos[1].with_suffix(".txt").exists())
        self.assertFalse(videos[2].with_suffix(".txt").exists())

    def test_unknown_or_duplicate_account_and_empty_text_rejected(self):
        for accounts, text in ((["fb99"], self.text), (["fb01", "fb01"], self.text), (["fb01"], " \n")):
            with self.assertRaises(ValueError):
                app.apply(accounts, text)

    def test_empty_and_excluded_media_have_no_generated_caption(self):
        excluded = self.video(self.entries[0], "skip.mp4")
        empty = self.video(self.entries[0], "empty.mp4")
        empty.write_bytes(b"")
        self.entries[0]["excluded_files"] = ["SKIP.MP4"]
        app.upload.save_json(self.root / "upload_config.json", {"targets": self.entries})
        app.apply(["fb01"], self.text)
        self.assertFalse(excluded.with_suffix(".txt").exists())
        self.assertFalse(empty.with_suffix(".txt").exists())


if __name__ == "__main__":
    unittest.main()
