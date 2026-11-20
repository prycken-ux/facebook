import copy
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import retry_nov19_textbox32_on_nov20 as retry
import test_publish_eligible60_materials_20261119 as base


class TwelveRetryTests(unittest.TestCase):
    def setUp(self):
        self.fx = base.Eligible60PublicationTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        self.app = retry.app
        original = self.fx.original_run
        failures = {a for a, t in retry.SPEC} | retry.SKIP_RETRY

        def fail_selected(entry, *args, **kwargs):
            if entry['account'] in failures:
                with patch.object(retry.first.upload, 'prepare_reel', side_effect=RuntimeError('Locator.input_value: Error: Node is not an <input>, <textarea> or <select> element')):
                    return original(entry, *args, **kwargs)
            return original(entry, *args, **kwargs)

        self.fx.original_run = fail_selected
        self.fx.core(unknown=True)
        self.req = retry.first.upload.read_json(self.root / self.app.REQUEST, {})
        self.control_path = self.root / 'logs' / ('eligible60-real-publication-' + self.req['sha256'][:16] + '.json')
        self.controller = retry.first.upload.read_json(self.control_path, {})
        self.jobs = {}
        for wave in self.controller['waves']:
            parent = retry.first.archive.checked_json(self.root / 'logs' / wave['manifest'])
            self.jobs.update({(j['account'], j['target']):j for j in parent['payload']['jobs']})
        self.enterContext(patch.object(retry, 'SPEC', {p:self.jobs[p]['filename'] for p in retry.SPEC}))
        self.enterContext(patch.object(retry, 'SOURCE_PREFIX', self.req['sha256'][:16]))
        self.before = copy.deepcopy(retry.first.upload.read_json(self.root / 'logs/publish_state.json', {}))
        self.request_bytes = (self.root / self.app.REQUEST).read_bytes()
        self.frozen = {self.root/'logs'/w['manifest']:(self.root/'logs'/w['manifest']).read_bytes() for w in self.controller['waves']}
        self.fx.runfx.now = datetime(2026, 11, 20, 6, tzinfo=timezone.utc)
        for clock in self.fx.runfx.clocks:
            clock.now.return_value = self.fx.runfx.now

    def run_retry(self, unknown=False, login=None):
        original = self.fx.original_run

        def run(entry, *args, **kwargs):
            if entry['account'] == login:
                with patch.object(retry.first.upload, 'prepare_reel', side_effect=RuntimeError('Login required for original account')):
                    return original(entry, *args, **kwargs)
            return original(entry, *args, **kwargs)

        with patch.object(self.app.workers, 'active_workers', return_value=[]), \
             patch.object(self.app.browser.staged.lock_recovery, 'recover_locks'), \
             patch.object(self.app.extra, 'wait_session'), \
             patch.object(self.app.extra, 'ensure_background_identity', side_effect=lambda f,p,e:f(p,e)), \
             patch.object(retry.first.upload, 'run_entry', side_effect=run), \
             patch.object(retry.first, 'execute', side_effect=lambda real:retry.execute(self.root)), \
             patch.object(self.app.owners.guided, 'prompt', side_effect=AssertionError('No manual dialogs in retry')):
            return self.fx.runfx.core(unknown=unknown, include_new=True)

    def test_exact12_once_preserves_others_and_40_43_and_original_freeze(self):
        # Allow the newly granted retry to succeed; initial failures stay frozen.
        self.fx.original_run = self.app.first.upload.run_entry
        result, events, comments = self.run_retry()
        self.assertEqual(result, 0)
        self.assertEqual({p for e,p in events if e=='post'}, set(retry.SPEC))
        self.assertEqual(sum(e=='post' for e,p in events), 32)
        state = retry.first.upload.read_json(self.root/'logs/publish_state.json', {})
        selected = {self.jobs[p]['key'] for p in retry.SPEC}
        for key, row in self.before.items():
            if key not in selected:
                self.assertEqual(state[key], row)
        self.assertTrue(all(state[k]['status']=='published' and state[k]['comment_status']=='sent' for k in selected))
        self.assertEqual((self.root/self.app.REQUEST).read_bytes(), self.request_bytes)
        for path,data in self.frozen.items():self.assertEqual(path.read_bytes(), data)
        result, events, comments = self.run_retry()
        self.assertFalse(any(e=='post' for e,p in events))

    def test_unknown_new_submissions_not_reuploaded_on_repeat(self):
        self.fx.original_run = self.app.first.upload.run_entry
        result,events,_ = self.run_retry(unknown=True)
        self.assertEqual(sum(e=='post' for e,p in events), 32)
        self.assertEqual(result, 3)
        _,events,_ = self.run_retry(unknown=True)
        self.assertFalse(any(e=='post' for e,p in events))

    def test_live_additional_pause_skipped_without_mutating_original_failure(self):
        self.fx.original_run = self.app.first.upload.run_entry
        payload=dict(schema='publication-account-exclusions-v1', excluded_accounts=sorted(self.app.PAUSED|{'fb32'}))
        retry.first.upload.save_json(self.root/self.app.AVAILABILITY,dict(payload=payload,sha256=retry.first.batch.digest(payload)))
        _,events,_ = self.run_retry()
        posts={p for e,p in events if e=='post'}
        self.assertEqual(posts,set(retry.SPEC)-{('fb32','personal')})
        key=self.jobs['fb32','personal']['key']
        self.assertEqual(retry.first.upload.read_json(self.root/'logs/publish_state.json',{})[key],self.before[key])

    def test_different_failure_now_is_preserved_without_new_attempt(self):
        self.fx.original_run = self.app.first.upload.run_entry
        path=self.root/'logs/publish_state.json'
        state=retry.first.upload.read_json(path,{})
        key=self.jobs['fb03','personal']['key']
        state[key]['error']='Encountered a different failure after the supplied log'
        retry.first.upload.save_json(path,state)
        before=copy.deepcopy(state[key])
        _,events,_=self.run_retry()
        self.assertEqual({p for e,p in events if e=='post'},set(retry.SPEC)-{('fb03','personal')})
        self.assertEqual(retry.first.upload.read_json(path,{})[key],before)

    def test_changed_filename_or_other_request_refused(self):
        with patch.object(retry, 'SOURCE_PREFIX', '0'*16):
            with self.assertRaisesRegex(ValueError,'不是日志指定'):self.run_retry()
        altered=dict(retry.SPEC);altered['fb03','personal']='wrong.mp4'
        with patch.object(retry, 'SPEC', altered):
            with self.assertRaisesRegex(ValueError,'文件名'):self.run_retry()

    def test_grant_excludes_paused_and_fb52(self):
        self.assertTrue(retry.SKIP_RETRY <= retry.paused_now(self.root))
        self.assertFalse({a for a,t in retry.SPEC}&retry.SKIP_RETRY)

    def test_submission_evidence_skips_even_when_labeled_prepost_failure(self):
        self.fx.original_run = self.app.first.upload.run_entry
        path=self.root/'logs/publish_state.json';state=retry.first.upload.read_json(path,{})
        key=self.jobs['fb03','personal']['key']
        state[key]['post_intent_at']=self.fx.runfx.now.isoformat()
        retry.first.upload.save_json(path,state)
        before=copy.deepcopy(state[key])
        _,events,_=self.run_retry()
        self.assertEqual({p for e,p in events if e=='post'},set(retry.SPEC)-{('fb03','personal')})
        self.assertEqual(retry.first.upload.read_json(path,{})[key],before)

    def test_previous_automatic_retry_failure_is_bound_and_gets_one_new_attempt(self):
        self.fx.original_run = self.app.first.upload.run_entry
        wave=self.controller['waves'][0]
        parent=retry.first.archive.checked_json(self.root/'logs'/wave['manifest'])
        value=copy.deepcopy(parent);job=self.jobs['fb03','personal']
        value['payload'].update(jobs=[job],run_kind='automatic-safe-retry-v1',
                                source_manifest=wave['manifest'],source_sha256=parent['sha256'])
        value['sha256']=retry.first.batch.digest(value['payload'])
        path=self.root/'logs'/('automatic-retry-2026-11-19-'+value['sha256'][:16]+'.json')
        retry.first.upload.save_json(path,value)
        state_path=self.root/'logs/publish_state.json';state=retry.first.upload.read_json(state_path,{})
        state[job['key']].update(source_frozen_manifest=path.name,source_frozen_sha256=value['sha256'])
        retry.first.upload.save_json(state_path,state);before=path.read_bytes()
        result,events,_=self.run_retry()
        self.assertEqual(result,0);self.assertEqual({p for e,p in events if e=='post'},set(retry.SPEC))
        self.assertEqual(path.read_bytes(),before)

