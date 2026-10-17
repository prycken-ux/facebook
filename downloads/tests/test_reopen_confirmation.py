"""Only an explicitly retracted user-only success can be reopened."""
import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fb_upload as upload
import reopen_manual_confirmation as reopen


class ReopenConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry = dict(account='fb01', target='page01', type='page', name='Example Page',
                          url='https://www.facebook.com/profile.php?id=1001', enabled=True, prepared_at='checked')
        self.inbox = upload.inbox_for(self.entry)
        self.completed = self.inbox.parent / 'completed'
        self.completed.mkdir(parents=True)
        self.filename = '2026-10-16_01.mp4'
        self.video = self.completed / self.filename
        self.caption = self.video.with_suffix('.txt')
        self.video.write_bytes(b'exact sixteen video')
        self.caption.write_text('Actual caption\n#Example', encoding='utf-8')
        for file in (self.video, self.caption):
            os.utime(file, (time.time() - 120, time.time() - 120))
        self.key = upload.job_key(self.entry, self.video)
        self.state = {
            self.key: dict(account='fb01', target='page01', video=str(self.inbox / self.filename),
                           status='published', confirmation_method='user_confirmed_existing_post_no_link',
                           error='receipt timeout', confirmed_at='previous-user-confirmation'),
            'older-genuine-post': dict(account='fb01', target='page01', video='2026-10-15_01.mp4',
                                       status='published', confirmation_method='fresh_success_ui_and_composer_closed')}
        for index in range(2, 8):
            self.state[f'other-account-{index}'] = dict(account=f'fb0{index}', target='page01',
                video=self.filename, status='published', confirmation_method='fresh_success_ui_and_composer_closed')
        self.state_path = self.root / 'logs/publish_state.json'
        upload.save_json(self.state_path, self.state)
        upload.save_json(upload.CONFIG, dict(targets=[self.entry]))

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def reopen(self):
        return reopen.reopen_confirmation(self.entry, self.filename, verified_absent=True)

    def unchanged(self, action, message):
        before = self.state_path.read_bytes()
        original_media = self.video.read_bytes() if self.video.exists() else None
        with self.assertRaisesRegex((ValueError, RuntimeError), message):
            action()
        self.assertEqual(self.state_path.read_bytes(), before)
        if original_media is not None:
            self.assertEqual(self.video.read_bytes(), original_media)

    def test_requires_explicit_verified_absence(self):
        self.unchanged(lambda: reopen.reopen_confirmation(self.entry, self.filename), 'verified-absent')
        self.assertFalse((self.root / 'backups').exists())

    def test_reopens_only_exact_manual_record_with_state_and_media_audit(self):
        before = self.state_path.read_bytes()
        self.assertEqual(self.reopen(), self.key)
        state = upload.read_json(self.state_path, {})
        self.assertEqual(state, {key: value for key, value in self.state.items() if key != self.key})
        backup = next((self.root / 'backups').iterdir())
        self.assertEqual((backup / 'publish_state.json').read_bytes(), before)
        self.assertEqual((backup / 'media' / self.filename).read_bytes(), b'exact sixteen video')
        self.assertEqual((backup / ('completed-' + self.filename)).read_bytes(), b'exact sixteen video')
        audit = upload.read_json(backup / 'retraction.json', {})
        self.assertEqual(audit['original_record'], self.state[self.key])
        self.assertEqual(audit['assertion'], 'user_verified_absent')
        self.assertEqual((self.inbox / self.filename).read_bytes(), b'exact sixteen video')
        self.assertFalse(self.video.exists())
        self.assertFalse(self.caption.exists())
        self.assertIsNotNone(upload.named_job(self.entry, state, self.filename))

    def test_republication_can_archive_and_then_blocks_duplicates(self):
        self.reopen()
        state = upload.read_json(self.state_path, {})
        browser = MagicMock()
        browser.pages = [MagicMock()]
        button = MagicMock()
        with patch('playwright.sync_api.sync_playwright'), \
                patch.object(upload, 'launch_context', return_value=browser), \
                patch.object(upload, 'prepare_reel', return_value=(button, {})), \
                patch.object(upload, 'install_receipt_watch'), \
                patch.object(upload, 'recheck_publish_identity'), \
                patch.object(upload, 'wait_for_receipt', return_value='Your reel is published.'):
            upload.run_entry(self.entry, state, self.state_path, True, filename=self.filename)
        button.click.assert_called_once()
        self.assertTrue(self.video.exists())
        self.assertTrue(self.caption.exists())
        self.assertFalse((self.inbox / self.filename).exists())
        self.assertEqual(state[self.key]['confirmation_method'], 'fresh_success_ui_and_composer_closed')
        self.assertIsNone(upload.named_job(self.entry, state, self.filename))
        self.unchanged(self.reopen, '仅能撤销')

    def test_detected_receipt_or_permalink_can_never_be_reset(self):
        for changes in ({'confirmation_method': 'fresh_success_ui_and_composer_closed'},
                        {'success_message': 'Your reel is published.'},
                        {'permalink': 'https://www.facebook.com/reel/12345'}):
            with self.subTest(changes=changes):
                state = {**self.state, self.key: {**self.state[self.key], **changes}}
                upload.save_json(self.state_path, state)
                self.unchanged(self.reopen, '仅能撤销')
        self.assertFalse((self.root / 'backups').exists())

    def test_uncertain_or_failed_task_cannot_be_reset_by_this_helper(self):
        for status in ('needs_review', 'posting', 'preparing', 'failed_before_post'):
            with self.subTest(status=status):
                state = {**self.state, self.key: {**self.state[self.key], 'status': status}}
                upload.save_json(self.state_path, state)
                self.unchanged(self.reopen, '仅能撤销')

    def test_other_account_target_or_date_is_untouched(self):
        for change in ({'account': 'fb08'}, {'target': 'personal'}):
            wrong = dict(self.entry, **change)
            self.unchanged(lambda: reopen.reopen_confirmation(wrong, self.filename, True), '没有唯一|个人主页')
        self.unchanged(lambda: reopen.reopen_confirmation(self.entry, '2026-10-17_01.mp4', True), '没有唯一')

    def test_changed_video_identity_or_bytes_is_rejected(self):
        self.video.write_bytes(b'changed content')
        self.unchanged(self.reopen, '指纹不一致')
        self.assertFalse((self.root / 'backups').exists())

    def test_missing_empty_caption_and_conflicting_destination_stop_before_any_write(self):
        self.caption.write_text('   ')
        self.unchanged(self.reopen, '文案为空')
        self.caption.unlink()
        self.unchanged(self.reopen, '找不到完整')
        self.caption.write_text('caption')
        self.inbox.mkdir()
        (self.inbox / self.filename).write_bytes(b'different existing inbox media')
        self.unchanged(self.reopen, '同名文件内容冲突')
        self.assertFalse((self.root / 'backups').exists())

    def test_missing_video_does_not_relabel_success(self):
        self.video.unlink()
        self.unchanged(self.reopen, '找不到完整')

    def test_partial_prior_move_is_recoverable_without_overwriting(self):
        self.inbox.mkdir()
        self.video.rename(self.inbox / self.filename)
        self.reopen()
        self.assertTrue((self.inbox / self.filename).exists())
        self.assertTrue((self.inbox / self.caption.name).exists())
        self.assertNotIn(self.key, upload.read_json(self.state_path, {}))

    def test_ambiguous_same_filename_records_are_not_guessed(self):
        state = {**self.state, 'another-content-key': dict(self.state[self.key])}
        upload.save_json(self.state_path, state)
        self.unchanged(self.reopen, '没有唯一')

    def test_existing_equal_inbox_pair_is_kept_and_completed_names_are_freed(self):
        import shutil
        self.inbox.mkdir()
        for source in (self.video, self.caption):
            shutil.copy2(source, self.inbox / source.name)
        self.reopen()
        self.assertTrue((self.inbox / self.filename).exists())
        self.assertFalse(self.video.exists())
        self.assertFalse(self.caption.exists())

    def test_state_save_failure_preserves_blocking_record_and_media_then_can_resume(self):
        original_save = upload.save_json
        def fail_state(path, value):
            if path == self.state_path:
                raise OSError('state save failed')
            return original_save(path, value)
        before = self.state_path.read_bytes()
        with patch.object(upload, 'save_json', side_effect=fail_state), self.assertRaisesRegex(OSError, 'state save failed'):
            self.reopen()
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertTrue((self.inbox / self.filename).exists())
        self.assertTrue(next((self.root / 'backups').glob('*/media/' + self.filename)).exists())
        self.reopen()
        self.assertNotIn(self.key, upload.read_json(self.state_path, {}))

    def test_cli_respects_existing_lock_and_never_launches_browser(self):
        args = ['reopen_manual_confirmation.py', '--account', 'fb01', '--target', 'page01',
                '--filename', self.filename, '--verified-absent']
        lock = self.root / 'logs/upload.lock'
        lock.write_text('12345')
        before = self.state_path.read_bytes()
        with patch('sys.argv', args), patch.object(upload, 'launch_context') as launch:
            self.assertEqual(reopen.main(), 2)
            self.assertEqual(lock.read_text(), '12345')
            self.assertEqual(self.state_path.read_bytes(), before)
            lock.unlink()
            self.assertEqual(reopen.main(), 0)
        launch.assert_not_called()
        self.assertFalse(lock.exists())


if __name__ == '__main__':
    unittest.main()
