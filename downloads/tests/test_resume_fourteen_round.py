import copy
from unittest.mock import patch
import unittest

import fb_upload as upload
import resume_fourteen_round as resume
import test_publish_fourteen_current as fixtures


class ResumeTests(unittest.TestCase):
    def setUp(self):
        fixtures.FourteenTests.setUp(self)
        self.manifest = []
        statuses = ['needs_review', 'published', 'failed_before_post', 'failed_before_post',
                    'published', 'needs_review', 'failed_before_post', 'needs_review',
                    'failed_before_post', 'failed_before_post', 'failed_before_post', 'posting', None, None]
        for key, video, entry, status in zip(self.keys, self.videos, self.entries, statuses):
            self.manifest.append(dict(account=entry['account'], target=entry['target'], key=key,
                                      filename=video.name, status='unrecorded', eligible=True))
            video.with_suffix('.txt').write_text('Same approved caption\nhttps://www.amazon.com/?x=1&y=2')
            if status:
                self.state[key] = dict(account=entry['account'], target=entry['target'], url=entry['url'],
                                       status=status, video=str(video), error='previous failure' if status == 'failed_before_post' else '')
        self.path = self.root / 'logs/current-audit-20261023-165040.json'
        self.round = dict(schema='fourteen-current-publication-v1', phase='attempts_finished', ai_label='off',
                          created='2026-10-23T16:50:40+08:00', rows=self.manifest, results=[])
        upload.save_json(self.path, self.round)
        upload.save_json(self.state_path, self.state)

    def tearDown(self):
        fixtures.FourteenTests.tearDown(self)

    def test_selects_exact_six_failures_and_two_unattempted_excludes_all_unknowns(self):
        jobs = resume.candidates(self.round, self.state)
        self.assertEqual(len(jobs), 8)
        self.assertEqual({r['key'] for r in jobs}, {self.keys[i] for i in (2, 3, 6, 8, 9, 10, 12, 13)})

    def test_run_uses_manifest_keys_including_unattempted_and_preserves_every_other_record(self):
        calls = []
        def publish(account, target, label, **kwargs):
            key = kwargs['expected_key']
            calls.append((account, target, label, key))
            state = upload.read_json(self.state_path, {})
            state[key] = dict(account=account, target=target, url=self.entries[self.keys.index(key)]['url'],
                              status='published', video=str(self.videos[self.keys.index(key)]))
            upload.save_json(self.state_path, state)
        with patch.object(resume, 'publish_current', side_effect=publish):
            self.assertEqual(resume.resume(True), 3)
        self.assertEqual(len(calls), 8)
        self.assertTrue(all(r[2] == 'off' for r in calls))
        actual = upload.read_json(self.state_path, {})
        for key in self.state.keys() - {r[3] for r in calls}:
            self.assertEqual(actual[key], self.state[key])
        report = upload.read_json(self.path, {})
        self.assertEqual(len(report['resume_results']), 8)
        self.assertEqual(len(report['final_rows']), 14)
        self.assertTrue(self.path.with_suffix('.csv').exists())

    def test_existing_upload_lock_stops_before_backup_or_publication(self):
        lock = self.root / 'logs/upload.lock'
        lock.write_text('running')
        with patch.object(resume, 'publish_current') as publish:
            with self.assertRaises(RuntimeError):
                resume.resume(True)
        publish.assert_not_called()
        self.assertEqual(lock.read_text(), 'running')
        self.assertFalse((self.root / 'backups').exists())

    def test_unknown_result_from_retry_is_preserved_and_remaining_jobs_continue(self):
        calls = []
        def publish(account, target, label, **kwargs):
            key = kwargs['expected_key']
            calls.append(key)
            state = upload.read_json(self.state_path, {})
            state[key] = dict(account=account, target=target, status='needs_review',
                              url=self.entries[self.keys.index(key)]['url'])
            upload.save_json(self.state_path, state)
            raise upload.ReceiptNeedsReview('receipt unknown')
        with patch.object(resume, 'publish_current', side_effect=publish):
            self.assertEqual(resume.resume(True), 3)
            self.assertEqual(len(calls), 8)
            self.assertEqual(resume.resume(True), 3)
            self.assertEqual(len(calls), 8)

    def test_read_only_preview_preserves_everything(self):
        before = self.state_path.read_bytes()
        report = self.path.read_bytes()
        with patch.object(resume, 'publish_current') as publish:
            self.assertEqual(resume.resume(), 0)
        publish.assert_not_called()
        self.assertEqual(before, self.state_path.read_bytes())
        self.assertEqual(report, self.path.read_bytes())

    def test_conflicting_identity_or_success_evidence_blocks_retry(self):
        broken = copy.deepcopy(self.state)
        broken[self.keys[2]]['success_message'] = 'already posted'
        with self.assertRaisesRegex(ValueError, '成功证据'):
            resume.candidates(self.round, broken)
        broken[self.keys[2]].pop('success_message')
        broken[self.keys[2]]['account'] = 'fb99'
        with self.assertRaisesRegex(ValueError, '不一致'):
            resume.candidates(self.round, broken)

    def test_plan_only_report_does_not_replace_real_publication_round(self):
        newer = self.root / 'logs/current-audit-20261023-170000.json'
        upload.save_json(newer, dict(self.round, phase='plan_only'))
        path, _ = resume.load_round()
        self.assertEqual(path, self.path)

    def test_older_unattempted_report_row_does_not_retry_current_posting(self):
        self.state[self.keys[12]] = dict(account='fb13', target='page01', status='posting')
        jobs = resume.candidates(self.round, self.state)
        self.assertNotIn(self.keys[12], {r['key'] for r in jobs})


if __name__ == '__main__':
    unittest.main()
