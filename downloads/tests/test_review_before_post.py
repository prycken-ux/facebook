"""The exact selected file must be reviewed in the same composer before Post."""
import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fb_upload as upload


class ReviewBeforePostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.entry = dict(account='fb07', target='personal', type='personal', workflow='personal_recording_v1',
                          name='Example Person', url='https://www.facebook.com/profile.php?id=1007',
                          enabled=True, prepared_at='checked')
        self.folder = upload.inbox_for(self.entry)
        self.folder.mkdir(parents=True)
        self.video = self.make_file('2026-10-15_01.mp4', b'actual fifteen fixture')
        self.old = self.make_file('2026-10-14_01.mp4', b'different fourteen fixture')
        self.state_path = self.root / 'logs/publish_state.json'
        self.state = {}
        self.page = MagicMock()
        self.context = MagicMock()
        self.context.pages = [self.page]
        self.button = MagicMock()
        upload.save_json(upload.CONFIG, {'targets': [self.entry]})

    def make_file(self, name, data):
        video = self.folder / name
        video.write_bytes(data)
        caption = video.with_suffix('.txt')
        caption.write_text('Fixture caption')
        for path in (video, caption):
            os.utime(path, (time.time()-120, time.time()-120))
        return video

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def run_review(self, answer, identity_error=None):
        with patch('playwright.sync_api.sync_playwright'), \
                patch.object(upload, 'launch_context', return_value=self.context) as launch, \
                patch.object(upload, 'prepare_reel', return_value=(self.button, {})) as prepare, \
                patch.object(upload, 'install_receipt_watch'), \
                patch.object(upload, 'recheck_publish_identity', side_effect=identity_error), \
                patch.object(upload, 'wait_for_receipt', return_value='Your reel is published.'), \
                patch('builtins.input', side_effect=answer):
            upload.run_entry(self.entry, self.state, self.state_path, True,
                             filename=self.video.name, review_before_post=True)
        return launch, prepare

    def test_post_waits_for_review_and_uses_same_composer_and_named_file(self):
        def approve(prompt):
            self.button.click.assert_not_called()
            self.assertIn('POST', prompt)
            self.assertEqual(next(iter(upload.read_json(self.state_path, {}).values()))['status'], 'preparing')
            return 'POST'
        launch, prepare = self.run_review(approve)
        launch.assert_called_once()
        prepare.assert_called_once()
        self.assertIs(prepare.call_args.args[0], self.page)
        self.assertEqual(prepare.call_args.args[2], self.video)
        self.button.click.assert_called_once()
        row = next(iter(self.state.values()))
        self.assertEqual(row['status'], 'published')
        self.assertEqual(row['preview_review_method'], 'user_entered_POST')
        self.assertTrue((self.folder.parent / 'completed' / self.video.name).exists())
        self.assertTrue(self.old.exists())
        self.context.close.assert_called_once()

    def test_other_inputs_cancel_without_post_or_archive(self):
        for answer in ('', 'post', 'CANCEL'):
            with self.subTest(answer=answer):
                self.state.clear()
                with self.assertRaisesRegex(RuntimeError, '未输入 POST'):
                    self.run_review(lambda prompt: answer)
                self.button.click.assert_not_called()
                self.assertEqual(next(iter(self.state.values()))['status'], 'failed_before_post')
                self.assertTrue(self.video.exists())

    def test_interrupted_review_is_recorded_before_post_not_left_preparing(self):
        def interrupt(prompt):
            raise KeyboardInterrupt()
        with self.assertRaisesRegex(RuntimeError, '预览核对已取消'):
            self.run_review(interrupt)
        self.assertEqual(next(iter(self.state.values()))['status'], 'failed_before_post')
        self.button.click.assert_not_called()
        self.context.close.assert_called_once()

    def test_changed_source_during_review_stops_before_post(self):
        def change_source(prompt):
            self.video.write_bytes(b'replaced file during preview review')
            return 'POST'
        with self.assertRaisesRegex(RuntimeError, '源视频内容发生变化'):
            self.run_review(change_source)
        self.button.click.assert_not_called()
        self.assertEqual(next(iter(self.state.values()))['status'], 'failed_before_post')

    def test_identity_is_rechecked_after_review_before_click(self):
        with self.assertRaisesRegex(RuntimeError, 'changed actor'):
            self.run_review(lambda prompt: 'POST', identity_error=RuntimeError('changed actor'))
        self.button.click.assert_not_called()
        self.assertEqual(next(iter(self.state.values()))['status'], 'failed_before_post')

    def test_cli_review_requires_named_publish(self):
        for args in (['prepare', '--review-before-post'], ['publish', '--review-before-post']):
            with self.subTest(args=args), patch('sys.argv', ['fb_upload.py'] + args), self.assertRaises(SystemExit) as raised:
                upload.main()
            self.assertEqual(raised.exception.code, 2)
        self.assertFalse(self.state_path.exists())

    def test_retry_backs_up_review_history_without_modifying_fourteen_success(self):
        key = upload.job_key(self.entry, self.video)
        old_key = upload.job_key(self.entry, self.old)
        self.state = {key: dict(account='fb07', target='personal', status='needs_review', video=str(self.video), error='old receipt timeout'),
                      old_key: dict(account='fb07', target='personal', status='published', video=str(self.old), permalink='https://www.facebook.com/reel/100014')}
        upload.save_json(self.state_path, self.state)
        previous = self.state_path.read_bytes()
        with patch('sys.argv', ['fb_upload.py', 'retry', '--job', key, '--verified-absent']):
            self.assertEqual(upload.main(), 0)
        self.assertEqual(upload.read_json(self.state_path, {}), {old_key: self.state[old_key]})
        backup = next((self.root / 'backups').glob('retry-*/publish_state.json'))
        self.assertEqual(backup.read_bytes(), previous)
        self.assertTrue(self.video.exists())
        self.assertTrue(self.old.exists())

    def test_recording_fourteen_does_not_mark_fifteen_as_published(self):
        key = upload.job_key(self.entry, self.video)
        self.state[key] = dict(account='fb07', target='personal', status='needs_review', video=str(self.video))
        upload.save_json(self.state_path, self.state)
        old_key = upload.record_manual_post(self.entry, self.state, self.state_path, self.old,
                                           'https://www.facebook.com/reel/1823700082081273')
        self.assertNotEqual(key, old_key)
        self.assertEqual(self.state[key]['status'], 'needs_review')
        self.assertEqual(self.state[old_key]['status'], 'published')
        self.assertEqual(self.state[old_key]['video'], str(self.old))


if __name__ == '__main__':
    unittest.main()
