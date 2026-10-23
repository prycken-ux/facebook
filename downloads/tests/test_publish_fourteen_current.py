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
import apply_common_caption as captions
import audit_current_round as audit
import fb_upload as upload
import publish_fourteen_current as driver
import publish_current_inbox as publisher


class FourteenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        for module in (upload, add_fb_accounts, captions):
            self.stack.enter_context(patch.object(module, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.sleep = self.stack.enter_context(patch.object(driver.time, 'sleep'))
        self.entries = []
        self.keys = []
        self.videos = []
        for index, (account, target) in enumerate(driver.TARGETS, 1):
            entry = dict(account=account, target=target, name=account + target,
                         type='personal' if target == 'personal' else 'page', enabled=True, prepared_at='ready',
                         url='https://www.facebook.com/profile.php?id=' + ('61595024556188' if (account, target) == ('fb10', 'page01') else str(10000 + index)))
            if target == 'personal':
                entry['workflow'] = 'personal_recording_v1'
            self.entries.append(entry)
            video = upload.inbox_for(entry) / f'新产品{index}.mp4'
            video.parent.mkdir(parents=True)
            video.write_bytes(f'new content {index}'.encode())
            os.utime(video, (time.time() - 120, time.time() - 120))
            self.videos.append(video)
            self.keys.append(upload.job_key(entry, video))
        self.extra = dict(account='fb11', target='page02', type='page', name='Not in this round',
                          url='https://www.facebook.com/profile.php?id=999998', enabled=False)
        self.config = dict(targets=[*self.entries, self.extra])
        self.state_path = self.root / 'logs/publish_state.json'
        self.state = dict(historical_review=dict(account='fb03', target='personal', status='needs_review',
            url=self.entries[2]['url'], video=str(self.videos[2].with_name('old.mp4')), created='2026-10-21T10:00:00+08:00'))
        upload.save_json(upload.CONFIG, self.config)
        upload.save_json(self.state_path, self.state)
        (self.root / 'common_caption_today.txt').write_text('Same approved caption\nhttps://www.amazon.com/?x=1&y=2')

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def report(self):
        return upload.read_json(next((self.root / 'logs').glob('current-audit-*.json')), {})

    def execute(self, fail_account=None, ambiguous_account=None):
        calls = []
        def publish(account, target, label, **kwargs):
            calls.append((account, target, label, kwargs['expected_key']))
            if account == fail_account:
                raise RuntimeError('login checkpoint')
            if account == ambiguous_account:
                key = kwargs['expected_key']
                state = upload.read_json(self.state_path, {})
                video = self.videos[self.keys.index(key)]
                entry = self.entries[self.keys.index(key)]
                state[key] = dict(account=account, target=target, url=entry['url'], video=str(video), status='needs_review')
                upload.save_json(self.state_path, state)
                raise upload.ReceiptNeedsReview('no receipt')
            # Simulate the clock having passed while retaining real pipeline/locks/hash guards.
            for path in upload.inbox_for(self.entries[self.keys.index(kwargs['expected_key'])]).iterdir():
                os.utime(path, (time.time() - 120, time.time() - 120))
            return publisher.publish_current(account, target, label, **kwargs)
        browser = MagicMock()
        browser.pages = [MagicMock()]
        with patch.object(audit, 'publish_current', side_effect=publish), \
             patch('playwright.sync_api.sync_playwright'), \
             patch.object(upload, 'launch_context', return_value=browser), \
             patch.object(upload, 'prepare_reel', return_value=(MagicMock(), {})), \
             patch.object(upload, 'recheck_publish_identity'), \
             patch.object(upload, 'install_receipt_watch'), \
             patch.object(upload, 'wait_for_receipt', return_value='Your reel is published.'):
            result = driver.run(True, 'off')
        return result, calls

    def age_captions(self, seconds):
        # Driver waits are mocked: emulate the steady files that real elapsed wait yields.
        for video in self.videos:
            path = video.with_suffix('.txt')
            if path.exists():
                os.utime(path, (time.time() - 120, time.time() - 120))
    
    def test_fourteen_real_pipeline_calls_keep_old_reviews_and_archive_exact_new_material(self):
        self.sleep.side_effect = self.age_captions
        result, calls = self.execute()
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 14)
        self.assertEqual([(a, t) for a, t, _, _ in calls], list(driver.TARGETS))
        self.assertLess(calls.index(next(r for r in calls if r[:2] == ('fb10', 'personal'))),
                        calls.index(next(r for r in calls if r[:2] == ('fb10', 'page01'))))
        self.assertTrue(all(r[2] == 'off' for r in calls))
        state = upload.read_json(self.state_path, {})
        self.assertEqual(state['historical_review'], self.state['historical_review'])
        for key, video in zip(self.keys, self.videos):
            self.assertEqual(state[key]['status'], 'published')
            self.assertTrue((video.parent.parent / 'completed' / video.name).exists())
        report = self.report()
        self.assertEqual(len(report['final_rows']), 14)
        self.assertTrue(all(row['status'] == 'published' for row in report['final_rows']))
        self.assertEqual({r['key'] for r in report['final_rows']}, set(self.keys))
        self.assertEqual(len(list((self.root / 'logs').glob('current-audit-*.csv'))), 1)
        self.assertFalse((self.root / 'videos/fb11/page02').exists())

    def test_login_failure_and_unknown_result_continue_without_pretending_success(self):
        self.sleep.side_effect = self.age_captions
        result, calls = self.execute(fail_account='fb04', ambiguous_account='fb08')
        self.assertEqual(result, 3)
        self.assertEqual(len(calls), 14)
        rows = {r['account'] + '/' + r['target']: r for r in self.report()['final_rows']}
        self.assertEqual(rows['fb04/personal']['status'], 'unrecorded')
        self.assertIn('login checkpoint', rows['fb04/personal']['reason'])
        self.assertEqual(rows['fb08/personal']['status'], 'needs_review')
        self.assertEqual(rows['fb13/page01']['status'], 'published')

    def test_read_only_check_does_not_create_captions_or_publish(self):
        before = self.state_path.read_bytes()
        with patch.object(audit, 'publish_current') as publish:
            self.assertEqual(driver.run(), 0)
        publish.assert_not_called()
        self.sleep.assert_not_called()
        self.assertEqual(before, self.state_path.read_bytes())
        self.assertTrue(all(not video.with_suffix('.txt').exists() for video in self.videos))

    def test_missing_target_or_wrong_page_stops_before_caption_changes(self):
        for config in (dict(targets=self.entries[:-1]),
                       dict(targets=[*self.entries[:-1], dict(self.entries[-1], url='https://www.facebook.com/profile.php?id=123456')])):
            upload.save_json(upload.CONFIG, config)
            with self.assertRaises(ValueError):
                driver.run(True, 'off')
        self.assertTrue(all(not video.with_suffix('.txt').exists() for video in self.videos))

    def test_ai_classification_is_required_for_real_publication(self):
        with self.assertRaisesRegex(ValueError, '明确指定'):
            driver.run(True)
        self.assertTrue(all(not video.with_suffix('.txt').exists() for video in self.videos))

    def test_inbox_empty_is_not_substituted_with_an_old_success(self):
        self.sleep.side_effect = self.age_captions
        self.videos[0].unlink()
        self.state['old-success'] = dict(account='fb01', target='page01', status='published', video='old.mp4', created='2026-10-21')
        upload.save_json(self.state_path, self.state)
        result, calls = self.execute()
        self.assertEqual(result, 3)
        self.assertEqual(len(calls), 13)
        self.assertEqual(self.report()['final_rows'][0]['status'], 'inbox_empty')
        self.assertIsNone(self.report()['final_rows'][0]['key'])


if __name__ == '__main__':
    unittest.main()
