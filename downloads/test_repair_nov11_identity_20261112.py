import copy
import unittest
from unittest.mock import MagicMock, patch

import repair_nov11_identity_20261112 as app
import test_recover_nov11_missed_20261112 as fixtures


class IdentityRepairTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.YesterdayMissedRecoveryTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        with patch.object(fixtures.app, 'discover_personal', side_effect=ValueError('no heading')):
            self.failed_path, self.failed = self.fx.prepare(lambda a: (_ for _ in ()).throw(ValueError('no heading')))
        self.assertEqual(len(self.failed['payload']['jobs']), 10)
        files = {account: next((self.root/'videos'/account/'personal/inbox').glob('*.mp4')).name for account in app.EXACT_FILES}
        self.fx.stack.enter_context(patch.object(app, 'EXACT_FILES', files))
        self.failed['issues'].extend(dict(account=a, filename=n, reason='date excluded') for a,n in files.items())
        app.upload.save_json(self.failed_path, self.failed)
        self.fx.stack.enter_context(patch.object(app, 'FAILED_PREFIX', self.failed['sha256'][:8]))
        self.fx.stack.enter_context(patch.object(fixtures.app, 'yesterday_file', return_value=True))
        state = app.upload.read_json(self.fx.fx.f.state_path, {})
        for job in self.failed['payload']['jobs']:
            state[job['key']] = dict(account=job['account'], target=job['target'], url=job['url'],
                                     video=str(self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']), status='failed_before_post')
        app.upload.save_json(self.fx.fx.f.state_path, state)
        self.before = self.fx.fx.f.state_path.read_bytes()
        self.failed_before = self.failed_path.read_bytes()
        self.clock = self.fx.stack.enter_context(patch.object(app, 'datetime', wraps=fixtures.datetime))
        self.clock.now.return_value = fixtures.datetime(2026,11,12,4,tzinfo=fixtures.timezone.utc)

    def prepare(self):
        with patch.object(app, 'page_preflight') as gate, patch.object(app, 'discover_personal', side_effect=self.fx.discovered):
            result = app.prepare(self.fx.path, self.fx.parent)
        return result, gate

    def test_new_source_retries_exact_ten_and_adds_five_without_touching_old_ledgers(self):
        (path, value), gate = self.prepare()
        self.assertEqual(len(value['payload']['jobs']), 15)
        self.assertEqual(value['payload']['jobs'][:10], self.failed['payload']['jobs'])
        app.validate(path, value, self.fx.parent)
        self.assertEqual(gate.call_count, 1)
        for job in value['payload']['jobs']:
            app.old.batch.validate_job(job, date=app.old.RUN_DATE)
        self.assertEqual(self.fx.fx.f.state_path.read_bytes(), self.before)
        self.assertEqual(self.failed_path.read_bytes(), self.failed_before)
        self.assertEqual(self.fx.main_pointer.read_bytes(), self.fx.pointer_before)
        self.assertEqual(self.fx.today_pointer.read_bytes(), self.fx.today_before)
        self.assertEqual(self.fx.old_ledger.read_bytes(), self.fx.ledger_before)
        self.assertNotEqual(path, self.failed_path)

    def test_submitted_unknown_success_or_used_retry_is_rejected_before_browser(self):
        state = app.upload.read_json(self.fx.fx.f.state_path, {})
        key = self.failed['payload']['jobs'][0]['key']
        for change in ({'status':'needs_review'}, {'post_intent_at':'2026-11-12'}, {'status':'published'}, {'today_first_retry_used':True}):
            changed = copy.deepcopy(state)
            changed[key].update(change)
            app.upload.save_json(self.fx.fx.f.state_path, changed)
            with patch.object(app, 'page_preflight') as gate:
                with self.assertRaisesRegex(ValueError, '发布前失败'):
                    app.prepare(self.fx.path, self.fx.parent)
            gate.assert_not_called()

    def test_failed_first_page_gate_never_creates_another_ten_job_batch(self):
        with patch.object(app, 'page_preflight', side_effect=ValueError('wrong actor')), patch.object(app, 'discover_personal') as discover:
            with self.assertRaisesRegex(ValueError, 'wrong actor'):
                app.prepare(self.fx.path, self.fx.parent)
        discover.assert_not_called()
        self.assertFalse((self.root/'logs'/app.POINTER).exists())
        self.assertEqual(self.fx.fx.f.state_path.read_bytes(), self.before)

    def test_rerun_resumes_same_source_without_reconnecting_or_resetting_attempt(self):
        (path, value), _ = self.prepare()
        state = app.upload.read_json(self.fx.fx.f.state_path, {})
        state[value['payload']['jobs'][0]['key']].update(status='needs_review', post_intent_at='submitted')
        app.upload.save_json(self.fx.fx.f.state_path, state)
        with patch.object(app, 'page_preflight', side_effect=AssertionError('frozen')), patch.object(app, 'discover_personal', side_effect=AssertionError('frozen')):
            self.assertEqual(app.prepare(self.fx.path, self.fx.parent), (path,value))
        self.assertEqual(app.upload.read_json(self.fx.fx.f.state_path, {}), state)

    def test_injecting_another_file_into_failed_page_is_rejected(self):
        (path, value), _ = self.prepare()
        bad = copy.deepcopy(value)
        bad['payload']['jobs'][0]['filename'] = 'other.mp4'
        bad['sha256'] = app.old.batch.digest(bad['payload'])
        path = path.with_name('frozen-material-'+app.old.RUN_DATE+'-'+bad['sha256'][:16]+'.json')
        with self.assertRaises(ValueError):
            app.validate(path, bad, self.fx.parent)

    def test_execution_uses_repair_source_then_videos_retry_comments_and_restores_hooks(self):
        (path, value), _ = self.prepare()
        events = []
        launch = app.upload.launch_context
        ensure = app.upload.ensure_identity
        with patch.object(app, 'prepare', return_value=(path, value)), patch.object(app.old, 'require_day'), patch.object(app.old, 'recover_locks'), \
             patch.object(app.old.normal, 'launcher_for_jobs', return_value=MagicMock()) as launcher, \
             patch('playwright.sync_api.sync_playwright'), patch.object(app.old, 'close_selected_window'), patch.object(app.old.local, 'self_check'), \
             patch.object(app.old.batch, 'run', side_effect=lambda *a,**k:events.append(('videos',a,k))), \
             patch.object(app.old.priority.retry, 'run', side_effect=lambda *a:events.append(('retry',a,{}))), \
             patch.object(app.old.priority.daily, 'backfill', side_effect=lambda *a,**k:events.append(('comments',a,k))), \
             patch.object(app.old.priority.comment_retry, 'run', side_effect=lambda *a,**k:events.append(('comment_retry',a,k))), \
             patch.object(app.old.batch, 'results'):
            self.assertEqual(app.execute(), 3)
        self.assertEqual([e[0] for e in events], ['videos','retry','comments','comment_retry'])
        self.assertEqual(events[0][1][0], path)
        self.assertTrue(events[0][2]['retry_before_post'])
        self.assertTrue(events[0][2]['defer_comments'])
        self.assertEqual(events[2][2]['only_keys'], {j['key'] for j in value['payload']['jobs']})
        launcher.assert_called_once_with(value['payload']['jobs'], date=app.old.RUN_DATE)
        self.assertIs(app.upload.launch_context, launch)
        self.assertIs(app.upload.ensure_identity, ensure)
        self.assertEqual(self.fx.fx.f.state_path.read_bytes(), self.before)


if __name__ == '__main__':
    unittest.main()
