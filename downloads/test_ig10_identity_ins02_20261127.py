"""Wait for authenticated navigation; bind user-authorized ins02 trial to 045d4f2b."""
import contextlib,copy,time,unittest
from unittest.mock import patch
from test_ig10_workflow_20261127 import Fixture
from test_ig10_browser_20261127 import BrowserFixture
import test_ig10_long_upload_20261127 as prior
import ig10_common_20261127 as c
import ig10_browser_20261127 as ui
import ig10_engine_20261127 as engine
import ig10_confirmed_absence_20261127 as absence

class IdentityReadinessTests(BrowserFixture):
 def intercept(self,transform):
  original=self.route
  def route(r):
   class Wrapped:
    request=r.request
    def abort(self,*a,**k):return r.abort(*a,**k)
    def fulfill(self,*a,**k):
     if 'body' in k:k['body']=transform(k['body'])
     return r.fulfill(*a,**k)
   return original(Wrapped())
  self.context.unroute('**/*');self.context.route('**/*',route)
 def test_delayed_own_navigation_after_api_403_waits_then_completes_video_and_comment(self):
  self.api_available=False
  def transform(body):return body.replace('aria-label="Profile"','id="own-nav" style="display:none" aria-label="Profile"')+"<script>setTimeout(()=>document.getElementById('own-nav').style.display='inline',1000)</script>"
  self.intercept(transform);self.upload();self.assertEqual(c.state(self.root)[self.job['key']]['identity']['verification_source'],'own_profile_navigation');ui.comment(self.page,self.context,self.root,self.job,time.monotonic());self.assertTrue(engine.verified(self.root,self.job));self.assertEqual(self.shares,1);self.assertEqual(self.comment_sends,1)
 def test_missing_navigation_never_uses_visited_profile_as_login_and_records_sanitized_evidence(self):
  self.api_available=False;anchor='<a href="/'+self.user+'/" aria-label="Profile">Profile</a>';self.intercept(lambda body:body.replace(anchor,'<h1>'+self.user+'</h1>'))
  with patch.object(ui,'IDENTITY_NAV_WAIT_SECONDS',.3),patch('playwright.sync_api.sync_playwright',return_value=contextlib.nullcontext(self.pw)),patch.object(engine,'launch',return_value=(self.browser,self.context,self.page)):
   self.assertEqual(engine.worker(self.root,self.path,self.job['key'],'video',time.monotonic()),3)
  row=c.state(self.root)[self.job['key']];self.assertEqual(row['video_status'],'failed_before_post');self.assertFalse(c.submission(row));self.assertNotIn('selected_file',row);e=row['identity_failure_evidence'];self.assertEqual(e['api_status'],403);self.assertEqual(e['navigation_candidates'],[]);self.assertEqual(set(e),{'api_status','api_outcome','navigation_candidates','navigation_wait_seconds'});self.assertEqual(self.shares,0)
 def test_ambiguous_sidebar_candidates_are_not_guessed(self):
  self.api_available=False;self.intercept(lambda body:body+'<a style="position:fixed;left:8px;top:150px" aria-label="Profile" href="/another_actor/">Other</a>');self.page.goto(ui.BASE+'/'+self.user+'/')
  with patch.object(ui,'IDENTITY_NAV_WAIT_SECONDS',.3):
   with self.assertRaises(ui.SessionProblem) as error:ui.actor(self.page,self.user)
  self.assertEqual(set(error.exception.identity_evidence['navigation_candidates']),{self.user,'another_actor'});self.assertEqual(self.shares,0)
 def test_login_redirect_during_navigation_wait_requires_manual_handling(self):
  self.api_available=False;anchor='<a href="/'+self.user+'/" aria-label="Profile">Profile</a>';self.intercept(lambda body:body.replace(anchor,'')+"<script>setTimeout(()=>location.href='/accounts/login/',300)</script>");self.page.goto(ui.BASE+'/'+self.user+'/')
  with patch.object(ui,'IDENTITY_NAV_WAIT_SECONDS',2):
   with self.assertRaisesRegex(ui.SessionProblem,'登录已失效'):ui.actor(self.page,self.user)
  self.assertEqual(self.shares,0)
 def test_own_navigation_without_trailing_slash_is_verified(self):
  self.api_available=False;self.intercept(lambda body:body.replace('href="/'+self.user+'/" aria-label="Profile"','href="/'+self.user+'" aria-label="Profile"'));self.page.goto(ui.BASE+'/'+self.user+'/');self.assertEqual(ui.actor(self.page,self.user)['username'],self.user)

