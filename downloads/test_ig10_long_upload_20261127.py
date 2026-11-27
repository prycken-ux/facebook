"""Preserved submitted history, one user-confirmed retry, actual browser wait/proof."""
import contextlib,copy,json,time,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse
from test_ig10_workflow_20261127 import Fixture
from test_ig10_browser_20261127 import BrowserFixture
import ig10_common_20261127 as c
import ig10_engine_20261127 as engine
import ig10_browser_20261127 as ui
import ig10_confirmed_absence_20261127 as retry

class ConfirmedAbsenceTests(Fixture):
 def prepare(self):
  path,batch=self.plan();first=batch['payload']['jobs'][0];video=dict(account='ins01',username=first['username'],key=first['key'],kind='video',error='submitted without receipt',page_url=ui.BASE+'/'+first['username']+'/',visible_text='正在分享\n0帖子');folder=self.root/'logs/diagnostics/ins01-video-5567c3ab';c.save(folder/'diagnostic.json',video);comment=dict(video,kind='comment',error='no unique video',visible_text='0帖子\n分享你的首张照片');c.save(self.root/'logs/diagnostics/ins01-comment-fixture/diagnostic.json',comment)
  row=dict(account='ins01',username=first['username'],video_sha256=first['video_sha256'],batch_sha256=batch['sha256'],video_status='needs_review',assumed_published=True,post_intent_at=c.stamp(),submit_click_returned_at=c.stamp(),diagnostic='logs/diagnostics/ins01-comment-fixture',error=video['error'],comment_error=comment['error'],comment_status='failed_before_send');c.save(self.root/'logs/ig-publication-state.json',{first['key']:row})
  gate=dict(blocked=True,passed=False,batch_sha256=batch['sha256'],job_key=first['key'],recorded_crop_repair='old-crop');c.save(self.root/'logs/ig-first-trial-20261127.json',gate)
  for name,value in [('SOURCE_BATCH',batch['sha256']),('SOURCE_JOB',first['key']),('SOURCE_VIDEO',first['video_sha256']),('SOURCE_ROW_SHA',c.digest(row))]:self.enterContext(patch.object(retry,name,value))
  return path,batch,first,gate,copy.deepcopy(row)
 def test_permit_preserves_parent_row_and_has_distinct_deterministic_attempt_key(self):
  _,batch,first,gate,old=self.prepare();before=(self.root/'logs/ig-publication-state.json').read_bytes();value=retry.plan(self.root,batch,gate,True);self.assertEqual(value['payload']['original_row'],old);new=retry.job(self.root,batch,first);self.assertNotEqual(new['key'],first['key']);self.assertEqual(new['video'],first['video']);self.assertEqual((self.root/'logs/ig-publication-state.json').read_bytes(),before);self.assertEqual(retry.plan(self.root,batch,gate,True),value)
 def test_unreviewed_state_or_changed_checkpoint_never_gets_a_new_permit(self):
  _,batch,first,gate,old=self.prepare();c.update(self.root,first['key'],comment_send_intent_at=c.stamp());self.assertIsNone(retry.plan(self.root,batch,gate,True));c.save(self.root/'logs/ig-publication-state.json',{first['key']:old});retry.plan(self.root,batch,gate,True);c.update(self.root,first['key'],permalink='https://www.instagram.com/reel/LATE123abc/')
  with self.assertRaisesRegex(ValueError,'原提交记录已变化'):retry.job(self.root,batch,first)
 def test_worker_refuses_unclaimed_or_already_used_retry_without_opening_browser(self):
  path,batch,first,gate,old=self.prepare();retry.plan(self.root,batch,gate,True);j=retry.job(self.root,batch,first)
  with patch.dict(engine.os.environ,IG10_RUN='run'),patch.object(engine,'launch',side_effect=OSError('fixture Chrome refusal')) as launch:
   with self.assertRaisesRegex(ValueError,'许可已消耗'):engine.worker(self.root,path,j['key'],'video',time.monotonic())
   self.assertFalse(launch.called);c.update(self.root,j['key'],retry_claimed_at=c.stamp(),retry_run_id='run');self.assertEqual(engine.worker(self.root,path,j['key'],'video',time.monotonic()),3)
   with self.assertRaisesRegex(ValueError,'许可已消耗'):engine.worker(self.root,path,j['key'],'video',time.monotonic())
   self.assertEqual(launch.call_count,1)
  self.assertEqual(c.state(self.root)[first['key']],old)
 def test_pre_share_failure_spends_only_one_attempt_and_retains_original_submission(self):
  path,batch,first,gate,old=self.prepare();events=[]
  def operation(root,path,j,kind,run,status):events.append((j['key'],kind));c.update(root,j['key'],video_status='failed_before_post',error='Timeout browser closed');return 3
  self.assertEqual(engine.coordinator(self.root,path,'once',operation),3);self.assertEqual(len(events),1);self.assertNotEqual(events[0][0],first['key']);engine.coordinator(self.root,path,'twice',operation);self.assertEqual(len(events),1);self.assertEqual(c.state(self.root)[first['key']],old)
 def test_post_click_reentry_only_reconciles_comment_without_another_upload(self):
  path,batch,first,gate,old=self.prepare();events=[]
  def operation(root,path,j,kind,run,status):
   events.append((j['account'],kind))
   if kind=='video':c.update(root,j['key'],video_status='needs_review',post_intent_at=c.stamp(),submit_click_returned_at=c.stamp())
   else:c.update(root,j['key'],comment_status='failed_before_send')
   return 3
  engine.coordinator(self.root,path,'once',operation);engine.coordinator(self.root,path,'twice',operation);self.assertEqual(events,[('ins01','video'),('ins01','comment'),('ins01','comment')]);self.assertEqual(c.state(self.root)[first['key']],old)
 def test_first_retry_proof_and_comment_release_other_nine_without_modifying_parent(self):
  path,batch,first,gate,old=self.prepare();manifest=path.read_bytes();events=[]
  def operation(root,path,j,kind,run,status):
   events.append((j['account'],kind));url='https://www.instagram.com/reel/GOOD'+j['account']+'/'
   if kind=='video':c.update(root,j['key'],video_status='published',assumed_published=False,post_intent_at=c.stamp(),permalink=url)
   else:
    key=c.digest(dict(video_job=j['key'],text=c.COMMENT));ledger=c.read(root/'logs/ig-comment-state.json',{});ledger[key]=dict(video_job=j['key'],username=j['username'],text_sha256=c.digest(c.COMMENT),permalink=url,verification='own_comment_seen_after_reload',verified_at=c.stamp(),status='sent');c.save(root/'logs/ig-comment-state.json',ledger)
   return 0
  self.assertEqual(engine.coordinator(self.root,path,'once',operation),0);self.assertEqual(len(events),20);engine.coordinator(self.root,path,'twice',operation);self.assertEqual(len(events),20);self.assertEqual(c.state(self.root)[first['key']],old);self.assertEqual(path.read_bytes(),manifest);report=c.read(self.root/'logs/ig-2026-11-27-results.json');self.assertEqual(report['confirmed_videos'],10);self.assertEqual(report['assumed_videos'],0);self.assertEqual(report['verified_comments'],10);self.assertTrue(report['rows'][0]['prior_assumed_published'])

