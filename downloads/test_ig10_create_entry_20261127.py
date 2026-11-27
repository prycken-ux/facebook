import json,time,unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from test_ig10_workflow_20261127 import Fixture
import ig10_common_20261127 as c
import ig10_browser_20261127 as ui
import ig10_engine_20261127 as engine

class EntryTests(Fixture):
 def setUp(self):
  super().setUp();_,self.batch=self.plan();self.job=self.batch['payload']['jobs'][0];self.pw=sync_playwright().start();self.addCleanup(self.pw.stop);self.browser=self.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);self.addCleanup(self.browser.close);self.page=self.browser.new_page();self.body='';self.page.route('**/*',self.route)
 def route(self,r):
  if '/api/v1/accounts/current_user/' in r.request.url:return r.fulfill(json=dict(status='ok',user=dict(username=self.job['username'],pk='123')))
  r.fulfill(content_type='text/html; charset=utf-8',body='<html><body>'+self.body+'</body></html>')
 def load(self,control,delay=0,portal=False,menu=False):
  show="document.getElementById('modal').style.display='block';window.clicks++"
  if delay:show="window.clicks++;setTimeout(()=>document.getElementById('modal').style.display='block',1200)"
  if menu:show="document.getElementById('menu').style.display='block';window.clicks++"
  control=control.replace('SHOW',show)
  self.body='<script>window.clicks=0;window.highlights=0;</script>'+control+'<button style="position:absolute;left:350px;top:50px" onclick="window.highlights++">新建</button>'
  self.body+='<div role="menu" id="menu" style="display:none"><button role="menuitem" onclick="document.getElementById(\'modal\').style.display=\'block\'">帖子</button></div>'
  self.body+='<input id="avatar" type="file" accept="image/*"><div '+('' if portal else 'role="dialog"')+' id="modal" style="display:none"><h2>创建新帖子</h2><p>把照片和视频拖放到这里</p><button>从电脑中选择</button><input type="file" accept="image/*,video/*"></div>'
  self.page.goto(ui.BASE+'/'+self.job['username']+'/')
 def opened(self):
  records=[];scope=ui.open_creation(self.page,self.job,time.monotonic(),record=lambda **v:records.append(v));self.assertIsNotNone(scope);self.assertEqual(self.page.evaluate('window.highlights'),0);self.assertEqual(self.page.evaluate('window.clicks'),1);self.assertEqual(self.page.locator('#avatar').input_value(),'');return records,scope
 def test_icon_only_chinese_new_post_and_central_highlight_exclusion(self):
  self.load('<div role="button" aria-label="icon" onclick="SHOW"><svg aria-label="新帖子" width="24" height="24"><path d="M0 12h24M12 0v24"/></svg></div>');records,_=self.opened();self.assertEqual(records[0]['creation_entry_method'],'sidebar_create_icon')
 def test_empty_profile_first_photo_is_valid_fallback(self):
  self.load('<a href="#" onclick="SHOW">分享你的首张照片</a>');records,_=self.opened();self.assertEqual(records[0]['creation_entry_method'],'empty_profile_first_photo')
 def test_portal_without_dialog_role_uses_observed_title_and_select_button(self):
  self.load('<button onclick="SHOW">创建</button>',portal=True);_,scope=self.opened();self.assertIs(scope,self.page)
 def test_delayed_dialog_waits_without_clicking_create_twice(self):
  self.load('<button onclick="SHOW">创建</button>',delay=1200);start=time.monotonic();self.opened();self.assertGreater(time.monotonic()-start,1)
 def test_delayed_creation_control_is_waited_for(self):
  self.load('<button id="create" style="display:none" onclick="SHOW">创建</button><script>setTimeout(()=>document.getElementById("create").style.display="block",1200)</script>');start=time.monotonic();self.opened();self.assertGreater(time.monotonic()-start,1)
 def test_plus_menu_post_path_opens_upload_dialog(self):
  self.load('<button onclick="SHOW">创建</button>',menu=True);self.opened()
 def test_missing_creation_never_clicks_central_highlight_and_respects_budget(self):
  self.load('');start=time.monotonic()
  with patch.object(ui,'CREATE_WAIT_SECONDS',.6):
   with self.assertRaisesRegex(RuntimeError,'未选择视频'):ui.open_creation(self.page,self.job,start)
  self.assertLess(time.monotonic()-start,2);self.assertEqual(self.page.evaluate('window.highlights'),0);self.assertEqual(self.page.locator('#avatar').input_value(),'')

 def test_creation_wait_never_clicks_an_unrelated_feed_comment_post(self):
  self.load('<button onclick="window.clicks++">创建</button><button onclick="window.spam=(window.spam||0)+1">Post</button>')
  with patch.object(ui,'CREATE_WAIT_SECONDS',.6):
   with self.assertRaisesRegex(RuntimeError,'未选择视频'):ui.open_creation(self.page,self.job,time.monotonic())
  self.assertEqual(self.page.evaluate('window.spam||0'),0)

