"""Numbered pairs retain their names, numeric ordering and content deduplication."""
import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fb_upload as upload


class NumberedQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry = dict(account='fb01', target='page01', type='page', name='Example Page',
                          url='https://www.facebook.com/profile.php?id=1001', enabled=True, prepared_at='checked')
        self.folder = upload.inbox_for(self.entry)
        self.folder.mkdir(parents=True)
        self.state_path = self.root / 'logs/publish_state.json'

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def pair(self, name, content=None):
        path = self.folder / name
        path.write_bytes(content if content is not None else ('video:' + name).encode())
        path.with_suffix('.txt').write_text('Original caption for ' + name, encoding='utf-8')
        for item in (path, path.with_suffix('.txt')):
            os.utime(item, (time.time() - 120, time.time() - 120))
        return path

    def test_numeric_names_are_queued_1_2_3_10_not_1_10_2(self):
        for name in ('10.mp4', '3.mp4', '1.mp4', '2.mp4'):
            self.pair(name)
        self.assertEqual([job[1].name for job in upload.pending_jobs(self.entry, {})],
                         ['1.mp4', '2.mp4', '3.mp4', '10.mp4'])

    def test_date_and_zero_padded_numeric_names_have_deterministic_order(self):
        names = ['2026-10-10_01.mp4', '2.mp4', '01.mp4', '2026-10-9_01.mp4', '1.mp4']
        self.assertEqual([p.name for p in sorted(map(Path, names), key=upload.queue_order)],
                         ['01.mp4', '1.mp4', '2.mp4', '2026-10-9_01.mp4', '2026-10-10_01.mp4'])

    def test_numbered_files_still_require_caption_and_skip_published_content(self):
        first = self.pair('1.mp4')
        self.pair('2.mp4').with_suffix('.txt').unlink()
        self.pair('3.mp4').with_suffix('.txt').write_text('')
        self.pair('10.mp4')
        state = {upload.job_key(self.entry, first): dict(status='published')}
        self.assertEqual([job[1].name for job in upload.pending_jobs(self.entry, state)], ['10.mp4'])

    def test_reusing_filename_with_new_contents_is_eligible_but_same_content_is_not(self):
        first = self.pair('1.mp4', b'old video')
        old_key = upload.job_key(self.entry, first)
        upload.archive(first, first.with_suffix('.txt'))
        state = {old_key: dict(account='fb01', target='page01', status='published')}
        self.pair('1.mp4', b'new video')
        self.assertEqual(len(list(upload.pending_jobs(self.entry, state))), 1)
        self.pair('2.mp4', b'old video')
        self.assertEqual([job[1].name for job in upload.pending_jobs(self.entry, state)], ['1.mp4'])

    def test_first_archive_retains_existing_flat_layout_and_source_names(self):
        video = self.pair('1.mp4')
        caption_bytes = video.with_suffix('.txt').read_bytes()
        target = upload.archive(video, video.with_suffix('.txt'))
        self.assertEqual(target, self.folder.parent / 'completed')
        self.assertEqual((target / '1.mp4').read_bytes(), b'video:1.mp4')
        self.assertEqual((target / '1.txt').read_bytes(), caption_bytes)

    def test_repeated_number_archives_both_files_together_without_overwriting_previous_pair(self):
        video = self.pair('1.mp4', b'old video')
        upload.archive(video, video.with_suffix('.txt'))
        video = self.pair('1.mp4', b'new video')
        caption = video.with_suffix('.txt')
        caption.write_text('New caption')
        target = upload.archive(video, caption)
        completed = self.folder.parent / 'completed'
        self.assertNotEqual(target, completed)
        self.assertEqual((completed / '1.mp4').read_bytes(), b'old video')
        self.assertEqual((completed / '1.txt').read_text(), 'Original caption for 1.mp4')
        self.assertEqual((target / '1.mp4').read_bytes(), b'new video')
        self.assertEqual((target / '1.txt').read_text(), 'New caption')
        self.assertFalse(video.exists())
        self.assertFalse(caption.exists())

    def test_collision_with_only_old_caption_keeps_pair_in_new_directory(self):
        video = self.pair('1.mp4')
        completed = self.folder.parent / 'completed'
        completed.mkdir()
        (completed / '1.txt').write_text('Keep existing text')
        target = upload.archive(video, video.with_suffix('.txt'))
        self.assertEqual((completed / '1.txt').read_text(), 'Keep existing text')
        self.assertFalse((completed / '1.mp4').exists())
        self.assertTrue((target / '1.mp4').exists())
        self.assertTrue((target / '1.txt').exists())

    def test_named_archived_lookup_finds_success_in_collision_subfolder(self):
        video = self.pair('1.mp4', b'new video')
        key = upload.job_key(self.entry, video)
        completed = self.folder.parent / 'completed'
        completed.mkdir()
        (completed / '1.mp4').write_bytes(b'older unregistered file')
        upload.archive(video, video.with_suffix('.txt'))
        state = {key: dict(account='fb01', target='page01', status='published')}
        self.assertIsNone(upload.named_job(self.entry, state, '1.mp4'))
        state[key]['status'] = 'needs_review'
        with self.assertRaisesRegex(ValueError, '缺少指定视频'):
            upload.named_job(self.entry, state, '1.mp4')

    def test_two_successful_uses_of_1_preserve_both_content_records_and_next_name_is_2(self):
        state = {}
        old_key = None
        for content in (b'first numbered video', b'second numbered video'):
            video = self.pair('1.mp4', content)
            browser = MagicMock()
            browser.pages = [MagicMock()]
            button = MagicMock()
            key = upload.job_key(self.entry, video)
            with patch('playwright.sync_api.sync_playwright'), \
                    patch.object(upload, 'launch_context', return_value=browser), \
                    patch.object(upload, 'prepare_reel', return_value=(button, {})), \
                    patch.object(upload, 'recheck_publish_identity'), \
                    patch.object(upload, 'install_receipt_watch'), \
                    patch.object(upload, 'wait_for_receipt', return_value='Your reel is published.'):
                upload.run_entry(self.entry, state, self.state_path, True)
            button.click.assert_called_once()
            self.assertEqual(state[key]['status'], 'published')
            if old_key:
                self.assertEqual(state[old_key]['status'], 'published')
            old_key = key
        self.assertEqual(len(state), 2)
        archived = list((self.folder.parent / 'completed').rglob('1.mp4'))
        self.assertEqual({p.read_bytes() for p in archived}, {b'first numbered video', b'second numbered video'})
        self.pair('1.mp4', b'second numbered video')
        self.pair('2.mp4')
        self.assertEqual([job[1].name for job in upload.pending_jobs(self.entry, state)], ['2.mp4'])


if __name__ == '__main__':
    unittest.main()
