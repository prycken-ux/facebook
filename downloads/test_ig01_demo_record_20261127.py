import importlib.util,json,os,sys,subprocess,time,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from test_ig10_workflow_20261127 import Fixture
import ig10_common_20261127 as c
import ig10_engine_20261127 as engine
import record_ig01_demo_20261127 as rec
import build_ig01_recorder_20261127 as builder

class PureTests(Fixture):
 def test_publish_network_is_blocked_but_video_upload_and_queries_can_render(self):
  for u in ['https://www.instagram.com/api/v1/media/configure_to_clips/','https://www.instagram.com/api/v1/web/comments/123/add/','https://www.instagram.com/api/v1/direct_v2/threads/broadcast/text/']:
   self.assertTrue(rec.blocked_request('POST',u))
  self.assertTrue(rec.blocked_request('POST','https://www.instagram.com/api/graphql','fb_api_req_friendly_name=CreateMediaMutation'))
  self.assertFalse(rec.blocked_request('POST','https://www.instagram.com/api/graphql','fb_api_req_friendly_name=ProfileQuery'))
  self.assertFalse(rec.blocked_request('POST','https://www.instagram.com/rupload_igvideo/fixture'))
  self.assertFalse(rec.blocked_request('GET','https://www.instagram.com/api/v1/media/123/info/'))
 def test_event_projection_omits_values_passwords_arbitrary_fields_and_video_bytes(self):
  value=rec.clean_event(dict(kind='change',cookies='secret',target=dict(tag='INPUT',type='file',value='secret',authorization='secret'),files=[dict(name='C:\\fakepath\\clip.mp4',size=10,type='video/mp4',bytes='secret')]))
  self.assertNotIn('secret',json.dumps(value));self.assertEqual(value['files'][0]['name'],'clip.mp4');self.assertIsNone(rec.clean_event(dict(kind='field_edit',target=dict(type='password',value='secret'))))
 def test_current_known_desktop_is_used_instead_of_default_profile_desktop(self):
  real=self.base/'RedirectedDesktop';real.mkdir()
  with patch.object(rec,'known_desktop',return_value=real):self.assertEqual(rec.desktop(self.root),real)
 def test_visible_mode_is_only_for_recorder_original_publisher_stays_headless(self):
  _,batch=self.plan();j=batch['payload']['jobs'][0]
  with patch.object(engine,'chrome',return_value=Path('chrome.exe')):
   args=rec.visible_args(self.root,j,9999);self.assertNotIn('--headless=new',args);self.assertIn('--new-window',args);self.assertIn('--user-data-dir='+str(self.root/'profiles/ins01'),args);self.assertIn('--headless=new',engine.browser_args(self.root,j,9999))
 def test_probe_capsule_has_exact_bytes_and_does_not_modify_publication_ledgers(self):
  _,batch=self.plan();c.save(self.root/'logs/ig-comment-state.json',{'existing':dict(status='sending')});c.save(self.root/'logs/ig-first-trial-20261127.json',dict(blocked=True));before=rec.fingerprints(self.root);entry=builder.build()
  result=subprocess.run([sys.executable,str(entry),str(self.root)],env=dict(os.environ,IG_DEMO_PROBE_ONLY='1'),capture_output=True,text=True,timeout=20);self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('IG DEMO VERIFIED',result.stdout);self.assertEqual(rec.fingerprints(self.root),before)
  spec=importlib.util.spec_from_file_location('demo_capsule',entry);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);cache=module.unpack(self.root)
  for name in builder.NAMES:self.assertEqual((cache/name).read_bytes(),(builder.HERE/name).read_bytes())
 def test_recording_and_publisher_cannot_run_together(self):
  self.plan()
  with c.lock(self.root,'publisher'):
   with self.assertRaisesRegex(RuntimeError,'已有IG任务'):rec.run(self.root)

 def test_startup_failure_still_exports_diagnostic_and_preserves_original_ledgers(self):
  self.plan();before=rec.fingerprints(self.root)
  with patch.object(engine,'release_profile',side_effect=RuntimeError('manual editor still open')),patch.object(rec,'launch',side_effect=AssertionError('Should not open Chrome')):
   self.assertEqual(rec.run(self.root),3)
  self.assertEqual(rec.fingerprints(self.root),before);archive=next((self.root/'logs').glob('IG-demo-record-*.zip'))
  with zipfile.ZipFile(archive) as z:self.assertIn('manual editor still open',z.read('recording.json').decode())
 def test_binary_video_request_body_is_never_read_or_recorded(self):
  _,batch=self.plan();recorder=rec.Recorder(self.root,batch['payload']['jobs'][0],batch)
  class Request:
   method='POST';url='https://www.instagram.com/rupload_igvideo/clip'
   @property
   def post_data(self):raise AssertionError('Must not decode video body')
  class Route:
   request=Request();continued=False
   def continue_(self):self.continued=True
   def abort(self,reason):raise AssertionError('Video preparation must remain available')
  route=Route();recorder.route(route);self.assertTrue(route.continued);self.assertFalse(recorder.pending)

