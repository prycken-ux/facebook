import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fb_upload as upload
import setup_personal as setup


class PersonalSetupTests(unittest.TestCase):
    def setUp(self):
        self.original = {"custom": "keep", "targets": [{"account": "fb02", "target": "page01", "type": "page",
                         "name": "Example Page", "url": "https://www.facebook.com/profile.php?id=2002",
                         "enabled": True, "prepared_at": "checked", "excluded_files": ["old.mp4"]}]}
        self.registry = {"accounts": [{"account": "fb03", "type": "personal", "name": "Example Person",
                                      "url": "https://www.facebook.com/profile.php?id=1003"}]}

    def test_merge_preserves_public_configuration_and_disables_new_personal_target(self):
        original = copy.deepcopy(self.original)
        result, _ = setup.merge(self.original, self.registry)
        self.assertEqual(self.original, original)
        self.assertEqual(result["targets"][0], original["targets"][0])
        self.assertEqual(result["custom"], "keep")
        personal = result["targets"][1]
        self.assertFalse(personal["enabled"])
        self.assertEqual(personal["target"], "personal")
        self.assertEqual(personal["workflow"], "personal_recording_v1")

    def test_changed_personal_destination_requires_new_prepare(self):
        config, _ = setup.merge(self.original, self.registry)
        config["targets"][1].update(enabled=True, prepared_at="old check")
        self.registry["accounts"][0]["url"] = "https://www.facebook.com/profile.php?id=1004"
        config, _ = setup.merge(config, self.registry)
        self.assertFalse(config["targets"][1]["enabled"])
        self.assertNotIn("prepared_at", config["targets"][1])

    def test_repeat_install_preserves_state_profiles_videos_and_existing_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload.save_json(root / "upload_config.json", self.original)
            upload.save_json(root / "account_registry.json", self.registry)
            upload.save_json(root / "logs" / "publish_state.json", {"job": {"status": "needs_review"}})
            profile = root / "profiles" / "fb03" / "fixture.txt"
            profile.parent.mkdir(parents=True)
            profile.write_text("private profile fixture")
            video = root / "videos" / "fb03" / "personal" / "inbox" / "new.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"existing video fixture")
            with patch.object(setup, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(setup.main(), 0)
                config = upload.read_json(root / "upload_config.json", {})
                config["targets"][1].update(enabled=True, prepared_at="new check")
                upload.save_json(root / "upload_config.json", config)
                self.assertEqual(setup.main(), 0)
            self.assertEqual(upload.read_json(root / "upload_config.json", {}), config)
            self.assertEqual(profile.read_text(), "private profile fixture")
            self.assertEqual(video.read_bytes(), b"existing video fixture")
            self.assertEqual(upload.read_json(root / "logs" / "publish_state.json", {}), {"job": {"status": "needs_review"}})
            self.assertEqual(len(list((root / "backups").iterdir())), 2)
            self.assertFalse((root / "logs" / "upload.lock").exists())

    def test_live_lock_is_not_deleted_or_bypassed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            lock = root / "logs" / "upload.lock"
            lock.write_text("other process")
            with patch.object(setup, "ROOT", root), self.assertRaises(RuntimeError):
                setup.main()
            self.assertEqual(lock.read_text(), "other process")
            self.assertFalse((root / "logs" / "batch.lock").exists())

    def test_unexpected_page_target_for_personal_account_is_not_overwritten(self):
        self.original["targets"][0]["account"] = "fb03"
        with self.assertRaises(ValueError):
            setup.merge(self.original, self.registry)


if __name__ == "__main__":
    unittest.main()
