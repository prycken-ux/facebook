import copy,contextlib,io,os,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import resume_nov25_selected18_20261126 as resume18
import publish_eligible60_real_20261125 as day
import resume18_target_watchdog_20261126 as watchdog
import test_publish_eligible60_real_20261125 as fixture

FAILED={('fb06','page01'),('fb07','personal'),('fb08','personal'),('fb11','personal')}
class EligibilityTests(unittest.TestCase):
    def test_only_named_unsubmitted_jobs_and_no_login_or_nested_submission(self):
        pair=next(iter(resume18.EXPECTED));job=dict(account=pair[0],target=pair[1],filename=resume18.EXPECTED[pair])
        submitted=day.app.queued.has_submission
        for row in [None,dict(status='not_started'),dict(status='failed_before_post',error='Target page, context or browser has been closed; resumed exact frozen job')]:self.assertTrue(resume18.eligible(job,row,submitted))
        for change in [dict(status='published'),dict(status='needs_review'),dict(status='posting'),dict(status='failed_before_post',error='Login required Timeout'),dict(status='failed_before_post',error='unknown'),dict(status='not_started',previous=dict(post_intent_at='already'))]:self.assertFalse(resume18.eligible(job,change,submitted))
        self.assertFalse(resume18.eligible(dict(job,filename='other.mp4'),None,submitted))

class Resume18IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.Nov25PublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        with patch.object(day.app,'run_phase',return_value=None):self.fx.core()
        first=day.first;self.req=first.upload.read_json(self.root/day.REQUEST,{})
        self.controller=first.upload.read_json(self.root/'logs'/('eligible60-real-publication-'+self.req['sha256'][:16]+'.json'),{})
        self.jobs={(j['account'],j['target']):j for wave in self.controller['waves'] for j in first.archive.checked_json(self.root/'logs'/wave['manifest'])['payload']['jobs']}
        self.scope=set(resume18.EXPECTED);self.enterContext(patch.object(resume18,'EXPECTED',{p:self.jobs[p]['filename'] for p in self.scope}));self.enterContext(patch.object(resume18,'REQUEST_PREFIX',self.req['sha256'][:16]))
        state=first.upload.read_json(self.root/'logs/publish_state.json',{})
        for pair,job in self.jobs.items():
            if pair in self.scope-FAILED:continue
            wave=next(w for w in self.controller['waves'] if pair in {tuple(p) for p in w['pairs']})
            row=dict(account=pair[0],target=pair[1],url=job['url'],video=str(first.upload.inbox_for(job)/job['filename']),uploader_version='2.47',ai_label_requested=False,created='2026-11-25T05:00:00+00:00',source_frozen_manifest=wave['manifest'],source_frozen_sha256=wave['sha256'])
            if pair in FAILED:row.update(status='failed_before_post',error='Target page, context or browser has been closed; resumed exact frozen job',failure_stage='open_target_profile',today_first_retry_used=True)
            elif pair[0] in {'fb32','fb52'}:row.update(status='failed_before_post',error='遇到登录或安全验证')
            else:row.update(status='published',post_intent_at='2026-11-25T05:01:00+00:00',comment_status='lookup_pending')
            state[job['key']]=row
        first.upload.save_json(self.root/'logs/publish_state.json',state);self.before=copy.deepcopy(state)
        self.old_claims=dict(schema='automatic-before-post-retry-claims-v1',jobs={self.jobs[p]['key']:dict(phase='consumed') for p in FAILED});first.upload.save_json(self.root/'logs/automatic_before_post_retry_claims.json',self.old_claims)
        self.fx.runfx.now=datetime(2026,11,26,3,tzinfo=timezone.utc)
        for clock in self.fx.runfx.clocks:clock.now.return_value=self.fx.runfx.now
        self.preflight=self.enterContext(patch.object(resume18,'preflight'))
        self.progress=self.root/'logs/resume18-test-progress.json';self.operation=self.root/'logs/resume18-test-operation.json'
    def core(self,unknown=False,network=False):
        for path in self.root.rglob('*'):
            if path.is_file() and path.suffix.lower() in {'.mp4','.txt'}:os.utime(path,(self.fx.runfx.now.timestamp()-180,)*2)
        watchdog.files.save(self.progress,watchdog.progress_new('run',self.req['sha256']))
        with resume18.installed(day),watchdog.guarded_worker(day,self.root,'run','attempt',self.progress,self.operation):return self.fx.core(unknown=unknown,network=network)
    def test_exact18_original_uploads_comments_and_replay_zero_preserve_other42(self):
        result,events,comments,calls=self.core();posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),18);self.assertEqual(set(posts),self.scope)
        self.assertEqual(set().union(*comments),{self.jobs[p]['key'] for p in self.scope})
        state=day.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for pair,job in self.jobs.items():
            if pair not in self.scope:self.assertEqual(state.get(job['key']),self.before.get(job['key']))
        self.assertEqual(day.first.upload.read_json(self.root/'logs/automatic_before_post_retry_claims.json',{}),self.old_claims)
        result,events,comments,calls=self.core();self.assertFalse(any(e=='post' for e,p in events))
        self.assertEqual(day.first.upload.read_json(self.root/resume18.RESULT,{})['published'],18)
    def test_preflight_failure_does_not_initialize_missing_jobs_or_submit(self):
        self.preflight.side_effect=ValueError('blocked fb10')
        with self.assertRaisesRegex(ValueError,'blocked fb10'):self.core()
        self.assertEqual(day.first.upload.read_json(self.root/'logs/publish_state.json',{}),self.before)
    def test_changed_to_submitted_target_never_reuploads_or_overwrites(self):
        path=self.root/'logs/publish_state.json';state=day.first.upload.read_json(path,{})
        key=self.jobs[('fb06','page01')]['key'];state[key].update(status='needs_review',post_intent_at='already submitted');day.first.upload.save_json(path,state)
        result,events,_,_=self.core();posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),17);self.assertNotIn(('fb06','page01'),posts)
        self.assertEqual(day.first.upload.read_json(path,{})[key],state[key])
    def test_one_new_prepost_failure_consumes_grant_and_replay_does_not_retry_again(self):
        result,events,_,_=self.core(network=True);self.assertEqual(sum(e=='post' for e,p in events),17)
        result,events,_,_=self.core();self.assertFalse(any(e=='post' for e,p in events))
        self.assertEqual(self.preflight.call_args.args[2],set())
    def test_timeout_assumptions_do_not_reupload_on_replay(self):
        result,events,_,_=self.core(unknown=True);self.assertEqual(sum(e=='post' for e,p in events),18)
        result,events,_,_=self.core(unknown=True);self.assertFalse(any(e=='post' for e,p in events))

class PreflightTests(unittest.TestCase):
    def test_busy_manual_window_is_reported_without_kill_or_other_accounts(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'logs').mkdir()
            with patch.object(resume18.profiles,'profile_owners',side_effect=lambda p:[dict(pid=123,name='chrome.exe')] if p.name=='fb10' else []),patch.object(watchdog,'release_idle',side_effect=RuntimeError('manual browser preserved')) as release:
                with self.assertRaisesRegex(ValueError,'fb10 PID 123'):resume18.preflight(day,root,{'fb01','fb10'})
            release.assert_called_once_with(day,root,'fb10')

if __name__=='__main__':unittest.main()
