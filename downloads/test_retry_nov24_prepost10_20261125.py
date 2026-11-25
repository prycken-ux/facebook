import copy,contextlib,hashlib,io,re,unittest,os
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import retry_nov24_prepost10_20261125 as r
import publish_eligible60_real_20261124 as day
import publication_target_watchdog_20261124 as w
import test_publish_eligible60_real_20261124 as fixture

class EligibilityTests(unittest.TestCase):
    def setUp(self):
        pair=next(iter(r.EXPECTED));self.job=dict(account=pair[0],target=pair[1],filename=r.EXPECTED[pair]);self.row=dict(status='failed_before_post',error='Page.goto: net::ERR_CONNECTION_RESET')
    def eligible(self,row=None,job=None):return r.eligible(job or self.job,self.row if row is None else row,day.app.queued.has_submission)
    def test_known_prepost_error_allowed(self):self.assertTrue(self.eligible())
    def test_foreign_account_and_changed_filename_preserved(self):
        self.assertFalse(self.eligible(job=dict(self.job,account='fb04')));self.assertFalse(self.eligible(job=dict(self.job,filename='other.mp4')))
    def test_submission_nested_anywhere_is_preserved(self):
        for extra in [dict(status='needs_review'),dict(status='published'),dict(post_intent_at='x'),dict(repair_previous_attempt=dict(post_intent_at='old')),dict(permalink='https://www.facebook.com/reel/123')]:
            with self.subTest(extra=extra):self.assertFalse(self.eligible(dict(self.row,**extra)))
    def test_login_identity_and_unknown_error_are_not_retried(self):
        for text in ['Login required','遇到登录或安全验证。','账号限制 Timeout','身份不一致 Timeout','unrecognized issue']:
            with self.subTest(text=text):self.assertFalse(self.eligible(dict(self.row,error=text)))

class AdditionalGrantIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.Nov24PublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        self.output=io.StringIO();self.enterContext(contextlib.redirect_stdout(self.output))
        for file in self.root.rglob('*'):
            if file.is_file() and file.suffix.lower() in {'.mp4','.txt'}:os.utime(file,(datetime(2026,11,23,tzinfo=timezone.utc).timestamp(),)*2)
        # Freeze the real original60 allocation without uploading anything.
        with patch.object(day.app,'run_phase',return_value=None):self.fx.core()
        self.req=day.first.upload.read_json(self.root/day.REQUEST,{})
        self.controller=day.first.upload.read_json(self.root/'logs'/('eligible60-real-publication-'+self.req['sha256'][:16]+'.json'),{})
        self.jobs={ (j['account'],j['target']):j for wave in self.controller['waves'] for j in day.first.archive.checked_json(self.root/'logs'/wave['manifest'])['payload']['jobs'] }
        self.scope=set(r.EXPECTED);self.names={pair:self.jobs[pair]['filename'] for pair in self.scope}
        self.enterContext(patch.object(r,'EXPECTED',self.names));self.enterContext(patch.object(r,'REQUEST_PREFIX',self.req['sha256'][:16]))
        state=day.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for pair,job in self.jobs.items():
            wave=next(wave for wave in self.controller['waves'] if pair in {tuple(p) for p in wave['pairs']})
            row=dict(account=pair[0],target=pair[1],url=job['url'],video=str(day.first.upload.inbox_for(job)/job['filename']),uploader_version='2.47',ai_label_requested=False,created='2026-11-24T05:00:00+00:00',source_frozen_manifest=wave['manifest'],source_frozen_sha256=wave['sha256'])
            if pair in self.scope:row.update(status='failed_before_post',error='Page.goto: net::ERR_CONNECTION_RESET',failure_stage='open_target_profile',today_first_retry_used=True)
            elif pair[0]=='fb10':continue
            elif pair[0] in {'fb32','fb52'} or pair in {('fb09','page06'),('fb09','page09')}:row.update(status='failed_before_post',error='遇到登录或安全验证' if pair[0] in {'fb32','fb52'} else '个人主页和公共主页列表未加载，未选择视频或点击发布。')
            else:row.update(status='needs_review',post_intent_at='2026-11-24T06:00:00+00:00',error='awaiting publication confirmation')
            state[job['key']]=row
        day.first.upload.save_json(self.root/'logs/publish_state.json',state)
        self.before=copy.deepcopy(state);self.old_claims=dict(schema='automatic-before-post-retry-claims-v1',jobs={self.jobs[p]['key']:dict(phase='consumed',source_sha256='old-claim') for p in self.scope})
        day.first.upload.save_json(self.root/'logs/automatic_before_post_retry_claims.json',self.old_claims)
        self.fx.runfx.now=datetime(2026,11,25,3,tzinfo=timezone.utc)
        for clock in self.fx.runfx.clocks:clock.now.return_value=self.fx.runfx.now
        self.progress=self.root/'logs/retry10-test-progress.json';self.operation=self.root/'logs/retry10-test-operation.json'
    def core(self,unknown=False):
        for file in self.root.rglob('*'):
            if file.is_file() and file.suffix.lower() in {'.mp4','.txt'}:os.utime(file,(self.fx.runfx.now.timestamp()-180,)*2)
        w.files.save(self.progress,w.progress_new('run',self.req['sha256']))
        with r.installed(day),w.guarded_worker(day,self.root,'run','attempt',self.progress,self.operation):return self.fx.core(unknown=unknown)
    def test_only_ten_new_posts_and_comments_and_replay_zero(self):
        result,events,comments,calls=self.core();self.assertEqual(result,0)
        posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),10);self.assertEqual(set(posts),self.scope)
        state=day.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for pair,job in self.jobs.items():
            if pair in self.scope:self.assertEqual(state[job['key']]['status'],'published');self.assertEqual(state[job['key']]['comment_status'],'sent')
            else:self.assertEqual(state.get(job['key']),self.before.get(job['key']))
        self.assertEqual(day.first.upload.read_json(self.root/'logs/automatic_before_post_retry_claims.json',{}),self.old_claims)
        result,events,comments,calls=self.core();self.assertEqual(sum(e=='post' for e,p in events),0)
    def test_changed_to_pending_in_one_target_skips_it_preserving_other_nine(self):
        state=day.first.upload.read_json(self.root/'logs/publish_state.json',{});key=self.jobs[('fb03','personal')]['key'];state[key].update(status='needs_review',post_intent_at='already submitted');day.first.upload.save_json(self.root/'logs/publish_state.json',state)
        result,events,_,_=self.core();posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),9);self.assertNotIn(('fb03','personal'),posts)
        self.assertEqual(day.first.upload.read_json(self.root/'logs/publish_state.json',{})[key],state[key])
    def test_newly_paused_target_is_not_opened_or_posted(self):
        p=dict(schema='publication-account-exclusions-v1',excluded_accounts=sorted(day.app.BLOCKED|{'fb37'}))
        day.first.upload.save_json(self.root/day.app.AVAILABILITY,dict(payload=p,sha256=day.first.batch.digest(p)))
        result,events,_,calls=self.core();posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),9);self.assertNotIn(('fb37','personal'),posts)
        key=self.jobs[('fb37','personal')]['key'];self.assertEqual(day.first.upload.read_json(self.root/'logs/publish_state.json',{})[key],self.before[key])
    def test_unconfirmed_new_attempts_are_never_reuploaded_on_replay(self):
        result,events,_,_=self.core(unknown=True);self.assertEqual(sum(e=='post' for e,p in events),10)
        result,events,_,_=self.core(unknown=True);self.assertEqual(sum(e=='post' for e,p in events),0)

if __name__=='__main__':unittest.main()
