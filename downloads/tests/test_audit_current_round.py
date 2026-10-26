import contextlib
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import add_fb_accounts
import audit_current_round as audit
import fb_upload as upload


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for module in (upload, add_fb_accounts):
            self.stack.enter_context(patch.object(module, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root/'upload_config.json'))
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.entries = []
        for number, (account, target) in enumerate(audit.ORIGINAL_TARGETS):
            entry = dict(account=account, target=target, type='personal' if target == 'personal' else 'page',
                name=account, url='https://www.facebook.com/profile.php?id=%d' % (1000+number),
                enabled=True, prepared_at='checked')
            if target == 'personal':
                entry['workflow'] = 'personal_recording_v1'
            self.entries.append(entry)
            upload.inbox_for(entry).mkdir(parents=True)
        self.entry = self.entries[2]
        self.extra = dict(account='fb10', target='page01', type='page', name='New Page',
                          url='https://www.facebook.com/profile.php?id=888888', enabled=False)
        self.config = {'targets': self.entries+[self.extra]}
        upload.save_json(upload.CONFIG, self.config)
        self.video = upload.inbox_for(self.entry)/'1020权利3.0.mp4'
        self.video.write_bytes(b'current material')
        self.caption = self.video.with_suffix('.txt')
        self.caption.write_text('Approved caption')
        (self.root/'common_caption_today.txt').write_text('Approved caption')
        for path in (self.video, self.caption):
            os.utime(path, (time.time()-120, time.time()-120))
        self.key = upload.job_key(self.entry, self.video)
        self.old = dict(account='fb03', target='personal', status='needs_review', url=self.entry['url'],
            video=str(self.video.parent/'k3.mp4'), created='2026-10-19T10:00:00+08:00')
        self.state = {'older-job': self.old}
        self.state_path = self.root/'logs/publish_state.json'
        upload.save_json(self.state_path, self.state)

    def record(self, status):
        return dict(account='fb03', target='personal', status=status, url=self.entry['url'],
            video=str(self.video), created='2026-10-21T18:00:00+08:00')

    def scan(self):
        return audit.scan(self.config, self.state, pairs=[('fb03', 'personal')])

    def test_current_content_is_unattempted_while_missing_old_review_is_separate(self):
        rows, old = self.scan()
        self.assertEqual(rows[0]['filename'], self.video.name)
        self.assertEqual(rows[0]['status'], 'unrecorded')
        self.assertTrue(rows[0]['eligible'])
        self.assertEqual(rows[0]['key'], self.key)
        self.assertEqual(old[0]['filename'], 'k3.mp4')

    def test_only_unattempted_and_unambiguously_before_post_failure_are_eligible(self):
        for status, eligible in [('published', False), ('needs_review', False),
                                 ('posting', False), ('preparing', False), ('failed_before_post', True)]:
            self.state[self.key] = self.record(status)
            with self.subTest(status=status):
                rows, old = self.scan()
                self.assertEqual(rows[0]['status'], status)
                self.assertEqual(rows[0]['eligible'], eligible)
                self.assertEqual([item['filename'] for item in old], ['k3.mp4'])

    def test_empty_inbox_does_not_become_success_based_on_a_historical_record(self):
        self.video.unlink()
        self.state['historical-success'] = self.record('published')
        rows, _ = self.scan()
        self.assertEqual(rows[0]['status'], 'inbox_empty')
        self.assertFalse(rows[0]['eligible'])
        self.assertIsNone(rows[0]['key'])
        self.assertIn('最近成功记录', rows[0]['reason'])

    def test_invalid_caption_success_proof_and_multiple_candidates_are_not_eligible(self):
        self.caption.write_text('Wrong caption')
        rows, _ = self.scan()
        self.assertFalse(rows[0]['eligible'])
        self.caption.write_text('Approved caption')
        os.utime(self.caption, (time.time()-120, time.time()-120))
        self.state[self.key] = {**self.record('failed_before_post'), 'permalink': 'https://www.facebook.com/reel/123'}
        rows, _ = self.scan()
        self.assertFalse(rows[0]['eligible'])
        del self.state[self.key]
        other = self.video.parent/'second.mp4'
        other.write_bytes(b'other material')
        other.with_suffix('.txt').write_text('Approved caption')
        for path in (other, other.with_suffix('.txt')):
            os.utime(path, (time.time()-120, time.time()-120))
        rows, _ = self.scan()
        self.assertTrue(all(not row['eligible'] for row in rows))

    def test_execute_uses_audited_fingerprint_and_does_not_execute_unknown_results(self):
        rows, _ = self.scan()
        rows.append({**rows[0], 'eligible': False, 'status': 'needs_review', 'key': 'other'})
        with patch.object(audit, 'publish_current') as publish:
            results = audit.execute(rows)
        publish.assert_called_once_with('fb03', 'personal', 'off', retry_before_post=True, expected_key=self.key)
        self.assertEqual(len(results), 1)

    def test_new_only_does_not_retry_old_failed_video_or_block_one_new_video(self):
        self.state[self.key] = self.record('failed_before_post')
        other=self.video.parent/'today.mp4'
        other.write_bytes(b'today content')
        other.with_suffix('.txt').write_text('Approved caption')
        for path in (other,other.with_suffix('.txt')):
            os.utime(path,(time.time()-120,time.time()-120))
        rows,_=audit.scan(self.config,self.state,pairs=[('fb03','personal')],retry_before_post=False)
        by_name={row['filename']:row for row in rows}
        self.assertFalse(by_name[self.video.name]['eligible'])
        self.assertEqual(by_name[self.video.name]['status'],'failed_before_post')
        self.assertTrue(by_name['today.mp4']['eligible'])
        with patch.object(audit,'publish_current') as publish:
            audit.execute(rows,'off',retry_before_post=False)
        publish.assert_called_once_with('fb03','personal','off',retry_before_post=False,
                                       expected_key=upload.job_key(self.entry,other))

    def test_new_only_leaves_old_failure_when_no_new_video_exists(self):
        self.state[self.key]=self.record('failed_before_post')
        rows,_=audit.scan(self.config,self.state,pairs=[('fb03','personal')],retry_before_post=False)
        self.assertFalse(rows[0]['eligible'])
        with patch.object(audit,'publish_current') as publish:
            audit.execute(rows,'off',retry_before_post=False)
        publish.assert_not_called()

    def test_read_only_run_preserves_ledger_and_excludes_new_fb10_page(self):
        before = self.state_path.read_bytes()
        with patch('sys.argv', ['audit_current_round.py']), patch.object(audit, 'publish_current') as publish:
            self.assertEqual(audit.main(), 0)
        publish.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), before)
        report = upload.read_json(next((self.root/'logs').glob('current-audit-*.json')), {})
        self.assertEqual(len(report['rows']), 13)
        self.assertFalse(any(row['account'] == 'fb10' and row['target'] == 'page01' for row in report['rows']))

    def test_final_report_tracks_the_same_hash_after_success_and_archival(self):
        def finish(rows, label):
            state = upload.read_json(self.state_path, {})
            state[self.key] = self.record('published')
            upload.save_json(self.state_path, state)
            upload.archive(self.video, self.caption)
            return [dict(account='fb03', target='personal', filename=self.video.name, key=self.key, attempt='finished')]
        with patch('sys.argv', ['audit_current_round.py', '--run']), patch.object(audit, 'execute', side_effect=finish):
            self.assertEqual(audit.main(), 0)
        report = upload.read_json(next((self.root/'logs').glob('current-audit-*.json')), {})
        row = next(item for item in report['final_rows'] if item['account'] == 'fb03')
        self.assertEqual(row['key'], self.key)
        self.assertEqual(row['status'], 'published')
        self.assertEqual(row['filename'], '1020权利3.0.mp4')
        self.assertFalse(self.video.exists())


if __name__ == '__main__':
    unittest.main()
