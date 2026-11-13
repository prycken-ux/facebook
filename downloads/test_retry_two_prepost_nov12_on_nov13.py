import copy
import unittest
from datetime import datetime
from unittest.mock import patch

import retry_two_prepost_nov12_on_nov13 as app
from test_retry_named_nov12_on_nov13 import NamedRetryTests


class TwoPrepostTests(unittest.TestCase):
    def setUp(self):
        self.fx = NamedRetryTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        parent_path, parent = app.base.prepare()
        self.parent_before = parent_path.read_bytes()
        self.parent_path = parent_path
        self.enterContext(patch.object(app, 'PARENT_PREFIX', parent['sha256'][:8]))
        clock = self.enterContext(patch.object(app, 'datetime', wraps=datetime))
        clock.now.return_value = self.fx.now
        self.jobs = [j for j in self.fx.jobs if (j['account'], j['target']) in app.SPEC]
        self.enterContext(patch.object(app, 'SPEC', {
            (j['account'], j['target']): (j['filename'], app.SPEC[(j['account'], j['target'])][1], j['key'][:12])
            for j in self.jobs
        }))
        state = app.base.upload.read_json(self.root/'logs/publish_state.json', {})
        for job in self.jobs:
            state[job['key']] = dict(account=job['account'], target=job['target'], url=job['url'],
                                    video=str(self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']),
                                    status='failed_before_post', uploader_version='2.47', ai_label_requested=False,
                                    created='2026-11-13T04:00:00+00:00', error='Locator.click: Timeout 5000ms exceeded.',
                                    repair_authorization=app.PARENT_GRANT, today_first_retry_used=True)
        self.before = copy.deepcopy(state)
        app.base.upload.save_json(self.root/'logs/publish_state.json', state)

    def core(self, **kwargs):
        with patch.object(app.base, 'execute', side_effect=app.execute):
            return self.fx.core(**kwargs)

    def test_only_two_exact_failed_jobs_retried_once_and_all_other_records_unchanged(self):
        result, posted, _ = self.core()
        self.assertEqual(result, 0)
        self.assertEqual(posted, list(app.SPEC))
        current = app.base.upload.read_json(self.root/'logs/publish_state.json', {})
        for key, row in self.before.items():
            if key not in {j['key'] for j in self.jobs}:
                self.assertEqual(current[key], row)
        for job in self.jobs:
            row = current[job['key']]
            self.assertEqual(row['status'], 'published')
            self.assertEqual(row['comment_status'], 'not_requested')
            self.assertEqual(row['previous_before_post_attempt']['repair_previous_attempt'], self.before[job['key']])
        self.assertEqual(self.parent_path.read_bytes(), self.parent_before)
        self.assertEqual(self.fx.comments_path.read_bytes(), self.fx.comment_bytes)
        _, posted, _ = self.core()
        self.assertEqual(posted, [])

    def test_unknown_receipt_never_gets_a_second_post_on_rerun(self):
        result, posted, _ = self.core(unknown=True)
        self.assertEqual(result, 3)
        self.assertEqual(len(posted), 2)
        _, posted, _ = self.core()
        self.assertEqual(posted, [])

    def test_existing_pending_or_submission_evidence_is_preserved(self):
        state = copy.deepcopy(self.before)
        first, second = self.jobs
        state[first['key']]['status'] = 'needs_review'
        state[first['key']]['post_intent_at'] = '2026-11-13T04:01:00+00:00'
        state[second['key']]['previous_before_post_attempt'] = dict(post_intent_at='2026-11-12T04:00:00+00:00')
        app.base.upload.save_json(self.root/'logs/publish_state.json', state)
        result, posted, _ = self.core()
        self.assertEqual(result, 3)
        self.assertEqual(posted, [])
        self.assertEqual(app.base.upload.read_json(self.root/'logs/publish_state.json', {}), state)

    def test_wrong_parent_or_replaced_file_never_selects_another_video(self):
        with patch.object(app, 'PARENT_PREFIX', 'ffffffff'):
            with self.assertRaisesRegex(ValueError, '原失败清单'):
                self.core()
        first = self.jobs[0]
        file = self.root/'videos'/first['account']/first['target']/'inbox'/first['filename']
        file.write_bytes(b'replaced file must stay unpublished')
        result, posted, _ = self.core()
        self.assertEqual(result, 3)
        self.assertEqual(posted, [tuple(self.jobs[1][k] for k in ('account', 'target'))])


if __name__ == '__main__':
    unittest.main()
