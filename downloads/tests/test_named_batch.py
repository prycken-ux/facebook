"""Exact-file publishing must never substitute an older queued video."""
import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import batch_upload as batch
import fb_upload as upload


class NamedBatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(patch.object(batch, 'ROOT', self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.name = '2026-10-15_01.mp4'
        self.entries = []
        for index in (1, 2):
            entry = dict(account=f'fb0{index}', target='page01', type='page', name=f'Page {index}',
                         url=f'https://www.facebook.com/profile.php?id={1000+index}', enabled=True, prepared_at='checked')
            self.entries.append(entry)
            (self.root / 'profiles' / entry['account']).mkdir(parents=True)
            self.make_pair(entry, self.name, b'today video')
        self.state_path = self.root / 'logs/publish_state.json'
        self.state_path.parent.mkdir()
        self.state = {}

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def make_pair(self, entry, name, content):
        folder = upload.inbox_for(entry)
        folder.mkdir(parents=True, exist_ok=True)
        video = folder / name
        video.write_bytes(content)
        caption = video.with_suffix('.txt')
        caption.write_text('\ufeffToday caption\n#Example', encoding='utf-8')
        for path in (video, caption):
            os.utime(path, (time.time()-120, time.time()-120))
        return video

    def test_exact_name_selects_today_instead_of_older_backlog(self):
        older = self.make_pair(self.entries[0], '2026-10-14_01.mp4', b'older backlog')
        job = upload.named_job(self.entries[0], {}, self.name)
        self.assertEqual(job[1].name, self.name)
        self.assertEqual(job[3], 'Today caption\n#Example')
        self.assertTrue(older.exists())

    def test_publication_uses_and_archives_only_named_file(self):
        entry = self.entries[0]
        older = self.make_pair(entry, '2026-10-14_01.mp4', b'older backlog')
        context = MagicMock()
        context.pages = [MagicMock()]
        button = MagicMock()
        with patch('playwright.sync_api.sync_playwright'), \
                patch.object(upload, 'launch_context', return_value=context), \
                patch.object(upload, 'prepare_reel', return_value=(button, {})) as prepare, \
                patch.object(upload, 'recheck_publish_identity'), \
                patch.object(upload, 'install_receipt_watch'), \
                patch.object(upload, 'wait_for_receipt', return_value='Your reel is published.'):
            upload.run_entry(entry, self.state, self.state_path, True, filename=self.name)
        self.assertEqual(prepare.call_args.args[2].name, self.name)
        button.click.assert_called_once()
        self.assertTrue(older.exists())
        self.assertTrue(older.with_suffix('.txt').exists())
        self.assertTrue((older.parent.parent / 'completed' / self.name).is_file())
        row = next(iter(upload.read_json(self.state_path, {}).values()))
        self.assertEqual(Path(row['video']).name, self.name)
        self.assertEqual(row['status'], 'published')

    def test_missing_file_in_last_account_blocks_entire_batch(self):
        upload.inbox_for(self.entries[1]).joinpath(self.name).unlink()
        upload.save_json(upload.CONFIG, {'targets': self.entries})
        with patch('sys.argv', ['batch_upload.py', 'publish', '--accounts=fb01,fb02', '--filename', self.name]), \
                patch('batch_upload.subprocess.run') as run:
            self.assertEqual(batch.main(), 1)
        run.assert_not_called()
        self.assertFalse(self.state_path.exists())
        self.assertFalse((self.root / 'logs/batch.lock').exists())

    def test_missing_caption_empty_caption_or_recent_copy_blocks_before_browser(self):
        entry = self.entries[0]
        video = upload.inbox_for(entry) / self.name
        caption = video.with_suffix('.txt')
        for failure in ('missing', 'empty', 'recent'):
            with self.subTest(failure=failure):
                self.make_pair(entry, self.name, b'today video')
                if failure == 'missing':
                    caption.unlink()
                elif failure == 'empty':
                    caption.write_text('  ', encoding='utf-8')
                    os.utime(caption, (time.time()-120, time.time()-120))
                else:
                    os.utime(video, None)
                with patch.object(upload, 'launch_context') as launch:
                    with self.assertRaises(ValueError):
                        upload.run_entry(entry, {}, self.state_path, True, filename=self.name)
                    launch.assert_not_called()
        self.assertFalse(self.state_path.exists())

    def test_published_archived_file_is_skipped_without_browser(self):
        entry = self.entries[0]
        video = upload.inbox_for(entry) / self.name
        key = upload.job_key(entry, video)
        state = {key: dict(account=entry['account'], target=entry['target'], status='published')}
        upload.archive(video, video.with_suffix('.txt'))
        with patch.object(upload, 'launch_context') as launch:
            self.assertFalse(upload.run_entry(entry, state, self.state_path, True, filename=self.name))
            launch.assert_not_called()

    def test_same_content_renamed_is_still_skipped(self):
        entry = self.entries[0]
        video = upload.inbox_for(entry) / self.name
        key = upload.job_key(entry, video)
        state = {key: dict(account=entry['account'], target=entry['target'], status='published')}
        renamed = self.make_pair(entry, 'renamed.mp4', video.read_bytes())
        self.assertIsNone(upload.named_job(entry, state, renamed.name))

    def test_new_content_with_reused_filename_is_not_confused_with_old_content(self):
        entry = self.entries[0]
        video = upload.inbox_for(entry) / self.name
        key = upload.job_key(entry, video)
        state = {key: dict(account=entry['account'], target=entry['target'], status='published')}
        upload.archive(video, video.with_suffix('.txt'))
        self.make_pair(entry, self.name, b'different new video')
        job = upload.named_job(entry, state, self.name)
        self.assertNotEqual(job[0], key)

    def test_existing_failed_or_uncertain_record_never_retries_automatically(self):
        entry = self.entries[0]
        key = upload.job_key(entry, upload.inbox_for(entry) / self.name)
        for status in ('failed_before_post', 'posting', 'needs_review'):
            with self.subTest(status=status):
                state = {key: dict(account=entry['account'], target=entry['target'], status=status)}
                with self.assertRaises(ValueError):
                    upload.named_job(entry, state, self.name)

    def test_preflight_still_requires_prepare_and_enabled(self):
        self.entries[1].pop('prepared_at')
        self.entries[1]['enabled'] = False
        _, errors = batch.select_targets({'targets': self.entries}, ['fb01', 'fb02'], 'publish', {}, filename=self.name)
        self.assertTrue(any('prepare' in message for message in errors))
        self.assertTrue(any('启用' in message for message in errors))

    def test_batch_passes_filename_and_stops_before_next_account_on_error(self):
        with patch('batch_upload.subprocess.run', return_value=SimpleNamespace(returncode=1)) as run:
            results = batch.execute(self.entries, 'publish', filename=self.name)
        self.assertEqual(len(results), 1)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('--filename')+1], self.name)
        self.assertEqual(command[command.index('--account')+1], 'fb01')

    def test_filename_rejects_paths_and_non_mp4(self):
        for name in ('../other.mp4', r'..\other.mp4', r'C:\other.mp4', 'video.txt', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                upload.named_job(self.entries[0], {}, name)


if __name__ == '__main__':
    unittest.main()
