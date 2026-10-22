import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import add_fb_accounts
import fb_upload as upload
import post_comment_plan as comments


class CommentPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(patch.object(add_fb_accounts, 'ROOT', self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry = dict(account='fb10', target='page01', type='page', name='Product Page',
                          url='https://www.facebook.com/profile.php?id=61595024556188', enabled=True, prepared_at='prepared')
        self.video = upload.inbox_for(self.entry) / '产品01.mp4'
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b'new product footage')
        self.video.with_suffix('.txt').write_text('Video caption')
        self.comment = self.video.with_suffix('.comment.txt')
        self.comment.write_text('Product A\nhttps://www.amazon.com/example?x=1&y=2', encoding='utf-8-sig')
        self.age()
        self.state_path = self.root / 'logs/publish_state.json'
        upload.save_json(upload.CONFIG, {'targets': [self.entry]})
        self.old = {'historical': dict(account='fb10', target='page01', video='old.mp4', status='published')}
        upload.save_json(self.state_path, self.old)
        self.key = upload.job_key(self.entry, self.video)

    def age(self):
        for path in self.video.parent.iterdir():
            os.utime(path, (time.time() - 120, time.time() - 120))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def run_upload(self, publish=True, failure=None):
        browser = MagicMock()
        browser.pages = [MagicMock()]
        button = MagicMock()
        state = upload.read_json(self.state_path, {})
        with patch('playwright.sync_api.sync_playwright'), \
             patch.object(upload, 'launch_context', return_value=browser), \
             patch.object(upload, 'prepare_reel', return_value=(button, {})), \
             patch.object(upload, 'recheck_publish_identity'), \
             patch.object(upload, 'install_receipt_watch'), \
             patch.object(upload, 'wait_for_receipt', return_value='Your reel is published.', side_effect=failure), \
             patch('builtins.input', return_value=''):
            result = upload.run_entry(self.entry, state, self.state_path, publish)
        return result, button

    def test_explicit_enable_does_not_touch_ledger_or_backfill_past_posts(self):
        before = self.state_path.read_bytes()
        settings = comments.configure(True)
        self.assertFalse(settings['automatic_send_enabled'])
        self.assertTrue(settings['future_only'])
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(comments.status(), [])

    def test_absent_or_disabled_configuration_keeps_old_upload_behavior(self):
        self.assertIsNone(comments.build_plan(self.entry, self.video, self.key))
        comments.configure(False)
        self.assertIsNone(comments.build_plan(self.entry, self.video, self.key))

    def test_per_video_text_is_frozen_independently_of_post_caption(self):
        comments.configure(True)
        plan = comments.build_plan(self.entry, self.video, self.key)
        self.comment.write_text('Other product text')
        self.assertEqual(plan['text'], 'Product A\nhttps://www.amazon.com/example?x=1&y=2')
        self.assertEqual(self.video.with_suffix('.txt').read_text(), 'Video caption')
        self.assertEqual(plan['video_job'], self.key)

    def test_same_comment_on_two_videos_still_creates_distinct_tasks(self):
        comments.configure(True)
        first = comments.build_plan(self.entry, self.video, self.key)
        other = self.video.with_name('产品02.mp4')
        other.write_bytes(b'other footage for same product')
        other.with_suffix('.comment.txt').write_text(self.comment_text())
        self.age()
        second = comments.build_plan(self.entry, other, upload.job_key(self.entry, other))
        self.assertEqual(first['text_sha256'], second['text_sha256'])
        self.assertNotEqual(first['video_job'], second['video_job'])

    def test_success_attaches_only_new_plan_and_archives_all_three_files(self):
        comments.configure(True)
        _, button = self.run_upload()
        button.click.assert_called_once()
        state = upload.read_json(self.state_path, {})
        self.assertEqual(state['historical'], self.old['historical'])
        self.assertEqual(state[self.key]['post_comment_plan']['text'], self.comment_text())
        archived = self.video.parent.parent / 'completed'
        for suffix in ('.mp4', '.txt', '.comment.txt'):
            self.assertTrue((archived / self.video.with_suffix(suffix).name).is_file())
        rows = comments.status()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'waiting_for_comment_ui_and_verified_video_link')
        self.assertFalse(upload.read_json(self.root / 'logs/post-comment-queue.json', {})['automatic_send_enabled'])

    def comment_text(self):
        return 'Product A\nhttps://www.amazon.com/example?x=1&y=2'

    def test_uncertain_video_is_not_a_ready_comment(self):
        comments.configure(True)
        with self.assertRaises(upload.ReceiptNeedsReview):
            self.run_upload(failure=upload.ReceiptNeedsReview('receipt timeout'))
        self.assertEqual(comments.status()[0]['status'], 'waiting_for_video_confirmation')
        self.assertTrue(self.comment.exists())

    def test_prepare_does_not_create_any_comment_plan(self):
        comments.configure(True)
        self.run_upload(publish=False)
        self.assertEqual(upload.read_json(self.state_path, {}), self.old)
        self.assertEqual(comments.status(), [])

    def test_missing_or_blank_comment_skips_only_comment(self):
        comments.configure(True)
        self.comment.unlink()
        self.assertIsNone(comments.build_plan(self.entry, self.video, self.key))
        self.comment.write_text('\n  ')
        self.age()
        self.assertIsNone(comments.build_plan(self.entry, self.video, self.key))

    def test_recent_comment_blocks_before_browser_or_post(self):
        comments.configure(True)
        self.comment.write_text('Just edited')
        with patch.object(upload, 'launch_context') as launch:
            with self.assertRaisesRegex(ValueError, '一分钟'):
                self.run_upload_without_mock()
        launch.assert_not_called()
        self.assertEqual(upload.read_json(self.state_path, {}), self.old)

    def run_upload_without_mock(self):
        return upload.run_entry(self.entry, upload.read_json(self.state_path, {}), self.state_path, True)

    def test_target_change_is_not_silently_applied(self):
        comments.configure(True)
        changed = dict(self.entry, url='https://www.facebook.com/profile.php?id=999999')
        with self.assertRaisesRegex(ValueError, '目标已变化'):
            comments.build_plan(changed, self.video, self.key)

    def test_collision_only_with_old_comment_keeps_all_three_together(self):
        comments.configure(True)
        folder = self.video.parent.parent / 'completed'
        folder.mkdir()
        old = folder / self.comment.name
        old.write_text('Old product comment')
        self.run_upload()
        self.assertEqual(old.read_text(), 'Old product comment')
        archived = list(folder.glob('*/' + self.video.name))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].with_suffix('.comment.txt').read_text(encoding='utf-8-sig'), self.comment_text())

    def test_manual_video_confirmation_preserves_frozen_comment_for_status(self):
        comments.configure(True)
        with self.assertRaises(upload.ReceiptNeedsReview):
            self.run_upload(failure=upload.ReceiptNeedsReview('timeout'))
        state = upload.read_json(self.state_path, {})
        state[self.key]['status'] = 'published'
        state[self.key]['confirmation_method'] = 'user_confirmed_existing_post_no_link'
        upload.save_json(self.state_path, state)
        self.assertEqual(comments.status()[0]['status'], 'waiting_for_comment_ui_and_verified_video_link')

    def test_tampered_frozen_text_does_not_enter_queue(self):
        comments.configure(True)
        self.run_upload()
        state = upload.read_json(self.state_path, {})
        state[self.key]['post_comment_plan']['text'] = 'different product'
        upload.save_json(self.state_path, state)
        with self.assertRaisesRegex(ValueError, '不一致'):
            comments.status()


if __name__ == '__main__':
    unittest.main()
