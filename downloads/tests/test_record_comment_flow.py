import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fb_upload as upload
import record_comment_flow as recording


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch('sys.argv', ['record_comment_flow.py', '--account', 'fb01']))
        self.entry = dict(account='fb01', target='page01', type='page', name='Example Page',
                          url='https://www.facebook.com/profile.php?id=1001')
        upload.save_json(upload.CONFIG, dict(targets=[self.entry]))
        self.browser = MagicMock()
        self.page = MagicMock()
        self.page.url = self.entry['url']
        self.page.locator.return_value.count.return_value = 0
        self.page.locator.return_value.aria_snapshot.return_value = '- button "Reply"\n- textbox "Write a reply..."'
        self.browser.pages = [self.page]
        self.lock = self.root / 'logs/upload.lock'

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def test_identity_is_checked_before_inspector_without_media_or_state_changes(self):
        with patch.object(recording, 'sync_playwright'), \
                patch.object(upload, 'launch_context', return_value=self.browser) as launch, \
                patch.object(upload, 'ensure_identity') as identity, \
                patch.object(upload, 'require_english_interface'):
            self.page.pause.side_effect = lambda: identity.assert_called_once_with(self.page, self.entry)
            self.assertEqual(recording.main(), 0)
        launch.assert_called_once()
        self.page.pause.assert_called_once()
        self.browser.close.assert_called_once()
        self.assertFalse(self.lock.exists())
        self.assertFalse((self.root / 'videos').exists())
        self.assertFalse((self.root / 'logs/publish_state.json').exists())
        capture = list((self.root / 'logs/comment-recordings').iterdir())
        self.assertEqual(len(capture), 1)
        self.assertIn('Reply', (capture[0] / 'comments.aria.txt').read_text())
        metadata = upload.read_json(capture[0] / 'context.json', {})
        self.assertEqual(metadata['account'], 'fb01')
        self.assertEqual(metadata['view_url'], self.entry['url'])
        self.page.screenshot.assert_called_once()

    def test_identity_or_login_failure_never_starts_recording(self):
        with patch.object(recording, 'sync_playwright'), \
                patch.object(upload, 'launch_context', return_value=self.browser), \
                patch.object(upload, 'ensure_identity', side_effect=RuntimeError('identity mismatch')):
            self.assertEqual(recording.main(), 1)
        self.page.pause.assert_not_called()
        self.browser.close.assert_called_once()
        self.assertFalse(self.lock.exists())

    def test_existing_lock_is_untouched(self):
        self.lock.parent.mkdir()
        self.lock.write_text('12345')
        with patch.object(upload, 'launch_context') as launch:
            self.assertEqual(recording.main(), 2)
        launch.assert_not_called()
        self.assertEqual(self.lock.read_text(), '12345')

    def test_missing_or_ambiguous_account_does_not_launch(self):
        for entries in ([], [self.entry, self.entry]):
            upload.save_json(upload.CONFIG, dict(targets=entries))
            with patch.object(upload, 'launch_context') as launch:
                self.assertEqual(recording.main(), 1)
            launch.assert_not_called()
            self.assertFalse(self.lock.exists())

    def test_checkpoint_page_is_not_captured(self):
        self.page.url = 'https://www.facebook.com/checkpoint/'
        with self.assertRaises(RuntimeError):
            recording.save_comment_view(self.page, self.entry)
        self.assertFalse((self.root / 'logs/comment-recordings').exists())
        self.page.screenshot.assert_not_called()

    def test_visible_password_form_is_not_captured(self):
        self.page.locator.return_value.count.return_value = 1
        self.page.locator.return_value.nth.return_value.is_visible.return_value = True
        with self.assertRaisesRegex(RuntimeError, '登录页面'):
            recording.save_comment_view(self.page, self.entry)
        self.assertFalse((self.root / 'logs/comment-recordings').exists())

    def test_empty_snapshot_is_not_saved(self):
        self.page.locator.return_value.aria_snapshot.return_value = ''
        with self.assertRaisesRegex(RuntimeError, '有效页面结构'):
            recording.save_comment_view(self.page, self.entry)
        self.assertFalse((self.root / 'logs/comment-recordings').exists())


if __name__ == '__main__':
    unittest.main()