class Ins02FallbackTests(Fixture):
 def prepare(self):
  path,batch,first,gate,parent=prior.ConfirmedAbsenceTests.prepare(self);permit=absence.plan(self.root,batch,gate,True);j=absence.job(self.root,batch,first);folder=self.root/'logs/diagnostics/ins01-identity-failed';error='无法唯一核对当前登录账号，未用个人主页网址代替登录证据'
  c.save(folder/'diagnostic.json',dict(account='ins01',username=first['username'],key=j['key'],kind='video',error=error));c.update(self.root,j['key'],account='ins01',username=first['username'],video_sha256=first['video_sha256'],batch_sha256=batch['sha256'],retry_of=first['key'],retry_authorization=permit['sha256'],retry_claimed_at=c.stamp(),retry_worker_started_at=c.stamp(),video_status='failed_before_post',error=error,diagnostic=str(folder.relative_to(self.root)))
  failed=c.state(self.root)[j['key']];self.enterContext(patch.object(absence,'FAILED_RETRY_SHA',c.digest(failed)));gate.update(effective_job_key=j['key'],absence_retry_authorization=permit['sha256']);c.save(self.root/'logs/ig-first-trial-20261127.json',gate);return path,batch,gate,copy.deepcopy(c.state(self.root))
 def test_exact_reviewed_checkpoint_can_switch_without_changing_either_ins01_row_or_gate(self):
  _,batch,gate,before=self.prepare();oldgate=(self.root/'logs/ig-first-trial-20261127.json').read_bytes();value=absence.fallback(self.root,batch,gate,True);self.assertEqual(value['payload']['target_account'],'ins02');self.assertEqual(c.state(self.root),before);self.assertEqual((self.root/'logs/ig-first-trial-20261127.json').read_bytes(),oldgate);self.assertEqual(absence.fallback(self.root,batch),value)
 def test_changed_preflight_or_submission_evidence_does_not_authorize_fallback(self):
  _,batch,gate,before=self.prepare();key=gate['effective_job_key']
  for field in ['selected_file','upload_started_at','post_intent_at','comment_send_intent_at']:
   c.update(self.root,key,**{field:'unexpected'});self.assertIsNone(absence.fallback(self.root,batch,gate,True));c.save(self.root/'logs/ig-publication-state.json',before)
  value=absence.fallback(self.root,batch,gate,True);c.update(self.root,key,error='new checkpoint')
  with self.assertRaisesRegex(ValueError,'原诊断不符'):absence.fallback(self.root,batch)
 def test_failed_ins02_holds_eight_and_replay_does_not_reupload_it(self):
  path,batch,gate,before=self.prepare();events=[];oldgate=(self.root/'logs/ig-first-trial-20261127.json').read_bytes()
  def operation(root,path,j,kind,run,status):events.append((j['account'],kind));c.update(root,j['key'],video_status='failed_before_post',error='identity unavailable');return 3
  self.assertEqual(engine.coordinator(self.root,path,'try02',operation),3);self.assertEqual(events,[('ins02','video')]);engine.coordinator(self.root,path,'again',operation);self.assertEqual(len(events),1);self.assertEqual((self.root/'logs/ig-first-trial-20261127.json').read_bytes(),oldgate)
  for key,value in before.items():self.assertEqual(c.state(self.root)[key],value)
  self.assertTrue(c.read(self.root/'logs/ig-first-trial-ins02-20261127.json')['blocked']);self.assertEqual(c.read(self.root/'logs/ig-2026-11-27-results.json')['skipped_targets'],1)
 def test_verified_ins02_releases_ins03_through_ins10_and_reports_nine_plus_one_skipped(self):
  path,batch,gate,before=self.prepare();manifest=path.read_bytes();oldgate=(self.root/'logs/ig-first-trial-20261127.json').read_bytes();events=[]
  def operation(root,path,j,kind,run,status):
   events.append((j['account'],kind));url='https://www.instagram.com/reel/GOOD'+j['account']+'/'
   if kind=='video':c.update(root,j['key'],video_status='published',assumed_published=False,post_intent_at=c.stamp(),permalink=url)
   else:
    key=c.digest(dict(video_job=j['key'],text=c.COMMENT));ledger=c.read(root/'logs/ig-comment-state.json',{});ledger[key]=dict(video_job=j['key'],username=j['username'],text_sha256=c.digest(c.COMMENT),permalink=url,verification='own_comment_seen_after_reload',verified_at=c.stamp(),status='sent');c.save(root/'logs/ig-comment-state.json',ledger)
   return 0
  self.assertEqual(engine.coordinator(self.root,path,'try02',operation),0);self.assertEqual(events[:2],[('ins02','video'),('ins02','comment')]);self.assertEqual(len(events),18);self.assertNotIn('ins01',[a for a,k in events]);engine.coordinator(self.root,path,'again',operation);self.assertEqual(len(events),18)
  for key,value in before.items():self.assertEqual(c.state(self.root)[key],value)
  self.assertEqual(path.read_bytes(),manifest);self.assertEqual((self.root/'logs/ig-first-trial-20261127.json').read_bytes(),oldgate);result=c.read(self.root/'logs/ig-2026-11-27-results.json');self.assertEqual(result['confirmed_videos'],9);self.assertEqual(result['verified_comments'],9);self.assertEqual(result['skipped_targets'],1);self.assertTrue(result['rows'][0]['skipped_by_user']);self.assertEqual(c.read(self.root/engine.STATUS)['phase'],'finished_with_skipped')

if __name__=='__main__':unittest.main()
