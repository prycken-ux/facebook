import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fb_upload as upload
import mark_verified_post as marker


class VerifiedPostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry = dict(account='fb07', target='personal', type='personal', workflow='personal_recording_v1',
                          name='Example Person', url='https://www.facebook.com/profile.php?id=1007')
        self.video = upload.inbox_for(self.entry) / '2026-10-15_01.mp4'
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b'actual fifteen bytes')
        self.video.with_suffix('.txt').write_text('fifteen caption')
        self.key = upload.job_key(self.entry, self.video)
        self.link = 'https://www.facebook.com/reel/1823700082081273'
        self.state_path = self.root / 'logs/publish_state.json'
        self.state = {
            self.key: dict(account='fb07', target='personal', video=str(self.video), status='needs_review', error='receipt timeout'),
            'old-fourteen': dict(account='fb07', target='personal', status='published',
                                 video=str(self.video.with_name('2026-10-14_01.mp4')), permalink=self.link,
                                 confirmation_method='user_verified_manual_post'),
            'genuine-older-post': dict(account='fb07', target='personal', status='published',
                                       video='older-account-folder/2026-10-14_01.mp4', permalink='https://www.facebook.com/reel/1119395750579952'),
            'other-account': dict(account='fb03', target='personal', status='published', video='other.mp4')}
        upload.save_json(self.state_path, self.state)
        upload.save_json(upload.CONFIG, {'targets': [self.entry]})

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def mark(self, correct=True):
        return marker.mark_verified(self.entry, self.video.name, self.link,
                                    '2026-10-14_01.mp4' if correct else None)

    def test_corrects_mistaken_fourteen_mapping_marks_fifteen_and_preserves_history(self):
        original = self.state_path.read_bytes()
        self.assertEqual(self.mark(), self.key)
        state = upload.read_json(self.state_path, {})
        self.assertEqual(state[self.key]['status'], 'published')
        self.assertEqual(state[self.key]['permalink'], self.link)
        self.assertEqual(state[self.key]['error'], 'receipt timeout')
        self.assertEqual(state['old-fourteen']['status'], 'misidentified_post')
        self.assertEqual(state['old-fourteen']['misidentified_permalink'], self.link)
        self.assertEqual(state['old-fourteen']['corrected_to_job'], self.key)
        self.assertNotIn('permalink', state['old-fourteen'])
        for key in ('genuine-older-post', 'other-account'):
            self.assertEqual(state[key], self.state[key])
        self.assertEqual(next((self.root / 'backups').glob('*/publish_state.json')).read_bytes(), original)
        completed = self.video.parent.parent / 'completed'
        self.assertTrue((completed / self.video.name).is_file())
        self.assertTrue((completed / self.video.with_suffix('.txt').name).is_file())

    def test_repeated_confirmation_is_idempotent_after_archiving(self):
        self.mark()
        previous = self.state_path.read_bytes()
        self.assertEqual(self.mark(), self.key)
        self.assertEqual(self.state_path.read_bytes(), previous)
        self.assertEqual(len(list((self.root / 'backups').iterdir())), 1)

    def test_without_explicit_correction_conflicting_link_changes_nothing(self):
        previous = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '更正范围'):
            self.mark(correct=False)
        self.assertEqual(self.state_path.read_bytes(), previous)
        self.assertTrue(self.video.exists())
        self.assertFalse((self.root / 'backups').exists())

    def test_conflicting_link_in_another_account_cannot_be_reassigned(self):
        self.state['old-fourteen']['account'] = 'fb06'
        upload.save_json(self.state_path, self.state)
        previous = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '更正范围'):
            self.mark()
        self.assertEqual(self.state_path.read_bytes(), previous)

    def test_changed_local_file_cannot_be_confirmed_as_original_job(self):
        self.video.write_bytes(b'different replacement file')
        previous = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '内容指纹不同'):
            self.mark()
        self.assertEqual(self.state_path.read_bytes(), previous)

    def test_normal_receipt_confirmation_without_mistaken_mapping(self):
        self.state.pop('old-fourteen')
        upload.save_json(self.state_path, self.state)
        self.mark(correct=False)
        self.assertEqual(upload.read_json(self.state_path, {})[self.key]['status'], 'published')

    def test_without_link_requires_explicit_user_confirmation(self):
        previous = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '明确确认'):
            marker.mark_verified(self.entry, self.video.name)
        self.assertEqual(self.state_path.read_bytes(), previous)
        self.assertTrue(self.video.exists())

    def test_explicit_user_confirmation_preserves_errors_other_records_and_backup(self):
        previous = self.state_path.read_bytes()
        marker.mark_verified(self.entry, self.video.name, verified_published=True)
        state = upload.read_json(self.state_path, {})
        row = state[self.key]
        self.assertEqual(row['status'], 'published')
        self.assertEqual(row['confirmation_method'], 'user_confirmed_existing_post_no_link')
        self.assertEqual(row['error'], 'receipt timeout')
        self.assertNotIn('permalink', row)
        for key in self.state.keys() - {self.key}:
            self.assertEqual(state[key], self.state[key])
        self.assertEqual(next((self.root / 'backups').glob('*/publish_state.json')).read_bytes(), previous)
        self.assertFalse(self.video.exists())
        self.assertTrue((self.video.parent.parent / 'completed' / self.video.name).exists())
        saved = self.state_path.read_bytes()
        marker.mark_verified(self.entry, self.video.name, verified_published=True)
        self.assertEqual(self.state_path.read_bytes(), saved)
        self.assertEqual(len(list((self.root / 'backups').iterdir())), 1)

    def test_confirmation_without_link_preserves_existing_permalink_and_published_proof(self):
        self.state[self.key]['permalink'] = 'https://www.facebook.com/reel/12345'
        upload.save_json(self.state_path, self.state)
        marker.mark_verified(self.entry, self.video.name, verified_published=True)
        self.assertEqual(upload.read_json(self.state_path, {})[self.key]['permalink'],
                         self.state[self.key]['permalink'])
        state = upload.read_json(self.state_path, {})
        state[self.key]['confirmation_method'] = 'detected_success_receipt'
        upload.save_json(self.state_path, state)
        previous = self.state_path.read_bytes()
        marker.mark_verified(self.entry, self.video.name, verified_published=True)
        self.assertEqual(self.state_path.read_bytes(), previous)

    def test_link_correction_without_link_is_rejected(self):
        previous = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '必须提供 --url'):
            marker.mark_verified(self.entry, self.video.name,
                                 correct_from_filename='2026-10-14_01.mp4', verified_published=True)
        self.assertEqual(self.state_path.read_bytes(), previous)

    def test_no_link_confirmation_still_checks_source_content(self):
        self.video.write_bytes(b'replaced video content')
        previous = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '内容指纹不同'):
            marker.mark_verified(self.entry, self.video.name, verified_published=True)
        self.assertEqual(self.state_path.read_bytes(), previous)

    def test_cli_without_link_is_local_only(self):
        args = ['mark_verified_post.py', '--account', 'fb07', '--target', 'personal',
                '--filename', self.video.name, '--verified-published']
        with patch('sys.argv', args), patch.object(upload, 'launch_context') as launch:
            self.assertEqual(marker.main(), 0)
        launch.assert_not_called()
        self.assertFalse((self.root / 'logs/upload.lock').exists())

    def test_archive_collision_does_not_overwrite_media_or_lose_success_record(self):
        completed = self.video.parent.parent / 'completed'
        completed.mkdir()
        destination = completed / self.video.name
        destination.write_bytes(b'pre-existing different media')
        self.mark()
        self.assertEqual(destination.read_bytes(), b'pre-existing different media')
        self.assertTrue(self.video.is_file())
        self.assertEqual(upload.read_json(self.state_path, {})[self.key]['status'], 'published')

    def test_cli_is_local_only_and_respects_other_upload_lock(self):
        args = ['mark_verified_post.py', '--account', 'fb07', '--target', 'personal', '--filename', self.video.name,
                '--url', self.link, '--correct-from-filename', '2026-10-14_01.mp4']
        lock = self.root / 'logs/upload.lock'
        lock.write_text('1234')
        previous = self.state_path.read_bytes()
        with patch('sys.argv', args), patch.object(upload, 'launch_context') as launch:
            self.assertEqual(marker.main(), 2)
            self.assertEqual(lock.read_text(), '1234')
            self.assertEqual(self.state_path.read_bytes(), previous)
            lock.unlink()
            self.assertEqual(marker.main(), 0)
        launch.assert_not_called()
        self.assertFalse(lock.exists())


if __name__ == '__main__':
    unittest.main()
