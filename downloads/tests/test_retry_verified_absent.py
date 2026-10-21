import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import add_fb_accounts
import fb_upload as upload
import retry_verified_absent as retry


class VerifiedRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for module in (upload, add_fb_accounts):
            self.stack.enter_context(patch.object(module, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root/'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry = dict(account='fb03', target='personal', type='personal', name='Lisa Mills',
            url='https://www.facebook.com/profile.php?id=100041479541385', enabled=True,
            prepared_at='existing', workflow='personal_recording_v1', ai_label=True)
        upload.save_json(upload.CONFIG, {'targets': [self.entry]})
        self.video = upload.inbox_for(self.entry)/'k3.mp4'
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b'confirmed absent video fixture')
        self.caption = self.video.with_suffix('.txt')
        self.caption.write_text('Same approved caption')
        for path in (self.video, self.caption):
            os.utime(path, (time.time()-120, time.time()-120))
        self.key = upload.job_key(self.entry, self.video)
        self.old = dict(account='fb03', target='personal', url=self.entry['url'], status='needs_review',
                        video=str(self.video), caption=str(self.caption), created='original-attempt')
        self.state = {self.key: self.old,
            'other-success': dict(account='fb01', target='page01', status='published'),
            'unconfirmed-fb10': dict(account='fb10', target='personal', status='needs_review')}
        self.state_path = self.root/'logs/publish_state.json'
        upload.save_json(self.state_path, self.state)

    def run_retry(self):
        return retry.retry_absent('fb03', verified_absent=True)

    def test_success_retries_exact_pair_with_backup_and_preserves_all_other_jobs(self):
        original = self.state_path.read_bytes()
        def publish(entry, state, path, publish, **options):
            self.assertEqual(options, dict(filename='k3.mp4', ai_label_override=False))
            self.assertEqual(state, {key: value for key, value in self.state.items() if key != self.key})
            self.assertTrue(publish)
            state[self.key] = {**self.old, 'status': 'published', 'created': 'new-attempt'}
            upload.save_json(path, state)
            return True
        with patch.object(upload, 'check_identity') as check, patch.object(upload, 'run_entry', side_effect=publish):
            self.assertTrue(self.run_retry())
        check.assert_called_once_with(self.entry)
        current = upload.read_json(self.state_path, {})
        self.assertEqual(current[self.key]['status'], 'published')
        self.assertEqual(current['unconfirmed-fb10'], self.state['unconfirmed-fb10'])
        self.assertEqual(current['other-success'], self.state['other-success'])
        backup = next((self.root/'backups').iterdir())
        self.assertEqual((backup/'publish_state.json').read_bytes(), original)
        self.assertEqual(upload.read_json(backup/'assertion.json', {})['original_record'], self.old)
        self.assertEqual(self.caption.read_text(), 'Same approved caption')

    def test_identity_failure_never_clears_pending_record(self):
        original = self.state_path.read_bytes()
        with patch.object(upload, 'check_identity', side_effect=RuntimeError('profile locked')), \
                patch.object(upload, 'run_entry') as run, self.assertRaises(RuntimeError):
            self.run_retry()
        run.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), original)
        self.assertFalse((self.root/'backups').exists())

    def test_changed_content_or_missing_caption_refuses_before_browser(self):
        for failure in ('content', 'caption'):
            original = self.state_path.read_bytes()
            if failure == 'content':
                self.video.write_bytes(b'replacement video')
            else:
                self.video.write_bytes(b'confirmed absent video fixture')
                os.utime(self.video, (time.time()-120, time.time()-120))
                self.caption.unlink()
            with self.subTest(failure=failure), patch.object(upload, 'check_identity') as check, \
                    self.assertRaises(ValueError):
                self.run_retry()
            check.assert_not_called()
            self.assertEqual(self.state_path.read_bytes(), original)

    def test_no_verification_or_success_proof_does_not_reset_record(self):
        with self.assertRaises(ValueError):
            retry.retry_absent('fb03')
        for proof in ({'permalink': 'https://www.facebook.com/reel/123'}, {'success_message': 'published'}):
            upload.save_json(self.state_path, {**self.state, self.key: {**self.old, **proof}})
            before = self.state_path.read_bytes()
            with self.subTest(proof=proof), self.assertRaises(ValueError):
                self.run_retry()
            self.assertEqual(self.state_path.read_bytes(), before)

    def test_an_early_launch_failure_restores_original_guard(self):
        with patch.object(upload, 'check_identity'), \
                patch.object(upload, 'run_entry', side_effect=RuntimeError('launch failed')), \
                self.assertRaises(RuntimeError):
            self.run_retry()
        self.assertEqual(upload.read_json(self.state_path, {}), self.state)

    def test_new_uncertain_attempt_is_preserved_instead_of_restoring_old_attempt(self):
        def uncertain(entry, state, path, publish, **options):
            state[self.key] = {**self.old, 'created': 'new-attempt', 'error': 'new timeout'}
            upload.save_json(path, state)
            raise upload.ReceiptNeedsReview('new timeout')
        with patch.object(upload, 'check_identity'), patch.object(upload, 'run_entry', side_effect=uncertain), \
                self.assertRaises(upload.ReceiptNeedsReview):
            self.run_retry()
        self.assertEqual(upload.read_json(self.state_path, {})[self.key]['created'], 'new-attempt')

    def test_multiple_pending_jobs_or_changed_target_refuse_without_changes(self):
        for changes in ({'second-pending': dict(self.old)},
                        {self.key: {**self.old, 'url': 'https://www.facebook.com/profile.php?id=222'}}):
            upload.save_json(self.state_path, {**self.state, **changes})
            before = self.state_path.read_bytes()
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.run_retry()
            self.assertEqual(self.state_path.read_bytes(), before)

    def test_active_lock_is_not_removed(self):
        lock = self.root/'logs/upload.lock'
        lock.write_bytes(b'other process')
        with self.assertRaises(RuntimeError):
            self.run_retry()
        self.assertEqual(lock.read_bytes(), b'other process')
        self.assertFalse((self.root/'logs/batch.lock').exists())

    def test_published_job_is_skipped_without_browser_or_mutation(self):
        upload.save_json(self.state_path, {**self.state, self.key: {**self.old, 'status': 'published'}})
        before = self.state_path.read_bytes()
        with patch.object(upload, 'check_identity') as check:
            self.assertFalse(self.run_retry())
        check.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
