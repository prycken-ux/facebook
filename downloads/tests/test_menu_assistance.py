"""Opt-in assistance leaves the real browser available before file selection."""
import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fb_upload as upload


class MenuAssistanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.entry = dict(account='fb06', target='page01', type='page', name='Example Page',
                          url='https://www.facebook.com/profile.php?id=1006', enabled=True, prepared_at='checked')
        self.video = upload.inbox_for(self.entry) / '2026-10-16_01.mp4'
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b'actual selected fixture')
        self.video.with_suffix('.txt').write_text('fixture caption')
        for file in (self.video, self.video.with_suffix('.txt')):
            os.utime(file, (time.time() - 120, time.time() - 120))
        self.page = MagicMock()
        self.page.url = self.entry['url']
        self.proof = dict(method='page_actor_id_match')
        self.state = {}
        self.state_path = self.root / 'logs/publish_state.json'
        upload.save_json(upload.CONFIG, dict(targets=[self.entry]))

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def assist(self, answer='READY', error=None):
        with patch('builtins.input', side_effect=lambda prompt: answer), \
                patch.object(upload, 'recheck_publish_identity', side_effect=error) as identity:
            upload.assist_reel_entry(self.page, self.entry, self.video, self.proof)
        return identity

    def test_resume_requires_ready_and_rechecks_actor(self):
        identity = self.assist()
        identity.assert_called_once_with(self.page, self.entry, self.proof)

    def test_cancellation_and_interruptions_stop_before_actor_or_upload(self):
        with self.assertRaisesRegex(RuntimeError, '协助已取消'):
            self.assist('CANCEL')
        for error in (EOFError(), KeyboardInterrupt()):
            with patch('builtins.input', side_effect=error), self.assertRaisesRegex(RuntimeError, '协助已取消'):
                upload.assist_reel_entry(self.page, self.entry, self.video, self.proof)

    def test_blank_lines_and_stray_pasted_commands_keep_waiting_until_ready(self):
        with patch('builtins.input', side_effect=['', '  ', '& python status', 'ready', 'READY']) as answer, \
                patch.object(upload, 'recheck_publish_identity') as identity:
            upload.assist_reel_entry(self.page, self.entry, self.video, self.proof)
        self.assertEqual(answer.call_count, 5)
        identity.assert_called_once_with(self.page, self.entry, self.proof)

    def test_blanks_do_not_prevent_explicit_cancel(self):
        with patch('builtins.input', side_effect=['', 'CANCEL']), \
                patch.object(upload, 'recheck_publish_identity') as identity:
            with self.assertRaisesRegex(RuntimeError, '协助已取消'):
                upload.assist_reel_entry(self.page, self.entry, self.video, self.proof)
        identity.assert_not_called()

    def test_changed_source_while_browser_is_paused_is_rejected(self):
        def change(prompt):
            self.video.write_bytes(b'replacement during pause')
            return 'READY'
        with patch('builtins.input', side_effect=change), self.assertRaisesRegex(RuntimeError, '内容发生变化'):
            upload.assist_reel_entry(self.page, self.entry, self.video, self.proof)

    def test_changed_page_or_actor_stops_before_file_selection(self):
        self.page.url = 'https://www.facebook.com/profile.php?id=9999'
        with self.assertRaisesRegex(RuntimeError, '离开目标主页'):
            self.assist()
        self.page.url = self.entry['url']
        with self.assertRaisesRegex(RuntimeError, 'actor changed'):
            self.assist(error=RuntimeError('actor changed'))

    def test_cli_requires_exact_file_and_upload_action(self):
        for arguments in (['publish', '--pause-before-reel'],
                          ['status', '--pause-before-reel'],
                          ['check-identity', '--pause-before-reel']):
            with patch('sys.argv', ['fb_upload.py'] + arguments), self.assertRaises(SystemExit) as raised:
                upload.main()
            self.assertEqual(raised.exception.code, 2)
        self.assertFalse((self.root / 'logs/upload.lock').exists())

    def test_real_cli_forwards_assistance_and_preview_options(self):
        args = ['fb_upload.py', 'publish', '--account', 'fb06', '--target', 'page01',
                '--filename', self.video.name, '--pause-before-reel', '--review-before-post']
        with patch('sys.argv', args), patch.object(upload, 'run_entry', return_value=True) as run:
            self.assertEqual(upload.main(), 0)
        self.assertEqual(run.call_args.kwargs,
                         dict(filename=self.video.name, pause_before_reel=True, review_before_post=True))
        self.assertFalse((self.root / 'logs/upload.lock').exists())

    def test_canceled_assistance_records_failed_before_post_and_keeps_source(self):
        browser = MagicMock()
        browser.pages = [self.page]
        with patch('playwright.sync_api.sync_playwright'), \
                patch.object(upload, 'launch_context', return_value=browser), \
                patch.object(upload, 'prepare_reel', side_effect=RuntimeError('菜单协助已取消')) as prepare:
            with self.assertRaisesRegex(RuntimeError, '协助已取消'):
                upload.run_entry(self.entry, self.state, self.state_path, True,
                                 filename=self.video.name, pause_before_reel=True)
        self.assertTrue(prepare.call_args.kwargs['pause_before_reel'])
        self.assertEqual(next(iter(self.state.values()))['status'], 'failed_before_post')
        self.assertTrue(self.video.exists())
        browser.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