class BrowserRecordTests(Fixture):
 def setUp(self):
  super().setUp();_,batch=self.plan();self.j=batch['payload']['jobs'][0];self.rec=rec.Recorder(self.root,self.j,batch);self.pw=sync_playwright().start();self.addCleanup(self.pw.stop);self.browser=self.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);self.addCleanup(self.browser.close);self.context=self.browser.new_context();self.page=self.context.new_page();self.rec.install(self.context,self.page)
  self.html='''<a href="/ted47868/" aria-label="Profile">Profile</a><script>window.shared=0;window.posted=0;window.menued=0;window.submitted=0;</script>
  <button id="next" onclick="document.getElementById('stage').textContent='填写说明'">下一步</button><div id="stage">裁剪</div>
  <button id="share" onclick="window.shared++"><span><svg aria-label="Share" width="20" height="20"></svg>分享</span></button>
  <button id="post" onclick="window.posted++">Post</button><div role="menu"><button role="menuitem" id="menu" onclick="window.menued++">Post</button></div>
  <textarea aria-label="Write a caption"></textarea><input type="file" accept="video/*"><form onsubmit="window.submitted++;return false"><button type="submit" id="submit">Send form</button></form>'''
  self.context.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body='<html><body>'+self.html+'</body></html>'))
  self.page.goto('https://www.instagram.com/ted47868/');self.rec.active=True
 def test_click_steps_and_screenshots_export_without_ledgers_cookies_or_video(self):
  c.save(self.root/'logs/ig-first-trial-20261127.json',dict(blocked=True));self.rec.before=rec.fingerprints(self.root);self.rec.capture('开始');self.page.locator('#next').click();self.page.locator('textarea').fill('PRIVATE_TYPED_VALUE');self.page.locator('input[type="file"]').set_input_files(dict(name='clip.mp4',mimeType='video/mp4',buffer=b'video bytes'));self.page.wait_for_timeout(400);self.rec.drain();self.rec.capture('文案')
  desktop=self.base/'VisibleDesktop';desktop.mkdir()
  with patch.object(rec,'known_desktop',return_value=desktop):path=self.rec.export('test')
  self.assertEqual(path.parent,desktop);self.assertEqual(rec.fingerprints(self.root),self.rec.before)
  with zipfile.ZipFile(path) as z:
   self.assertTrue(any(n.endswith('.png') for n in z.namelist()));self.assertFalse(any(n.endswith(('.mp4','.har','.html')) for n in z.namelist()));value=json.loads(z.read('recording.json'));self.assertTrue(value['publication_ledgers_unchanged']);self.assertFalse(value['automatic_publication_invoked']);self.assertNotIn('PRIVATE_TYPED_VALUE',json.dumps(value['events']));self.assertTrue(any(x.get('files') for x in value['events']))
 def test_share_inner_svg_post_and_form_submit_are_blocked_but_menu_post_allowed(self):
  self.page.locator('#share svg').click();self.page.locator('#post').click();self.page.locator('#submit').click();self.page.locator('#menu').click();self.page.wait_for_timeout(300);self.rec.drain();self.assertEqual(self.page.evaluate('window.shared'),0);self.assertEqual(self.page.evaluate('window.posted'),0);self.assertEqual(self.page.evaluate('window.submitted'),0);self.assertEqual(self.page.evaluate('window.menued'),1);self.assertGreaterEqual(sum(e['kind']=='blocked_publish' for e in self.rec.events),2)
 def test_finish_button_stops_recording_and_hooks_compile(self):
  self.page.get_by_role('button',name='结束记录并打包').click();self.page.wait_for_timeout(100);self.assertTrue(self.rec.drain());self.assertTrue(any(x['kind']=='finish' for x in self.rec.events));self.page.evaluate("(s)=>{new Function(s);return true;}",rec.HOOK)
 def test_login_password_page_does_not_capture_fields_or_screenshot(self):
  self.page.evaluate("()=>{const p=document.createElement('input');p.type='password';document.body.append(p)}");self.page.locator('input[type="password"]').fill('DO_NOT_RECORD');self.page.wait_for_timeout(100);self.rec.drain();self.assertFalse(any('DO_NOT_RECORD' in str(x) for x in self.rec.events))
  with self.assertRaisesRegex(ValueError,'登录页'):self.rec.capture('login')
 def test_media_configure_request_is_aborted_without_transmitting(self):
  # Route handlers run newest first; leave only the recorder's guard for this request.
  self.context.unroute('**/*');self.context.route('**/*',self.rec.route)
  self.assertTrue(self.page.evaluate("async()=>{try{await fetch('/api/v1/media/configure_to_clips/',{method:'POST',body:'not transmitted'});return false;}catch(e){return true;}}"));self.rec.drain();self.assertTrue(any(x['kind']=='blocked_network_publish' for x in self.rec.events))

 def test_advanced_ai_switch_state_is_recorded(self):
  self.page.evaluate("()=>{const e=document.createElement('div');e.setAttribute('role','switch');e.setAttribute('aria-label','AI label');e.setAttribute('aria-checked','false');e.textContent='AI';e.onclick=()=>e.setAttribute('aria-checked','true');document.body.append(e);}")
  self.page.get_by_role('switch',name='AI label').click();self.page.wait_for_timeout(150);self.rec.drain();self.rec.capture('AI设置');snapshot=c.read(self.rec.folder/self.rec.frames[-1]['controls']);switch=next(x for x in snapshot['controls'] if x.get('role')=='switch');self.assertEqual(switch['checked'],'true');self.assertTrue(any(x.get('target',{}).get('role')=='switch' for x in self.rec.events))

if __name__=='__main__':unittest.main()
