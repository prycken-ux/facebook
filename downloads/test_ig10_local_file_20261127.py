"""Local CDP large-file regression; every HTTP request is intercepted, no IG posts."""
import copy,os,signal,subprocess,time,unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from test_ig10_workflow_20261127 import Fixture
import test_ig10_recorded_reels_20261127 as recorded
import ig10_common_20261127 as c
import ig10_browser_20261127 as ui
import ig10_engine_20261127 as engine

SIZE=187468160
ERROR='Locator.set_input_files: Cannot transfer files larger than 50Mb to a browser not co-located with the server'

class LocalFileTests(Fixture):
 def setUp(self):
  super().setUp();self.path,self.batch=self.plan();self.job=copy.deepcopy(self.batch['payload']['jobs'][0]);self.file=self.root/self.job['video']
  with self.file.open('wb') as stream:stream.truncate(SIZE)
  info=c.file_info(self.file);self.job.update(video_size=info['size'],video_sha256=info['sha256']);self.job['key']=c.digest(self.job)
  self.processes=[];real_popen=subprocess.Popen;real_args=engine.browser_args
  def popen(args,**kw):
   kw['start_new_session']=True;proc=real_popen(args,**kw);self.processes.append(proc);return proc
  def args(root,job,port):return real_args(root,job,port)+['--no-sandbox']
  def cleanup():
   for proc in self.processes:
    if proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL)
    proc.wait()
  self.addCleanup(cleanup);self.pw=sync_playwright().start();self.addCleanup(self.pw.stop)
  with patch.object(engine,'chrome',return_value=Path('/usr/bin/chromium')),patch.object(engine,'browser_args',side_effect=args),patch.object(engine.subprocess,'Popen',side_effect=popen):
   self.browser,self.context,self.page=engine.launch(self.pw,self.root,self.job,time.monotonic())
  self.addCleanup(self.browser.close)
  self.flow=recorded.RecordedFlowTests('runTest');self.flow.user=self.job['username'];self.flow.actual=self.job['username'];self.flow.comments=[];self.flow.shares=0;self.flow.comment_sends=0;self.flow.ai_when_shared=None;self.flow.api_available=True;self.flow.chinese_portal=False;self.flow.ai_initial=True;self.flow.ambiguous_ai=False;self.flow.portal=False;self.flow.delayed=False;self.flow.payloads=[]
  self.context.route('**/*',self.flow.route)
 def select(self,target=None,local=True):return ui.set_video_file(self.page,self.context,target or self.page.locator('#video'),self.root,self.job,time.monotonic(),local_browser=local)
 def test_actual_cdp_reproduces_guard_then_local_path_selects_full_original(self):
  self.page.set_content('<input id="video" type="file" accept="video/mp4"><script>window.events=[];for(const name of ["input","change"])document.addEventListener(name,e=>window.events.push(e.type));</script>')
  with self.assertRaisesRegex(Exception,'Cannot transfer files larger than 50Mb'):self.page.locator('#video').set_input_files(str(self.file))
  before=(self.root/'logs/ig-publication-state.json').read_bytes();evidence=self.select();self.assertEqual(evidence['video_file_transport'],'local_chrome_cdp_path');self.assertEqual(evidence['browser_selected_size'],SIZE);self.assertEqual(self.page.evaluate('window.events'),['input','change']);self.assertEqual(self.page.locator('#video').get_attribute('data-ig-local-upload'),None);self.assertEqual(c.file_info(self.file),dict(size=self.job['video_size'],sha256=self.job['video_sha256']));self.assertEqual((self.root/'logs/ig-publication-state.json').read_bytes(),before);self.assertFalse(self.flow.shares)
 def test_app_clears_and_detaches_input_after_change_still_verifies_original(self):
  self.page.set_content('<input id="video" type="file" accept="video/mp4" onchange="this.value=\'\';this.remove()">');handle=self.page.locator('#video').element_handle();evidence=self.select(handle);self.assertEqual(evidence['browser_selected_size'],SIZE);self.assertEqual(evidence['browser_selected_name'],self.file.name);self.assertEqual(handle.evaluate('(e)=>e.files.length'),0);self.assertEqual(handle.evaluate('(e)=>Object.keys(e).filter(k=>/^[0-9a-f]{32}$/.test(k))'),[]);handle.dispose()
 def test_nonlocal_large_file_or_changed_fingerprint_never_sets_input(self):
  self.page.set_content('<input id="video" type="file" accept="video/mp4">')
  with self.assertRaisesRegex(RuntimeError,'本机Chrome'):self.select(local=False)
  self.job['video_sha256']='0'*64
  with self.assertRaisesRegex(ValueError,'指纹变化'):self.select()
  self.assertEqual(self.page.locator('#video').evaluate('(e)=>e.files.length'),0);self.assertEqual(self.flow.shares,0)
 def test_same_size_wrong_browser_file_fails_before_share(self):
  self.page.set_content('<input id="video" type="file" accept="video/mp4" onchange="Object.defineProperty(this,\'files\',{value:[]})">')
  # Capture of the native change precedes app mutation; a wrong native selection must fail.
  wrong=self.file.with_name('wrong.mp4')
  with wrong.open('wb') as stream:stream.truncate(SIZE)
  real=self.context.new_cdp_session
  def session(page):
   original=real(page)
   class Session:
    def send(self,name,params):
     if name=='DOM.setFileInputFiles':params=dict(params,files=[str(wrong)])
     return original.send(name,params)
    def detach(self):return original.detach()
   return Session()
  with patch.object(self.context,'new_cdp_session',side_effect=session):
   with self.assertRaisesRegex(RuntimeError,'选中文件与原分配视频不符'):self.select()
  self.assertFalse(self.flow.shares)
 def test_full_recorded_flow_large_local_file_exact_caption_ai_off_comment_reload_dedup(self):
  ui.prepare_and_share(self.page,self.context,self.root,self.job,time.monotonic(),local_browser=True)
  row=c.state(self.root)[self.job['key']];self.assertEqual(row['video_status'],'published');self.assertEqual(row['video_file_transport'],'local_chrome_cdp_path');self.assertEqual(row['browser_selected_size'],SIZE);self.assertEqual(row['edit_advances'],2);self.assertEqual(self.flow.shares,1);payload=self.flow.payloads[0];self.assertEqual(payload['caption'],c.CAPTION);self.assertEqual(payload['ai'],'false');self.assertTrue(payload['audio']);self.assertFalse(payload['comments_disabled']);self.assertTrue(payload['original']);self.assertEqual(payload['backgroundNext'],0)
  ui.comment(self.page,self.context,self.root,self.job,time.monotonic());self.assertTrue(engine.verified(self.root,self.job));ui.comment(self.page,self.context,self.root,self.job,time.monotonic());self.assertEqual(self.flow.comment_sends,1);self.assertEqual(self.flow.shares,1)