class GrantPolicyTests(unittest.TestCase):
    def test_exact_diagnosed_scope_and_current_error_gate(self):
        self.assertEqual(len(retry.SPEC),32)
        self.assertTrue(all(t=='personal' for a,t in retry.SPEC))
        self.assertFalse({a for a,t in retry.SPEC} & (retry.app.BLOCKED | {'fb09','fb52'}))


class RetryChainTests(unittest.TestCase):
    def test_exact_retry_bootstrap_chain_exempts_self_only(self):
        import subprocess
        from test_nov16_venv_process_chain import VenvProcessChainTests
        f=VenvProcessChainTests();f.setUp();rows=copy.deepcopy(f.rows)
        body=f.body.replace('start_finish_first24_nov16','start_retry_nov19_textbox32_on_nov20').replace('verified-nov16-first24-and-nov14-stage','verified-nov19-textbox32-prepost-retry')
        runner=r'E:\FB-AutoUpload\material-staging\tools\new-retry12\retry_nov19_textbox32_on_nov20.py'
        for row in rows[:2]:row['command']=subprocess.list2cmdline([f.exe,'-u',runner,f.root])
        for row in rows[2:]:row['command']=subprocess.list2cmdline([f.exe,'-u','-c',body,f.root])
        rows.append(f.row(96,1,['-u',f.root+r'\publish_eligible60_materials_20261119.py',f.root]))
        with patch.object(retry.app.workers,'BOOTSTRAP',retry.BOOTSTRAP):workers,allowed=retry.app.workers.classify_workers(rows,f.root,100,runner)
        self.assertEqual(allowed,[97,98,99,100]);self.assertEqual([r['pid'] for r in workers],[96])


if __name__=='__main__':unittest.main()
