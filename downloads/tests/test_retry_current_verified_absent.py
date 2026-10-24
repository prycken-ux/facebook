import copy
import os
import time
import unittest
from unittest.mock import MagicMock, patch

import fb_upload as upload
import retry_current_verified_absent as retry
import test_publish_fourteen_current as fixtures


class CurrentAbsenceTests(unittest.TestCase):
    def setUp(self):
        fixtures.FourteenTests.setUp(self)
        self.targets = [('fb03', 'personal'), ('fb06', 'page01'), ('fb12', 'page01')]
        self.rows = []
        self.selected_keys = []
        for entry, key, video in zip(self.entries, self.keys, self.videos):
            pair = (entry['account'], entry['target'])
            status = {self.targets[0]: 'preparing', self.targets[1]: 'needs_review', self.targets[2]: 'posting'}.get(pair, 'published')
            self.state[key] = dict(account=pair[0], target=pair[1], status=status, url=entry['url'],
                                   video=str(video), created='2026-10-23T17:00:00+08:00', error='old interrupted task')
            if pair in self.targets:
                self.selected_keys.append(key)
            else:
                self.state[key]['success_message'] = 'original success proof'
            video.with_suffix('.txt').write_text('Same approved caption\nhttps://www.amazon.com/?x=1&y=2')
            for path in (video, video.with_suffix('.txt')):
                os.utime(path, (time.time() - 120, time.time() - 120))
            self.rows.append(dict(account=pair[0], target=pair[1], key=key, filename=video.name, status='unrecorded', eligible=True))
        self.path = self.root / 'logs/current-audit-20261023-165040.json'
        self.round = dict(schema='fourteen-current-publication-v1', phase='attempts_finished', ai_label='off',
                          created='2026-10-23T16:50:40+08:00', rows=self.rows, results=[])
        upload.save_json(self.path, self.round)
        upload.save_json(self.state_path, self.state)
        self.claims_path = self.root / 'logs/verified-current-absence-claims.json'

    def tearDown(self):
        fixtures.FourteenTests.tearDown(self)

    def browser(self, failure=None):
        from contextlib import ExitStack
        stack = ExitStack()
        browser = MagicMock()
        browser.pages = [MagicMock()]
        stack.enter_context(patch.object(upload, 'check_identity'))
        stack.enter_context(patch('playwright.sync_api.sync_playwright'))
        stack.enter_context(patch.object(upload, 'launch_context', return_value=browser))
        stack.enter_context(patch.object(upload, 'prepare_reel', return_value=(MagicMock(), {})))
        stack.enter_context(patch.object(upload, 'recheck_publish_identity'))
        stack.enter_context(patch.object(upload, 'install_receipt_watch'))
        stack.enter_context(patch.object(upload, 'wait_for_receipt', return_value='Your reel is published.', side_effect=failure))
        return stack

    def test_exact_three_retry_all_original_pending_phases_and_preserve_other_rows_and_old_reviews(self):
        before = self.state_path.read_bytes()
        with self.browser():
            self.assertEqual(retry.run(self.targets, True), 0)
        actual = upload.read_json(self.state_path, {})
        for key, old in self.state.items():
            if key in self.selected_keys:
                self.assertEqual(actual[key]['status'], 'published')
            else:
                self.assertEqual(actual[key], old)
        for index in (2, 5, 11):
            self.assertFalse(self.videos[index].exists())
            self.assertTrue((self.videos[index].parent.parent / 'completed' / self.videos[index].name).exists())
        backups = sorted((self.root / 'backups').glob('verified-current-absent-*'))
        self.assertEqual(len(backups), 3)
        self.assertEqual((backups[0] / 'publish_state.json').read_bytes(), before)
        self.assertEqual(len(upload.read_json(self.path, {})['resume_results']), 3)

    def test_unknown_new_result_consumes_assertion_and_repeat_does_not_send_again(self):
        with self.browser(upload.ReceiptNeedsReview('new receipt unknown')):
            self.assertEqual(retry.run(self.targets, True), 3)
        after = self.state_path.read_bytes()
        with patch.object(upload, 'check_identity') as identity, patch.object(upload, 'run_entry') as run:
            self.assertEqual(retry.run(self.targets, True), 3)
        identity.assert_not_called()
        run.assert_not_called()
        self.assertEqual(after, self.state_path.read_bytes())
        self.assertTrue(all(r['phase'] == 'consumed' for r in upload.read_json(self.claims_path, {}).values()))

    def test_identity_failure_never_removes_original_guard(self):
        before = self.state_path.read_bytes()
        with patch.object(upload, 'check_identity', side_effect=RuntimeError('profile busy')):
            with self.assertRaisesRegex(RuntimeError, 'profile busy'):
                retry.retry_one(self.targets[0], self.path, self.round, True)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertFalse(self.claims_path.exists())
        self.assertFalse((self.root / 'backups').exists())

    def test_replacement_launch_failure_restores_record_and_does_not_consume_assertion(self):
        before = self.state_path.read_bytes()
        with patch.object(upload, 'check_identity'), patch.object(upload, 'launch_context', side_effect=RuntimeError('launch failed')):
            with self.assertRaisesRegex(RuntimeError, 'launch failed'):
                retry.retry_one(self.targets[0], self.path, self.round, True)
        self.assertEqual(upload.read_json(self.state_path, {}), self.state)
        self.assertEqual(next(iter(upload.read_json(self.claims_path, {}).values()))['phase'], 'not_started')
        with self.browser():
            retry.retry_one(self.targets[0], self.path, self.round, True)
        self.assertEqual(upload.read_json(self.state_path, {})[self.selected_keys[0]]['status'], 'published')

    def test_absence_assertion_and_actual_pending_state_are_required(self):
        with self.assertRaisesRegex(ValueError, '核实'):
            retry.run(self.targets, False)
        row = self.rows[2]
        for field in ('permalink', 'success_message', 'confirmation_method', 'confirmed_at'):
            old = dict(self.state[row['key']], **{field: 'proof'})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '成功证据'):
                retry.validate_record(self.entries[2], row, old)

    def test_wrong_file_hash_or_caption_stops_before_browser(self):
        before = self.state_path.read_bytes()
        self.videos[2].write_bytes(b'different new footage')
        os.utime(self.videos[2], (time.time() - 120, time.time() - 120))
        with patch.object(upload, 'check_identity') as identity:
            with self.assertRaisesRegex(ValueError, '指纹'):
                retry.retry_one(self.targets[0], self.path, self.round, True)
        identity.assert_not_called()
        self.assertEqual(before, self.state_path.read_bytes())
        self.videos[2].write_bytes(b'new content 3')
        self.videos[2].with_suffix('.txt').write_text('Other product caption')
        for path in (self.videos[2], self.videos[2].with_suffix('.txt')):
            os.utime(path, (time.time() - 120, time.time() - 120))
        with patch.object(upload, 'check_identity') as identity:
            with self.assertRaisesRegex(ValueError, '文案'):
                retry.retry_one(self.targets[0], self.path, self.round, True)
        identity.assert_not_called()
        self.assertEqual(before, self.state_path.read_bytes())

    def test_active_worker_lock_is_not_deleted(self):
        lock = self.root / 'logs/upload.lock'
        lock.write_text('active uploader')
        with self.assertRaises(RuntimeError):
            retry.retry_one(self.targets[0], self.path, self.round, True)
        self.assertEqual(lock.read_text(), 'active uploader')
        self.assertFalse((self.root / 'logs/batch.lock').exists())

    def test_interruption_after_removal_restores_only_guard_before_new_attempt(self):
        key = self.selected_keys[0]
        saved = copy.deepcopy(self.state[key])
        state = copy.deepcopy(self.state)
        del state[key]
        upload.save_json(self.state_path, state)
        upload.save_json(self.claims_path, {self.path.name + ':' + key + ':first-user-verification': dict(phase='reserved', original_record=saved)})
        with patch.object(upload, 'check_identity', side_effect=RuntimeError('stop after recovery')):
            with self.assertRaises(RuntimeError):
                retry.retry_one(self.targets[0], self.path, self.round, True)
        self.assertEqual(upload.read_json(self.state_path, {}), self.state)
        self.assertEqual(next(iter(upload.read_json(self.claims_path, {}).values()))['phase'], 'not_started')

    def test_interruption_with_new_task_does_not_restore_or_retry_old_guard(self):
        key = self.selected_keys[0]
        saved = copy.deepcopy(self.state[key])
        state = copy.deepcopy(self.state)
        state[key] = dict(saved, status='needs_review', created='new attempt')
        upload.save_json(self.state_path, state)
        upload.save_json(self.claims_path, {self.path.name + ':' + key + ':first-user-verification': dict(phase='reserved', original_record=saved)})
        with patch.object(upload, 'check_identity') as identity:
            self.assertFalse(retry.retry_one(self.targets[0], self.path, self.round, True))
        identity.assert_not_called()
        self.assertEqual(upload.read_json(self.state_path, {}), state)

    def test_fresh_explicit_confirmation_id_can_bind_a_new_verification(self):
        with self.browser(upload.ReceiptNeedsReview('first retry uncertain')):
            self.assertEqual(retry.run([self.targets[0]], True), 3)
        with self.browser():
            self.assertEqual(retry.run([self.targets[0]], True, confirmation_id='fresh-user-check-2'), 0)
        self.assertEqual(len(upload.read_json(self.claims_path, {})), 2)

    def test_confirmation_bound_to_another_round_cannot_be_applied(self):
        before = self.state_path.read_bytes()
        with patch.object(upload, 'check_identity') as identity:
            with self.assertRaisesRegex(ValueError, '批次不同'):
                retry.run(self.targets, True, round_start='2026-10-24T16:50:40')
        identity.assert_not_called()
        self.assertEqual(before, self.state_path.read_bytes())
        self.assertFalse(self.claims_path.exists())

    def test_source_filename_or_owner_mismatch_is_refused(self):
        row = self.rows[2]
        old = self.state[row['key']]
        for changed in (dict(old, account='fb99'), dict(old, video='other.mp4'), dict(old, url='https://www.facebook.com/profile.php?id=999')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                retry.validate_record(self.entries[2], row, changed)


if __name__ == '__main__':
    unittest.main()