class LongUploadBrowserTests(BrowserFixture):
 def intercept(self,transform):
  original=self.route
  def route(r):
   if '/rupload_igvideo/' in r.request.url:return r.fulfill(status=200,body='{}',content_type='application/json')
   class Wrapped:
    request=r.request
    def abort(self,*a,**k):return r.abort(*a,**k)
    def fulfill(self,*a,**k):
     if 'body' in k:k['body']=transform(k['body'])
     return r.fulfill(*a,**k)
   return original(Wrapped())
  self.context.unroute('**/*');self.context.route('**/*',route)
 def test_video_budget_is_30_minutes_comment_budget_is_three_minutes(self):self.assertEqual(c.VIDEO_SECONDS,1800);self.assertEqual(c.COMMENT_SECONDS,180)
 def test_actual_chromium_waits_past_old_180_second_cutoff_for_delayed_share_receipt(self):
  def transform(body):
   script="""<script>window.delayedConfigure=options=>{document.body.insertAdjacentHTML('beforeend','<div>正在分享</div>');return new Promise(resolve=>setTimeout(()=>fetch('/rupload_igvideo/fixture',{method:'POST',body:'fixture'}).then(()=>fetch('/api/v1/media/configure_to_clips/',options)).then(resolve),1300));};</script>"""
   return body.replace("fetch('/api/v1/media/configure_to_clips/',",'delayedConfigure(')+script
  self.intercept(transform)
  with patch.object(c,'update',wraps=c.update) as update:ui.prepare_and_share(self.page,self.context,self.root,self.job,time.monotonic()-190)
  row=c.state(self.root)[self.job['key']];self.assertEqual(row['video_status'],'published');self.assertEqual(row['sharing_ui_state'],'published');self.assertEqual(self.shares,1);self.assertEqual(row['upload_transport_summary']['started'],1);self.assertEqual(row['upload_transport_summary']['http_statuses'],[200]);self.assertIn('sharing_in_progress',[call.kwargs.get('sharing_ui_state') for call in update.call_args_list]);ui.comment(self.page,self.context,self.root,self.job,time.monotonic());self.assertTrue(engine.verified(self.root,self.job));self.assertEqual(self.comment_sends,1)
 def test_still_sharing_at_budget_is_pending_without_assumed_platform_success(self):
  def transform(body):return body.replace("fetch('/api/v1/media/configure_to_clips/',",'pendingConfigure(')+"<script>window.pendingConfigure=options=>{document.body.insertAdjacentHTML('beforeend','<div>正在分享</div>');return new Promise(()=>{});};</script>"
  self.intercept(transform)
  original_update=c.update
  def record(*args,**fields):
   original_update(*args,**fields)
   # Expire the test budget only after the real DOM reports Sharing; creation
   # and editor setup keep their normal budgets and are not mocked away.
   if fields.get('sharing_ui_state')=='sharing_in_progress':c.VIDEO_SECONDS=1
  with patch.object(c,'VIDEO_SECONDS',1800),patch.object(c,'update',side_effect=record),patch('playwright.sync_api.sync_playwright',return_value=contextlib.nullcontext(self.pw)),patch.object(engine,'launch',return_value=(self.browser,self.context,self.page)):
   self.assertEqual(engine.worker(self.root,self.path,self.job['key'],'video',time.monotonic()),3)
  row=c.state(self.root)[self.job['key']];self.assertIn('submit_click_returned_at',row,row);self.assertTrue(row['submit_click_returned_at']);self.assertEqual(row['video_status'],'needs_review');self.assertFalse(row['assumed_published']);self.assertEqual(row['sharing_ui_state'],'sharing_in_progress');self.assertEqual(self.shares,0);self.assertFalse(row.get('comment_send_intent_at'))
 def test_fresh_empty_profile_and_reels_are_required_before_retry_selection(self):
  def transform(body):return body+'<p>0帖子</p>'
  self.intercept(transform);ui.verify_confirmed_absence(self.page,self.root,self.job,time.monotonic());observations=c.state(self.root)[self.job['key']]['retry_absence_observations'];self.assertEqual([x['path'] for x in observations],['profile','reels','profile']);self.assertEqual(self.shares,0);self.assertEqual(self.page.locator('#video').evaluate('(e)=>e.files.length'),0)
 def test_late_video_link_or_nonempty_profile_prevents_reupload(self):
  visits=[]
  def transform(body):visits.append(True);return body+'<p>0帖子</p>'+('<a href="/reel/LATE123abc/">Late video</a>' if len(visits)>1 else '')
  self.intercept(transform)
  with self.assertRaisesRegex(RuntimeError,'主页不再明确为空'):ui.verify_confirmed_absence(self.page,self.root,self.job,time.monotonic())
  self.assertEqual(len(visits),2);self.assertEqual(self.shares,0);self.assertEqual(self.page.locator('#video').evaluate('(e)=>e.files.length'),0)
 def test_profile_receipt_recovery_includes_valid_video_more_than_ten_minutes_after_share(self):
  media=dict(code='TRIALabc123',user=dict(username=self.user,pk='123'),caption=dict(text=c.CAPTION),taken_at=time.time(),media_type=2)
  self.intercept(lambda body:body+'<script type="application/json">'+json.dumps(dict(media=media))+'</script>');now=datetime.now(timezone.utc);row=dict(upload_started_at=(now-timedelta(seconds=1000)).isoformat(),post_intent_at=(now-timedelta(seconds=990)).isoformat(),baseline_codes=[])
  url,proof=ui.recover(self.page,self.job,row,dict(username=self.user,pk='123'),time.monotonic());self.assertEqual(url,'https://www.instagram.com/reel/TRIALabc123/');self.assertEqual(proof['owner'],self.user)

if __name__=='__main__':unittest.main()