class LocalFileGateTests(Fixture):
 def prepare(self):
  with (self.source/'1.mp4').open('wb') as stream:stream.truncate(SIZE)
  path,batch=self.plan();job=batch['payload']['jobs'][0];folder=self.root/'logs/diagnostics/ins01-large-file'
  c.save(folder/'diagnostic.json',dict(account=job['account'],username=job['username'],key=job['key'],kind='video',error=ERROR,page_url=ui.BASE+'/',visible_text='创建新帖子\n把照片和视频拖放到这里\n从电脑中选择'))
  c.update(self.root,job['key'],account=job['account'],username=job['username'],video_sha256=job['video_sha256'],batch_sha256=batch['sha256'],video_status='failed_before_post',identity=dict(username=job['username']),identity_verified_at=c.stamp(),creation_dialog_verified_at=c.stamp(),error=ERROR,diagnostic=str(folder.relative_to(self.root)))
  gate=dict(blocked=True,passed=False,batch_sha256=batch['sha256'],job_key=job['key'],navigation_syntax_repair='prior-nav',create_entry_repair='prior-create');return path,batch,job,gate
 def test_exact_pre_transfer_error_releases_once_with_audit_and_unchanged_ledger(self):
  _,batch,job,gate=self.prepare();before=(self.root/'logs/ig-publication-state.json').read_bytes();fixed=engine.recover_local_file_gate(self.root,batch,gate);self.assertFalse(fixed['blocked']);self.assertFalse(fixed['passed']);self.assertEqual(fixed['create_entry_repair'],'prior-create');audit=c.checked(self.root/fixed['local_file_repair']);self.assertEqual(audit['payload']['video_size'],SIZE);self.assertEqual(audit['payload']['gate_before'],gate);self.assertEqual((self.root/'logs/ig-publication-state.json').read_bytes(),before);again=dict(fixed,blocked=True);self.assertEqual(engine.recover_local_file_gate(self.root,batch,again),again)
 def test_any_submission_selection_comment_or_wrong_failure_keeps_gate(self):
  _,batch,job,gate=self.prepare();original=c.state(self.root)
  for field,value in [('post_intent_at',c.stamp()),('submit_click_returned_at',c.stamp()),('selected_file',job['video']),('selected_video_sha256',job['video_sha256']),('browser_file_verified_at',c.stamp()),('comment_send_intent_at',c.stamp()),('media_proof',{'code':'ABC'}),('error','Timeout'),('identity',dict(username='another'))]:
   c.update(self.root,job['key'],**{field:value});self.assertEqual(engine.recover_local_file_gate(self.root,batch,gate),gate);c.save(self.root/'logs/ig-publication-state.json',original)
  c.save(self.root/'logs/ig-comment-state.json',{'test':dict(video_job=job['key'])});self.assertEqual(engine.recover_local_file_gate(self.root,batch,gate),gate)
 def test_small_file_or_wrong_diagnostic_keeps_gate(self):
  _,batch,job,gate=self.prepare();job['video_size']=50*1024*1024;self.assertEqual(engine.recover_local_file_gate(self.root,batch,gate),gate);job['video_size']=SIZE;folder=self.root/c.state(self.root)[job['key']]['diagnostic'];data=c.read(folder/'diagnostic.json');data['username']='another';c.save(folder/'diagnostic.json',data);self.assertEqual(engine.recover_local_file_gate(self.root,batch,gate),gate)
 def test_repaired_trial_failure_holds_other_nine_and_cannot_be_released_again(self):
  path,batch,job,gate=self.prepare();c.save(self.root/'logs/ig-first-trial-20261127.json',gate);events=[]
  def operation(root,path,job,kind,run,status):events.append((job['account'],kind));c.update(root,job['key'],video_status='failed_before_post',error=ERROR);return 3
  self.assertEqual(engine.coordinator(self.root,path,'first',operation=operation),3);self.assertEqual(events,[('ins01','video')]);current=c.read(self.root/'logs/ig-first-trial-20261127.json');self.assertTrue(current['blocked']);self.assertTrue(current['local_file_repair']);self.assertEqual(current['create_entry_repair'],'prior-create');engine.coordinator(self.root,path,'again',operation=operation);self.assertEqual(len(events),1)

if __name__=='__main__':unittest.main()
