import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import add_fb_accounts as app


class AdditionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patcher = patch.object(app, "ROOT", self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.config = {"other": {"keep": True}, "targets": []}
        self.registry = {"custom": "retain", "accounts": []}
        for number in range(1, 8):
            row = {"account": "fb%02d" % number, "target": "page01", "type": "page",
                   "name": "old %d" % number, "url": "https://www.facebook.com/old%d" % number,
                   "enabled": True, "prepared_at": "old-prepare", "excluded_files": ["old.mp4"]}
            self.config["targets"].append(row)
            self.registry["accounts"].append(dict(row))
        self.write("upload_config.json", self.config)
        self.write("account_registry.json", self.registry)
        (self.root / "logs").mkdir()
        (self.root / "logs/publish_state.json").write_bytes(b'{"existing": "retain bytes"}')
        self.mapping = {"accounts": [self.mapping_for(a, i % 2 == 0) for i, a in enumerate(app.SLOTS)]}

    def write(self, name, document):
        app.upload.save_json(self.root / name, document)

    def mapping_for(self, account, personal=False):
        return {"account": account, "type": "personal" if personal else "page",
                "name": account + " Name", "url": "https://www.facebook.com/new" + account}

    def plan(self, mappings=None):
        return app.registration_plan(*app.local_documents(), mappings or self.mapping)

    def test_reserve_all_six_without_changing_old_data(self):
        old = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        with app.locked():
            app.reserve(app.SLOTS)
        for path, content in old.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertTrue(all((self.root / "profiles" / a).is_dir() for a in app.SLOTS))
        self.assertFalse((self.root / "logs/upload.lock").exists())

    def test_repeated_reserve_retains_login_profile(self):
        app.reserve(app.SLOTS)
        local_login = self.root / "profiles/fb08/fixture-login"
        local_login.write_bytes(b"fixture-only")
        app.reserve(app.SLOTS)
        self.assertEqual(local_login.read_bytes(), b"fixture-only")

    def test_unclaimed_profile_blocks_whole_request(self):
        (self.root / "profiles/fb13").mkdir(parents=True)
        with self.assertRaises(ValueError):
            app.reserve(app.SLOTS)
        self.assertFalse((self.root / "profiles/fb08").exists())
        self.assertFalse((self.root / app.MANIFEST).exists())

    def test_existing_target_cannot_be_replaced_even_with_marker(self):
        app.reserve(app.SLOTS)
        self.config["targets"].append(self.mapping_for("fb08"))
        self.write("upload_config.json", self.config)
        with self.assertRaises(ValueError):
            app.reserve(app.SLOTS)
        with self.assertRaises(ValueError):
            self.plan()

    def test_mixed_registration_adds_six_disabled_preserving_original_seven(self):
        app.reserve(app.SLOTS)
        planned, registry, manifest = self.plan()
        self.assertEqual(len(planned["targets"]), 13)
        self.assertEqual(planned["targets"][:7], self.config["targets"])
        self.assertEqual(registry["accounts"][:7], self.registry["accounts"])
        self.assertEqual(planned["other"], self.config["other"])
        for row in planned["targets"][7:]:
            self.assertFalse(row["enabled"])
            self.assertNotIn("prepared_at", row)
            self.assertTrue(row["ai_label"])
            if row["type"] == "personal":
                self.assertEqual(row["workflow"], "personal_recording_v1")
                self.assertEqual(row["target"], "personal")
        self.assertTrue(all(s["state"] == "registered" for s in manifest["slots"].values()))

    def test_registration_backup_state_preservation_and_idempotence(self):
        app.reserve(app.SLOTS)
        self.write("mapping.json", self.mapping)
        old = (self.root / "upload_config.json").read_bytes()
        state = (self.root / "logs/publish_state.json").read_bytes()
        app.register(self.root / "mapping.json")
        backups = list((self.root / "backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "upload_config.json").read_bytes(), old)
        self.assertTrue((self.root / "videos/fb08/personal/inbox").is_dir())
        self.assertTrue((self.root / "videos/fb09/page01/inbox").is_dir())
        config = app.upload.read_json(self.root / "upload_config.json", {})
        config["targets"][7].update({"enabled": True, "prepared_at": "later-check"})
        self.write("upload_config.json", config)
        before = {p: p.read_bytes() for p in self.root.glob("*.json")}
        app.register(self.root / "mapping.json")
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual((self.root / "logs/publish_state.json").read_bytes(), state)
        self.assertEqual(list((self.root / "backups").iterdir()), backups)

    def test_partial_save_failure_restores_all_documents(self):
        app.reserve(app.SLOTS)
        self.write("mapping.json", self.mapping)
        before = {p: p.read_bytes() for p in self.root.glob("*.json")}
        original_save = app.upload.save_json
        calls = []

        def fail_second(path, data):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("fixture write failure")
            original_save(path, data)

        with patch.object(app.upload, "save_json", side_effect=fail_second):
            with self.assertRaises(OSError):
                app.register(self.root / "mapping.json")
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_existing_lock_retained_and_partial_owned_lock_released(self):
        lock = self.root / "logs/upload.lock"
        lock.write_text("fixture-other-task")
        with self.assertRaises(RuntimeError):
            with app.locked():
                self.fail("must not acquire")
        self.assertEqual(lock.read_text(), "fixture-other-task")
        self.assertFalse((self.root / "logs/batch.lock").exists())

    def test_duplicate_urls_rejected_across_new_and_old(self):
        app.reserve(app.SLOTS)
        for url in (self.mapping["accounts"][0]["url"], self.config["targets"][0]["url"]):
            mapping = copy.deepcopy(self.mapping)
            mapping["accounts"][1]["url"] = url
            with self.assertRaises(ValueError):
                self.plan(mapping)

    def test_replacement_identity_rejected_after_registration(self):
        app.reserve(app.SLOTS)
        planned = self.plan()
        for name, document in zip(("upload_config.json", "account_registry.json", app.MANIFEST), planned):
            self.write(name, document)
        mapping = copy.deepcopy(self.mapping)
        mapping["accounts"][0]["name"] = "changed"
        with self.assertRaises(ValueError):
            self.plan(mapping)

    def test_invalid_mapping_does_not_mutate_documents(self):
        app.reserve(app.SLOTS)
        for field, value in (("account", "fb01"), ("account", "../outside"),
                             ("type", "other"), ("url", "https://example.com/user"),
                             ("name", ""), ("password", "never-accepted")):
            with self.subTest(field=field, value=value):
                mapping = copy.deepcopy(self.mapping)
                mapping["accounts"][0][field] = value
                original = app.local_documents()
                with self.assertRaises(ValueError):
                    app.registration_plan(*original, mapping)
                self.assertEqual(original, app.local_documents())

    def test_shortcuts_have_distinct_existing_profile_paths_and_no_shell_code(self):
        self.root = self.root / "space ` $() 名称"
        with patch.object(app, "ROOT", self.root):
            items = app.shortcut_items(app.SLOTS, Path("C:/Program Files/Chrome/chrome.exe"))
        self.assertEqual(len({item["arguments"] for item in items}), 6)
        for account, item in zip(app.SLOTS, items):
            self.assertIn(str(self.root / "profiles" / account), item["arguments"])
            self.assertTrue(item["path"].endswith(account + " 登录.lnk"))
            self.assertIn("--no-first-run", item["arguments"])
        with patch.object(app.subprocess, "run") as run:
            app.write_shortcuts(items)
        args, kwargs = run.call_args
        self.assertNotIn(str(self.root), args[0][-1])
        self.assertEqual(json.loads(kwargs["input"]), items)
        self.assertNotIn("shell", kwargs)

    def test_prepare_nonwindows_makes_no_changes(self):
        with patch.object(app.sys, "platform", "linux"):
            with self.assertRaises(RuntimeError):
                app.prepare(app.SLOTS)
        self.assertFalse((self.root / app.MANIFEST).exists())

    def test_only_requested_new_slots_allowed(self):
        self.assertEqual(app.parse_accounts("fb08,fb13"), ["fb08", "fb13"])
        for value in ("", "fb01", "fb08,fb08", "fb14", "../profiles", "fb08, fb09"):
            with self.assertRaises(ValueError):
                app.parse_accounts(value)


if __name__ == "__main__":
    unittest.main()
