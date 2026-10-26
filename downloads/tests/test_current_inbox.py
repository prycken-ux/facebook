"""New current material must not be confused with missing historical review files."""
import contextlib
import copy
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import add_fb_accounts
import fb_upload as upload
import publish_current_inbox as current


class CurrentInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for module in (upload, add_fb_accounts):
            self.stack.enter_context(patch.object(module, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root/'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry = dict(account='fb03', target='personal', type='personal', name='Lisa Mills',
            url='https://www.facebook.com/profile.php?id=100041479541385', enabled=True,
            prepared_at='checked', workflow='personal_recording_v1')
        upload.save_json(upload.CONFIG, {'targets': [self.entry]})
        self.folder = upload.inbox_for(self.entry)
        self.folder.mkdir(parents=True)
        self.old_path = self.folder/'k3.mp4'
        self.old_path.write_bytes(b'older unresolved video')
        self.old_key = upload.job_key(self.entry, self.old_path)
        self.old = dict(account='fb03', target='personal', status='needs_review', video=str(self.old_path),
                        url=self.entry['url'], created='old-attempt', error='old timeout')
        self.old_path.unlink()
        self.video = self.make_pair('1020权利3.0.mp4', b'this round new video')
        self.key = upload.job_key(self.entry, self.video)
        self.state = {self.old_key: copy.deepcopy(self.old),
            'fb10-unconfirmed': dict(account='fb10', target='personal', status='needs_review')}
        self.state_path = self.root/'logs/publish_state.json'
        upload.save_json(self.state_path, self.state)
        (self.root/'common_caption_today.txt').write_text('Yesterday caption\nAmazon link', encoding='utf-8')

    def make_pair(self, name, content):
        video = self.folder/name
        video.write_bytes(content)
        caption = video.with_suffix('.txt')
        caption.write_text('Yesterday caption\nAmazon link', encoding='utf-8')
        for path in (video, caption):
            os.utime(path, (time.time()-120, time.time()-120))
        return video

    @contextlib.contextmanager
    def browser(self, receipt_error=None, preparation=None):
        context = MagicMock()
        context.pages = [MagicMock()]
        button = MagicMock()
        def prepare(*args, **kwargs):
            if preparation:
                preparation()
            return button, {}
        with patch('playwright.sync_api.sync_playwright'), \
                patch.object(upload, 'launch_context', return_value=context) as launch, \
                patch.object(upload, 'prepare_reel', side_effect=prepare) as prepare_call, \
                patch.object(upload, 'install_receipt_watch'), \
                patch.object(upload, 'recheck_publish_identity'), \
                patch.object(upload, 'wait_for_receipt', return_value='Your reel is published.', side_effect=receipt_error):
            yield button, launch, prepare_call

    def run_new(self, **changes):
        options = dict(filename=self.video.name, ai_label_override=False, new_video_with_old_review=True)
        options.update(changes)
        return upload.run_entry(self.entry, self.state, self.state_path, True, **options)

    def test_posts_exact_unicode_current_file_while_preserving_old_reviews(self):
        with self.browser() as (button, _, prepare):
            self.run_new()
        button.click.assert_called_once()
        self.assertEqual(prepare.call_args.args[2].name, '1020权利3.0.mp4')
        self.assertFalse(prepare.call_args.args[1]['ai_label'])
        self.assertEqual(self.state[self.old_key], self.old)
        saved = upload.read_json(self.state_path, {})
        self.assertEqual(saved[self.old_key], self.old)
        self.assertEqual(saved[self.key]['status'], 'published')
        self.assertEqual(saved[self.key]['preserved_older_review_jobs'], [self.old_key])
        self.assertEqual(saved['fb10-unconfirmed'], self.state['fb10-unconfirmed'])
        self.assertTrue((self.folder.parent/'completed'/self.video.name).is_file())

    def test_default_behavior_still_blocks_old_pending_review(self):
        with patch.object(upload, 'launch_context') as launch, self.assertRaises(RuntimeError):
            upload.run_entry(self.entry, self.state, self.state_path, True, filename=self.video.name)
        launch.assert_not_called()

    def test_preparing_or_posting_and_existing_old_source_remain_blocked(self):
        for status in ('preparing', 'posting', 'needs_review'):
            self.state[self.old_key]['status'] = status
            if status == 'needs_review':
                self.old_path.write_bytes(b'older unresolved video')
            with self.subTest(status=status), patch.object(upload, 'launch_context') as launch, \
                    self.assertRaises(RuntimeError):
                self.run_new()
            launch.assert_not_called()

    def test_renamed_old_content_cannot_be_reposted(self):
        self.video.write_bytes(b'older unresolved video')
        os.utime(self.video, (time.time()-120, time.time()-120))
        with patch.object(upload, 'launch_context') as launch, self.assertRaises(ValueError):
            self.run_new()
        launch.assert_not_called()

    def test_new_uncertain_result_is_retained_and_cannot_be_retried_by_this_mode(self):
        with self.browser(receipt_error=upload.ReceiptNeedsReview('timeout')) as (button, _, _):
            with self.assertRaises(upload.ReceiptNeedsReview):
                self.run_new()
        button.click.assert_called_once()
        self.assertEqual(self.state[self.key]['status'], 'needs_review')
        self.assertEqual(self.state[self.old_key], self.old)
        with patch.object(upload, 'launch_context') as launch, self.assertRaises(ValueError):
            self.run_new()
        launch.assert_not_called()

    def test_changed_source_after_preparation_stops_before_post(self):
        with self.browser(preparation=lambda: self.video.write_bytes(b'changed during preparation')) as (button, _, _):
            with self.assertRaises(RuntimeError):
                self.run_new()
        button.click.assert_not_called()
        self.assertEqual(self.state[self.key]['status'], 'failed_before_post')
        self.assertEqual(self.state[self.old_key], self.old)

    def test_mode_requires_exact_filename_and_prepared_target(self):
        for change in ({'filename': None},):
            with self.assertRaises(ValueError):
                self.run_new(**change)
        self.entry.pop('prepared_at')
        with self.assertRaises(ValueError):
            self.run_new()

    def test_helper_selects_current_material_and_backs_up_ledger_without_reset(self):
        original = self.state_path.read_bytes()
        with self.browser() as (button, _, _):
            current.publish_current('fb03')
        button.click.assert_called_once()
        backup = next((self.root/'backups').iterdir())
        self.assertEqual((backup/'publish_state.json').read_bytes(), original)
        self.assertEqual(upload.read_json(self.state_path, {})[self.old_key], self.old)

    def test_helper_refuses_multiple_new_files_or_wrong_common_caption(self):
        second = self.make_pair('second.mp4', b'another new video')
        with patch.object(upload, 'run_entry') as run, self.assertRaises(ValueError):
            current.publish_current('fb03')
        run.assert_not_called()
        second.unlink()
        self.video.with_suffix('.txt').write_text('unexpected caption')
        with patch.object(upload, 'run_entry') as run, self.assertRaises(ValueError):
            current.publish_current('fb03')
        run.assert_not_called()

    def test_helper_never_automatically_retries_a_recorded_current_video(self):
        self.state[self.key] = dict(account='fb03', target='personal', status='needs_review', video=str(self.video))
        upload.save_json(self.state_path, self.state)
        before = self.state_path.read_bytes()
        with patch.object(upload, 'run_entry') as run:
            self.assertFalse(current.publish_current('fb03'))
        run.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_unicode_names_are_allowed_but_paths_and_windows_devices_are_not(self):
        upload.validate_video_filename('1020权利3.0.mp4')
        for name in ('../video.mp4', r'..\video.mp4', 'name\n.mp4', 'NUL.mp4', 'COM1.mp4', 'a:b.mp4'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                upload.validate_video_filename(name)

    def current_record(self, status):
        return dict(account='fb03', target='personal', status=status, url=self.entry['url'],
                    video=str(self.video), caption=str(self.video.with_suffix('.txt')), created='current-attempt')

    def test_explicit_before_post_retry_retries_current_content_and_preserves_older_review(self):
        self.state[self.key] = self.current_record('failed_before_post')
        upload.save_json(self.state_path, self.state)
        with self.browser() as (button, _, _):
            current.publish_current('fb03', retry_before_post=True, expected_key=self.key)
        button.click.assert_called_once()
        result = upload.read_json(self.state_path, {})
        self.assertEqual(result[self.key]['status'], 'published')
        self.assertEqual(result[self.old_key], self.old)
        backup = next((self.root/'backups').iterdir())
        self.assertEqual(upload.read_json(backup/'before-post-retry.json', {})['original_record']['status'],
                         'failed_before_post')

    def test_before_post_retry_flag_does_not_repeat_an_unknown_result(self):
        self.state[self.key] = self.current_record('needs_review')
        upload.save_json(self.state_path, self.state)
        original = self.state_path.read_bytes()
        with patch.object(upload, 'run_entry') as run:
            self.assertFalse(current.publish_current('fb03', retry_before_post=True, expected_key=self.key))
        run.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), original)

    def test_exact_audited_key_selects_only_that_failed_video_among_other_material(self):
        other=self.make_pair('different.mp4',b'other failed video')
        other_key=upload.job_key(self.entry,other)
        self.state[self.key]=self.current_record('failed_before_post')
        self.state[other_key]=dict(self.current_record('failed_before_post'),video=str(other))
        previous=copy.deepcopy(self.state[other_key])
        upload.save_json(self.state_path,self.state)
        with self.browser() as (button,_,prepare):
            current.publish_current('fb03',retry_before_post=True,expected_key=self.key)
        button.click.assert_called_once()
        self.assertEqual(prepare.call_args.args[2],self.video)
        self.assertTrue(other.exists())
        self.assertEqual(upload.read_json(self.state_path,{})[other_key],previous)

    def test_audited_key_never_guesses_between_two_copies_of_identical_content(self):
        self.make_pair('copy.mp4',self.video.read_bytes())
        with patch.object(upload,'run_entry') as run,self.assertRaises(ValueError):
            current.publish_current('fb03',expected_key=self.key)
        run.assert_not_called()

    def test_menu_assistance_is_forwarded_only_when_requested(self):
        with self.browser() as (button,_,prepare):
            current.publish_current('fb03',expected_key=self.key,pause_before_reel=True)
        self.assertTrue(prepare.call_args.kwargs['pause_before_reel'])
        button.click.assert_called_once()

    def test_before_post_retry_launch_failure_restores_old_failure_record(self):
        self.state[self.key] = self.current_record('failed_before_post')
        upload.save_json(self.state_path, self.state)
        with patch.object(upload, 'launch_context', side_effect=RuntimeError('launch failed')), \
                self.assertRaises(RuntimeError):
            current.publish_current('fb03', retry_before_post=True, expected_key=self.key)
        self.assertEqual(upload.read_json(self.state_path, {}), self.state)

    def test_audit_fingerprint_mismatch_or_conflicting_success_proof_never_launches(self):
        original = self.state_path.read_bytes()
        with patch.object(upload, 'run_entry') as run, self.assertRaises(ValueError):
            current.publish_current('fb03', retry_before_post=True, expected_key='0'*64)
        run.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), original)
        self.state[self.key] = {**self.current_record('failed_before_post'), 'success_message': 'published'}
        upload.save_json(self.state_path, self.state)
        with patch.object(upload, 'run_entry') as run, self.assertRaises(ValueError):
            current.publish_current('fb03', retry_before_post=True, expected_key=self.key)
        run.assert_not_called()

    def test_source_change_between_helper_check_and_uploader_selection_never_posts(self):
        original_run = upload.run_entry
        original_state = self.state_path.read_bytes()
        def changed(*args, **kwargs):
            self.video.write_bytes(b'changed after audit with old preserved timestamp')
            os.utime(self.video, (time.time()-120, time.time()-120))
            return original_run(*args, **kwargs)
        with patch.object(upload, 'run_entry', side_effect=changed), \
                patch.object(upload, 'launch_context') as launch, self.assertRaises(ValueError):
            current.publish_current('fb03', expected_key=self.key)
        launch.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), original_state)


if __name__ == '__main__':
    unittest.main()
