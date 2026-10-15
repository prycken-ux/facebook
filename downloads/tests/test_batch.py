import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import batch_upload as batch


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(batch, "ROOT", self.root)
        self.root_patch.start()
        for account in ("fb01", "fb02"):
            (self.root / "profiles" / account).mkdir(parents=True)
        self.entries = [{"account": "fb01", "target": "page01", "type": "page", "name": "One",
                         "url": "https://www.facebook.com/profile.php?id=1001", "enabled": True, "prepared_at": "checked"},
                        {"account": "fb02", "target": "page01", "type": "page", "name": "Two",
                         "url": "https://www.facebook.com/profile.php?id=1002", "enabled": True, "prepared_at": "checked"}]

    def tearDown(self):
        self.root_patch.stop()
        self.temporary.cleanup()

    def test_complete_preflight_blocks_missing_or_personal_target(self):
        selected, errors = batch.select_targets({"targets": self.entries}, ["fb01", "fb02", "fb03"], "publish", {})
        self.assertTrue(any("fb03" in message for message in errors))
        self.entries[1]["type"] = "personal"
        _, errors = batch.select_targets({"targets": self.entries}, ["fb01", "fb02"], "publish", {})
        self.assertTrue(any("个人主页" in message for message in errors))

    def test_same_public_page_cannot_be_posted_twice_in_one_batch(self):
        self.entries[1]["url"] = self.entries[0]["url"] + "&sk=reels_tab"
        _, errors = batch.select_targets({"targets": self.entries}, ["fb01", "fb02"], "publish", {})
        self.assertTrue(any("重复配置" in message for message in errors))

    def test_recorded_personal_target_is_accepted_but_requires_its_own_prepare(self):
        self.entries[1].update(type="personal", target="personal", workflow="personal_recording_v1")
        selected, errors = batch.select_targets({"targets": self.entries}, ["fb01", "fb02"], "publish", {})
        self.assertEqual(errors, [])
        self.assertEqual(len(selected), 2)
        self.entries[1].pop("prepared_at")
        _, errors = batch.select_targets({"targets": self.entries}, ["fb02"], "publish", {})
        self.assertTrue(any("prepare" in message for message in errors))

    def test_review_blocks_batch_before_any_account_posts(self):
        state = {"job": {"account": "fb02", "target": "page01", "status": "needs_review"}}
        _, errors = batch.select_targets({"targets": self.entries}, ["fb01", "fb02"], "publish", state)
        self.assertTrue(errors)

    def test_stops_after_ambiguous_first_account_instead_of_starting_next(self):
        with patch("batch_upload.subprocess.run", return_value=SimpleNamespace(returncode=1)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            result = batch.execute(self.entries, "publish")
        self.assertEqual(len(result), 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result[0]["account"], "fb01")

    def test_successful_commands_are_sequential_and_keep_account_mapping(self):
        with patch("batch_upload.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            result = batch.execute(self.entries, "prepare")
        self.assertEqual([row["account"] for row in result], ["fb01", "fb02"])
        for account, call in zip(["fb01", "fb02"], run.call_args_list):
            self.assertIn(account, call.args[0])
            self.assertIn("prepare", call.args[0])

    def test_missing_target_does_not_launch_child_process(self):
        with patch.object(batch.upload, "read_json", side_effect=[{"targets": self.entries}, {}]), \
                patch("sys.argv", ["batch_upload.py", "publish", "--accounts=fb01,fb03"]), \
                patch("batch_upload.subprocess.run") as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(batch.main(), 1)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
