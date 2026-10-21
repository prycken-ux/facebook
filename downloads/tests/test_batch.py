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

    def test_opt_in_continues_after_receipt_review_to_next_account(self):
        with patch("batch_upload.subprocess.run", side_effect=[SimpleNamespace(returncode=3), SimpleNamespace(returncode=0)]) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            results = batch.execute(self.entries, "publish", continue_on_review=True)
        self.assertEqual(run.call_count, 2)
        self.assertEqual([row["exit_code"] for row in results], [3, 0])
        self.assertEqual([row["account"] for row in results], ["fb01", "fb02"])

    def test_default_still_stops_at_receipt_review(self):
        with patch("batch_upload.subprocess.run", return_value=SimpleNamespace(returncode=3)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            batch.execute(self.entries, "publish")
        self.assertEqual(run.call_count, 1)

    def test_opt_in_still_stops_on_operational_or_lock_error(self):
        for code in (1, 2):
            with self.subTest(code=code), \
                    patch("batch_upload.subprocess.run", return_value=SimpleNamespace(returncode=code)) as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                batch.execute(self.entries, "publish", continue_on_review=True)
            self.assertEqual(run.call_count, 1)

    def test_opt_in_skips_existing_review_target_without_modifying_record(self):
        state = {"job": {"account": "fb01", "target": "page01", "status": "needs_review", "error": "old timeout"}}
        original = repr(state)
        with contextlib.redirect_stdout(io.StringIO()), patch.object(batch.upload, "named_job", return_value=None) as named:
            selected, errors = batch.select_targets({"targets": self.entries}, ["fb01", "fb02"], "publish", state,
                                                     filename="today.mp4", continue_on_review=True)
        self.assertEqual(errors, [])
        self.assertEqual([entry["account"] for entry in selected], ["fb02"])
        self.assertEqual(named.call_count, 1)
        self.assertEqual(named.call_args.args[0]["account"], "fb02")
        self.assertEqual(repr(state), original)

    def test_opt_in_does_not_skip_preparing_or_posting_targets(self):
        for status in ("preparing", "posting"):
            state = {"job": {"account": "fb01", "target": "page01", "status": status}}
            _, errors = batch.select_targets({"targets": self.entries}, ["fb01", "fb02"], "publish", state,
                                              continue_on_review=True)
            self.assertTrue(errors)

    def test_opt_in_does_not_bypass_prepare_or_enable(self):
        self.entries[1].pop("prepared_at")
        self.entries[1]["enabled"] = False
        _, errors = batch.select_targets({"targets": self.entries}, ["fb01", "fb02"], "publish", {},
                                          continue_on_review=True)
        self.assertTrue(any("prepare" in error for error in errors))
        self.assertTrue(any("启用" in error for error in errors))

    def test_batch_exit_still_reports_review_after_continuing(self):
        with patch.object(batch.upload, "read_json", side_effect=[{"targets": self.entries}, {}]), \
                patch("sys.argv", ["batch_upload.py", "publish", "--accounts=fb01,fb02", "--continue-on-review"]), \
                patch("batch_upload.subprocess.run", side_effect=[SimpleNamespace(returncode=3), SimpleNamespace(returncode=0)]) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(batch.main(), 3)
        self.assertEqual(run.call_count, 2)
        self.assertFalse((self.root / "logs/batch.lock").exists())

    def test_target_filter_selects_personal_without_unprepared_page_or_its_review(self):
        personal = dict(account='fb01', target='personal', type='personal', name='Person',
                        workflow='personal_recording_v1', url='https://www.facebook.com/person1',
                        prepared_at='checked', enabled=True)
        page = dict(self.entries[0], enabled=False)
        page.pop('prepared_at')
        state = {'page-job': dict(account='fb01', target='page01', status='needs_review')}
        config = {'targets': [personal, page]}
        selected, errors = batch.select_targets(config, ['fb01'], 'publish', state,
            target_filter={('fb01', 'personal')})
        self.assertEqual(errors, [])
        self.assertEqual(selected, [personal])
        with patch.object(batch.upload, 'read_json', side_effect=[config, state]), \
                patch('sys.argv', ['batch_upload.py', 'publish', '--accounts=fb01',
                                  '--targets=fb01/personal', '--continue-on-review']), \
                patch('batch_upload.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(batch.main(), 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][-2:], ['--target', 'personal'])

    def test_filter_does_not_fall_back_to_another_target(self):
        selected, errors = batch.select_targets({'targets': self.entries}, ['fb01'], 'plan', {},
                                               target_filter={('fb01', 'missing')})
        self.assertEqual(selected, [])
        self.assertTrue(errors)

    def test_invalid_target_filters_are_refused(self):
        self.assertIsNone(batch.parse_target_filter(None, ['fb01']))
        for value in ('', 'fb01', 'fb01/../page', 'fb02/page01',
                      'fb01/page01,fb01/page01'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                batch.parse_target_filter(value, ['fb01'])
        with self.assertRaises(ValueError):
            batch.parse_target_filter('fb01/page01', ['fb01', 'fb02'])
        self.assertEqual(batch.parse_target_filter('fb01/personal,fb01/page01', ['fb01']),
                         {('fb01', 'personal'), ('fb01', 'page01')})


if __name__ == "__main__":
    unittest.main()
