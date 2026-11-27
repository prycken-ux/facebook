import contextlib,copy,hashlib,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import setup_instagram10_browser_workspace_20261126 as setup
import register_instagram10_accounts_20261126 as register
import ig10_common_20261127 as c
import ig10_allocate_20261127 as allocation
import ig10_engine_20261127 as engine

class Fixture(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.root=self.base/'IG-AutoUpload';self.source=self.base/'IG素材';self.source.mkdir();chrome=self.base/'chrome.exe';chrome.write_bytes(b'fixture');desktop=self.base/'Desktop';desktop.mkdir()
  self.enterContext(contextlib.redirect_stdout(io.StringIO()));setup.prepare(self.root,chrome=chrome,desktop=desktop,writer=lambda *a,**k:None);register.apply(self.root)
  self.enterContext(patch.object(c,'today',return_value='2026-11-27'))
  for i in range(1,13):(self.source/f'{i}.mp4').write_bytes(('distinct IG clip '+str(i)).encode())
 def plan(self):return allocation.allocate(self.root,self.source)

class AllocationTests(Fixture):
 def test10_exact_mapping_natural_order_source_retained_extra_untouched_and_no_browser(self):
  before={p:p.read_bytes() for p in self.source.iterdir()};login=self.root/'profiles/ins01/Default/Login Data';login.parent.mkdir(parents=True);login.write_bytes(b'keep')
  with patch.object(engine,'run_operation',side_effect=AssertionError('Allocation must not post')):path,value=self.plan()
  self.assertEqual(len(value['payload']['jobs']),10);self.assertEqual([j['source_name'] for j in value['payload']['jobs']],[f'{i}.mp4' for i in range(1,11)])
  self.assertEqual({j['account']:j['username'] for j in value['payload']['jobs']},c.MAPPING)
  for p,b in before.items():self.assertEqual(p.read_bytes(),b)
  self.assertEqual(login.read_bytes(),b'keep');self.assertTrue(all((self.root/j['video']).is_file() for j in value['payload']['jobs']))
 def test_missing_or_duplicate_clips_never_create_partial_formal_allocation(self):
  for i in range(9,13):(self.source/f'{i}.mp4').unlink()
  (self.source/'copy.mp4').write_bytes((self.source/'1.mp4').read_bytes())
  with self.assertRaisesRegex(ValueError,'不足10'):self.plan()
  self.assertFalse(list((self.root/'videos').rglob('*.mp4')))
 def test_prior_fb_hash_is_allowed_for_this_ig_batch(self):
  fb=self.base/'FB-AutoUpload';p=dict(assignments=[dict(files=[dict(name='1.mp4',sha256=hashlib.sha256((self.source/'1.mp4').read_bytes()).hexdigest())])]);c.save(fb/'logs/material-distribution/fixture/2026-11-26-eligible58.json',dict(payload=p,sha256=c.digest(p)))
  _,value=self.plan();self.assertEqual([j['source_name'] for j in value['payload']['jobs']],[f'{i}.mp4' for i in range(1,11)])
 def test_resume_never_refills_submitted_video_or_changes_source(self):
  path,value=self.plan();before=path.read_bytes();j=value['payload']['jobs'][0];c.update(self.root,j['key'],post_intent_at=c.stamp(),video_status='needs_review');(self.root/j['video']).unlink();allocation.allocate(self.root);self.assertFalse((self.root/j['video']).exists());self.assertEqual(path.read_bytes(),before)
  with self.assertRaisesRegex(ValueError,'不换源'):allocation.allocate(self.root,self.base/'other')
 def test_wrong_mapping_and_fb_source_are_blocked(self):
  with self.assertRaisesRegex(ValueError,'FB'):allocation.source_folder(self.root,self.base/'FB-AutoUpload')
 def test_lost_ledger_after_initialization_is_not_defaulted(self):
  self.plan();(self.root/'logs/ig-publication-state.json').unlink()
  with self.assertRaisesRegex(ValueError,'账本缺失'):allocation.allocate(self.root)

class CoordinatorTests(Fixture):
 def perform(self,fail=None):
  path,batch=self.plan();events=[]
  def operation(root,path,j,kind,run,status):
   events.append((j['account'],kind))
   if fail==kind and j['account']=='ins01':c.update(root,j['key'],**({'video_status':'failed_before_post','error':'no create button'} if kind=='video' else {'comment_status':'failed_before_send','comment_error':'field missing'}));return 3
   url='https://www.instagram.com/reel/ABCD'+j['account']+'/'
   if kind=='video':c.update(root,j['key'],video_status='published',assumed_published=False,post_intent_at=c.stamp(),permalink=url)
   else:
    key=c.digest(dict(video_job=j['key'],text=c.COMMENT));ledger=c.read(root/'logs/ig-comment-state.json',{});ledger[key]=dict(video_job=j['key'],username=j['username'],text_sha256=c.digest(c.COMMENT),permalink=url,verification='own_comment_seen_after_reload',verified_at=c.stamp(),status='sent');c.save(root/'logs/ig-comment-state.json',ledger);c.update(root,j['key'],comment_status='sent',comment_verification='own_comment_seen_after_reload')
   return 0
  result=engine.coordinator(self.root,path,'run',operation=operation);return result,events,path,batch,operation
 def test_first_trial_then_all10_and_rerun_has_no_reuploads_or_duplicate_comments(self):
  result,events,path,batch,operation=self.perform();self.assertEqual(result,0);self.assertEqual(len(events),20);self.assertEqual(events[:2],[('ins01','video'),('ins01','comment')]);self.assertEqual(sum(k=='video' for a,k in events),10)
  before=len(events);engine.coordinator(self.root,path,'again',operation=operation);self.assertEqual(len(events),before);report=c.read(self.root/'logs/ig-2026-11-27-results.json');self.assertEqual(report['verified_comments'],10)
 def check_first_failure(self,kind):
  result,events,*_=self.perform(kind);self.assertEqual(result,3);self.assertEqual({a for a,k in events},{'ins01'});self.assertTrue(c.read(self.root/'logs/ig-first-trial-20261127.json')['blocked'])
 def test_failed_first_video_holds_other9(self):self.check_first_failure('video')
 def test_failed_first_comment_holds_other9(self):self.check_first_failure('comment')
 def test_gate_does_not_accept_status_sent_without_reload_evidence(self):
  path,batch=self.plan();j=batch['payload']['jobs'][0];c.update(self.root,j['key'],video_status='published',permalink='https://www.instagram.com/reel/ABCdef123/',comment_status='sent');self.assertFalse(engine.verified(self.root,j))


class DeadlineTests(Fixture):
 def test_real_blocking_operation_is_stopped_within_shared_budget_and_submission_retained(self):
  import signal,subprocess,time
  path,batch=self.plan();job=batch['payload']['jobs'][0];c.update(self.root,job['key'],post_intent_at=c.stamp(),submit_click_returned_at=c.stamp(),video_status='posting')
  children=[];outside=subprocess.Popen([__import__('sys').executable,'-c','import time;time.sleep(20)'])
  def cleanup_outside():
   if outside.poll() is None:outside.kill()
   outside.wait()
  self.addCleanup(cleanup_outside)
  class Owned:
   def __init__(self,args,env,cwd,output):
    # Same containment interface; real POSIX process group substitutes for the Windows Job.
    self.proc=subprocess.Popen([args[0],'-c','import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(20)"]);time.sleep(20)'],start_new_session=True,stdout=output,stderr=output);children.append(self)
   def poll(self):return self.proc.poll()
   def stop(self):os.killpg(self.proc.pid,signal.SIGKILL);self.proc.wait()
   def close(self):
    if self.poll() is None:self.stop()
  started=time.monotonic()
  with patch.object(c,'VIDEO_SECONDS',.5),patch.object(engine,'release_profile',side_effect=lambda *a:time.sleep(.3)):
   self.assertEqual(engine.run_operation(self.root,path,job,'video','r',lambda *a,**k:None,child_factory=Owned),3)
  self.assertLess(time.monotonic()-started,1.5);self.assertIsNotNone(children[0].poll());self.assertIsNone(outside.poll());row=c.state(self.root)[job['key']];self.assertEqual(row['video_status'],'needs_review');self.assertTrue(row['submit_click_returned_at'])
 def test_second_coordinator_preserves_live_status(self):
  path,_=self.plan();before=dict(phase='running',message='existing',pid=987);c.save(self.root/engine.STATUS,before)
  with patch.dict(os.environ,IG10_BATCH=str(path),IG10_RUN='second',IG10_ROLE='coordinator'),c.lock(self.root,'publisher'):
   self.assertEqual(engine.main(self.root),1)
  self.assertEqual(c.read(self.root/engine.STATUS),before);self.assertEqual(c.read(self.root/'logs/ig-launch-second.json')['phase'],'already_running')
 def test_profile_release_failure_preserves_uncertain_comment_intent(self):
  path,batch=self.plan();j=batch['payload']['jobs'][0];c.update(self.root,j['key'],comment_send_intent_at=c.stamp())
  with patch.object(engine,'release_profile',side_effect=RuntimeError('Visible modal remains')):
   self.assertEqual(engine.run_operation(self.root,path,j,'comment','r',lambda *a,**k:None),3)
  row=c.state(self.root)[j['key']];self.assertEqual(row['comment_status'],'needs_review');self.assertTrue(row['comment_send_intent_at'])
 def test_failed_child_setup_records_pre_submit_failure_without_opening_browser(self):
  path,batch=self.plan();j=batch['payload']['jobs'][0]
  with patch.object(engine,'release_profile'):
   self.assertEqual(engine.run_operation(self.root,path,j,'video','r',lambda *a,**k:None,child_factory=lambda *a:(_ for _ in ()).throw(RuntimeError('job setup failed'))),3)
  row=c.state(self.root)[j['key']];self.assertEqual(row['video_status'],'failed_before_post');self.assertFalse(c.submission(row))

if __name__=='__main__':unittest.main()