class CreateRecoveryTests(Fixture):
 def setup_error(self):
  path,batch=self.plan();j=batch['payload']['jobs'][0];error='未找到Instagram创建入口，未选择视频';folder=self.root/'logs/diagnostics/create-failure';diag=dict(account=j['account'],username=j['username'],key=j['key'],kind='video',error=error,page_url=ui.BASE+'/'+j['username']+'/',visible_text=j['username']+'\n编辑主页\n分享你的首张照片');c.save(folder/'diagnostic.json',diag)
  c.update(self.root,j['key'],account=j['account'],username=j['username'],video_sha256=j['video_sha256'],batch_sha256=batch['sha256'],video_status='failed_before_post',error=error,diagnostic=str(folder.relative_to(self.root)),identity=dict(username=j['username']),identity_verified_at=c.stamp(),upload_started_at=c.stamp())
  gate=dict(batch_sha256=batch['sha256'],job_key=j['key'],blocked=True,passed=False,navigation_syntax_repair='logs/repairs/existing.json');c.save(self.root/'logs/ig-first-trial-20261127.json',gate);return path,batch,j,gate
 def test_known_pre_file_failure_recovers_once_and_preserves_ledger_and_prior_repair(self):
  path,batch,j,gate=self.setup_error();before=(self.root/'logs/ig-publication-state.json').read_bytes();fixed=engine.recover_create_entry_gate(self.root,batch,gate);self.assertFalse(fixed['blocked']);self.assertFalse(fixed['passed']);self.assertEqual(fixed['navigation_syntax_repair'],gate['navigation_syntax_repair']);self.assertTrue(fixed['create_entry_repair']);self.assertEqual((self.root/'logs/ig-publication-state.json').read_bytes(),before)
  audit=c.checked(self.root/fixed['create_entry_repair']);self.assertEqual(audit['payload']['gate_before'],gate);blocked=dict(fixed,blocked=True);self.assertEqual(engine.recover_create_entry_gate(self.root,batch,blocked),blocked)
 def test_selection_submission_or_comment_evidence_keeps_blocked(self):
  path,batch,j,gate=self.setup_error()
  for field in ['selected_file','selected_video_sha256','creation_entry_clicked_at','post_intent_at','submit_click_returned_at','comment_send_intent_at','media_proof']:
   before=c.state(self.root);c.update(self.root,j['key'],**{field:'evidence'});self.assertEqual(engine.recover_create_entry_gate(self.root,batch,gate),gate);c.save(self.root/'logs/ig-publication-state.json',before)
 def test_existing_comment_ledger_or_mismatched_diagnostic_keeps_blocked(self):
  path,batch,j,gate=self.setup_error();p=self.root/'logs/ig-comment-state.json';c.save(p,{'x':dict(video_job=j['key'],status='sending')});self.assertEqual(engine.recover_create_entry_gate(self.root,batch,gate),gate);p.unlink();diag=self.root/'logs/diagnostics/create-failure/diagnostic.json';data=c.read(diag);data['username']='other';c.save(diag,data);self.assertEqual(engine.recover_create_entry_gate(self.root,batch,gate),gate)
 def test_repair_that_fails_again_is_not_released_repeatedly(self):
  path,batch,j,gate=self.setup_error();events=[]
  def operation(root,path,j,kind,run,status):events.append((j['account'],kind));c.update(root,j['key'],error='new issue');return 3
  self.assertEqual(engine.coordinator(self.root,path,'create-fix',operation=operation),3);current=c.read(self.root/'logs/ig-first-trial-20261127.json');self.assertTrue(current['blocked']);self.assertTrue(current['create_entry_repair']);self.assertTrue(current['navigation_syntax_repair']);engine.coordinator(self.root,path,'again',operation=operation);self.assertEqual(events,[('ins01','video')])

 def test_recovered_batch_passes_first_proof_then_remaining9_and_rerun_is_noop(self):
  path,batch,j,gate=self.setup_error();events=[];manifest=path.read_bytes()
  def operation(root,path,job,kind,run,status):
   events.append((job['account'],kind));url='https://www.instagram.com/reel/TEST'+job['account']+'/'
   if kind=='video':c.update(root,job['key'],video_status='published',post_intent_at=c.stamp(),permalink=url,assumed_published=False)
   else:
    ledger=c.read(root/'logs/ig-comment-state.json',{});key=c.digest(dict(video_job=job['key'],text=c.COMMENT));ledger[key]=dict(video_job=job['key'],username=job['username'],text_sha256=c.digest(c.COMMENT),permalink=url,verification='own_comment_seen_after_reload',verified_at=c.stamp());c.save(root/'logs/ig-comment-state.json',ledger)
   return 0
  self.assertEqual(engine.coordinator(self.root,path,'fix-pass',operation=operation),0);self.assertEqual(len(events),20);fixed=c.read(self.root/'logs/ig-first-trial-20261127.json');self.assertTrue(fixed['passed']);self.assertTrue(fixed['create_entry_repair']);self.assertEqual(path.read_bytes(),manifest);engine.coordinator(self.root,path,'replay',operation=operation);self.assertEqual(len(events),20)

if __name__=='__main__':unittest.main()
