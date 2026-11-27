import copy,signal,os,sys,time,subprocess,unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from test_ig10_workflow_20261127 import Fixture
import ig10_common_20261127 as c
import ig10_engine_20261127 as engine
import build_ig10_starter_20261127 as builder

class SyntaxGateTests(Fixture):
 def setup_error(self):
  path,batch=self.plan();j=batch['payload']['jobs'][0];error="Page.evaluate: SyntaxError: Unexpected token '}'\n at eval (<anonymous>)";folder=self.root/'logs/diagnostics/ins01-video-fixture';c.save(folder/'diagnostic.json',dict(account=j['account'],username=j['username'],key=j['key'],kind='video',error=error,at=c.stamp()))
  c.update(self.root,j['key'],account=j['account'],username=j['username'],video_sha256=j['video_sha256'],batch_sha256=batch['sha256'],video_status='failed_before_post',error=error,diagnostic=str(folder.relative_to(self.root)))
  gate=dict(batch_sha256=batch['sha256'],job_key=j['key'],passed=False,blocked=True,checked_at=c.stamp());c.save(self.root/'logs/ig-first-trial-20261127.json',gate);return path,batch,j,gate
 def test_exact_pre_identity_syntax_error_has_one_audited_recovery_without_ledger_changes(self):
  path,batch,j,gate=self.setup_error();before=(self.root/'logs/ig-publication-state.json').read_bytes();fixed=engine.recover_navigation_syntax_gate(self.root,batch,gate)
  self.assertFalse(fixed['blocked']);self.assertFalse(fixed['passed']);self.assertTrue(fixed['navigation_syntax_repair']);self.assertEqual((self.root/'logs/ig-publication-state.json').read_bytes(),before)
  audit=c.checked(self.root/fixed['navigation_syntax_repair']);self.assertEqual(audit['payload']['gate_before'],gate);self.assertEqual(audit['payload']['row_before']['error'],c.state(self.root)[j['key']]['error'])
  blocked=dict(fixed,blocked=True);self.assertEqual(engine.recover_navigation_syntax_gate(self.root,batch,blocked),blocked)
 def test_submitted_or_comment_intent_cannot_release_gate(self):
  path,batch,j,gate=self.setup_error()
  for field,value in [('post_intent_at',c.stamp()),('submit_click_returned_at',c.stamp()),('permalink','https://www.instagram.com/reel/ABC123xyz/'),('identity_verified_at',c.stamp()),('upload_started_at',c.stamp()),('selected_file','clip.mp4'),('comment_send_intent_at',c.stamp())]:
   before=c.state(self.root);c.update(self.root,j['key'],**{field:value});self.assertEqual(engine.recover_navigation_syntax_gate(self.root,batch,gate),gate);c.save(self.root/'logs/ig-publication-state.json',before)
 def test_any_comment_ledger_evidence_keeps_gate(self):
  path,batch,j,gate=self.setup_error();c.save(self.root/'logs/ig-comment-state.json',{'comment':dict(video_job=j['key'],status='sending')});self.assertEqual(engine.recover_navigation_syntax_gate(self.root,batch,gate),gate)
 def test_unrelated_failure_or_wrong_diagnostic_keeps_gate(self):
  path,batch,j,gate=self.setup_error();c.update(self.root,j['key'],error='Timeout5000');self.assertEqual(engine.recover_navigation_syntax_gate(self.root,batch,gate),gate)
  c.update(self.root,j['key'],error="Page.evaluate: SyntaxError: Unexpected token '}'");self.assertEqual(engine.recover_navigation_syntax_gate(self.root,batch,gate),gate)
 def test_repaired_trial_failing_again_remains_blocked_without_second_release(self):
  path,batch,j,gate=self.setup_error();events=[]
  def operation(root,path,job,kind,run,status):events.append((job['account'],kind));c.update(root,job['key'],error='No Create button');return 3
  self.assertEqual(engine.coordinator(self.root,path,'fix',operation=operation),3);self.assertEqual(events,[('ins01','video')]);current=c.read(self.root/'logs/ig-first-trial-20261127.json');self.assertTrue(current['blocked']);self.assertTrue(current['navigation_syntax_repair']);engine.coordinator(self.root,path,'again',operation=operation);self.assertEqual(len(events),1)

class BackgroundTests(Fixture):
 def test_browser_arguments_use_original_profile_headless_and_never_visible_fallback(self):
  _,batch=self.plan();job=batch['payload']['jobs'][0]
  with patch.object(engine,'chrome',return_value=Path('chrome.exe')):
   args=engine.browser_args(self.root,job,1234);self.assertIn('--headless=new',args);self.assertNotIn('--new-window',args);self.assertIn('--mute-audio',args);self.assertIn('--user-data-dir='+str(self.root/'profiles/ins01'),args)
   with patch.object(engine.subprocess,'Popen',side_effect=OSError('fixture refusal')) as launch:
    with self.assertRaises(OSError):engine.launch(None,self.root,job,time.monotonic())
    self.assertEqual(launch.call_count,1);self.assertIn('--headless=new',launch.call_args.args[0])
 def test_starter_has_no_automatic_viewer_or_new_console_process(self):
  text=builder.TEMPLATE;self.assertNotIn('def viewer(',text);self.assertNotIn('0x00000010',text);self.assertNotIn('-NoExit',text);self.assertIn('creationflags=0x08000000',text)
 def test_real_cdp_headless_launch_reuses_profile_cookie_without_desktop_window(self):
  _,batch=self.plan();job=batch['payload']['jobs'][0];real_popen=subprocess.Popen;processes=[];real_args=engine.browser_args
  def popen(args,**kw):kw['start_new_session']=True;p=real_popen(args,**kw);processes.append(p);return p
  def args(root,job,port):return real_args(root,job,port)+['--no-sandbox']
  def cleanup():
   for p in processes:
    if p.poll() is None:os.killpg(p.pid,signal.SIGKILL)
    p.wait()
  self.addCleanup(cleanup)
  with sync_playwright() as pw,patch.object(engine,'chrome',return_value=Path('/usr/bin/chromium')),patch.object(engine,'browser_args',side_effect=args),patch.object(engine.subprocess,'Popen',side_effect=popen):
   b,ctx,page=engine.launch(pw,self.root,job,time.monotonic());ctx.add_cookies([dict(name='fixture_session',value='keep',domain='fixture.invalid',path='/',expires=time.time()+86400,secure=True)]);self.assertEqual(page.url,'about:blank');self.assertTrue(page.evaluate("()=>navigator.userAgent.includes('HeadlessChrome')"));b.new_browser_cdp_session().send('Browser.close');processes[-1].wait(timeout=10)
   b,ctx,page=engine.launch(pw,self.root,job,time.monotonic());self.assertIn('fixture_session',[x['name'] for x in ctx.cookies('https://fixture.invalid/')]);b.new_browser_cdp_session().send('Browser.close');processes[-1].wait(timeout=10)

if __name__=='__main__':unittest.main()
