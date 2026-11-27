"""Real Chromium tests; all Instagram traffic is intercepted with fixture HTML/JSON."""
import html,json,time,unittest
from unittest.mock import patch
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from test_ig10_workflow_20261127 import Fixture
import ig10_common_20261127 as c
import ig10_browser_20261127 as ui
import ig10_engine_20261127 as engine

class BrowserTests(Fixture):
 def setUp(self):
  super().setUp();self.path,self.batch=self.plan();self.job=self.batch['payload']['jobs'][0];self.user=self.job['username'];self.comments=[];self.shares=0;self.comment_sends=0;self.actual=self.user;self.ai_when_shared=None;self.api_available=True
  self.pw=sync_playwright().start();self.addCleanup(self.pw.stop);self.browser=self.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);self.addCleanup(self.browser.close);self.context=self.browser.new_context();self.context.route('**/*',self.route);self.page=self.context.new_page();self.page.set_default_timeout(2000)
 def route(self,r):
  p=urlparse(r.request.url)
  if p.hostname!='www.instagram.com':return r.abort()
  if p.path.startswith('/api/v1/accounts/current_user/'):
   if not self.api_available:return r.fulfill(status=403,json={'status':'fail'})
   return r.fulfill(json=dict(status='ok',user=dict(username=self.actual,pk='123',is_private=False)))
  if p.path.startswith('/api/v1/media/configure'):
   self.shares+=1;data=r.request.post_data_json;self.ai_when_shared=data['ai'];return r.fulfill(json=dict(status='ok',media=dict(code='TRIALabc123',user=dict(username=self.user,pk='123'),caption=dict(text=c.CAPTION),taken_at=time.time(),media_type=2)))
  if p.path=='/fixture-comment':
   self.comment_sends+=1;self.comments.append(r.request.post_data_json['text']);return r.fulfill(json={'ok':True})
  if p.path=='/reel/TRIALabc123/':
   comments=''.join('<li><h3><a href="/'+self.user+'/">'+self.user+'</a></h3><span>'+html.escape(t)+'</span></li>' for t in self.comments)
   body='<a href="/'+self.user+'/" aria-label="Profile">Profile</a><article><header><a href="/'+self.user+'/">'+self.user+'</a></header><p>'+html.escape(c.CAPTION)+'</p><video></video><ul>'+comments+'</ul><form onsubmit="event.preventDefault();fetch(\'/fixture-comment\',{method:\'POST\',body:JSON.stringify({text:this.querySelector(\'textarea\').value})})"><textarea aria-label="Add a comment"></textarea><button>Post</button></form></article>'
  else:
   body='''<a href="/ACTOR/" aria-label="Profile">Profile</a><button onclick="document.getElementById('modal').style.display='block'">Create</button>
   <input type="file" accept="image/*" id="avatar"><div role="dialog" id="modal" style="display:none">
   <div id="stage1"><input type="file" accept="video/*" id="video"><button onclick="document.getElementById('stage1').remove();document.getElementById('stage2').style.display='block'">Next</button></div>
   <div id="stage2" style="display:none"><button onclick="document.getElementById('stage2').remove();document.getElementById('stage3').style.display='block'">Next</button></div>
   <div id="stage3" style="display:none"><div contenteditable="true" role="textbox"></div><button>Advanced settings</button>
   <div id="ai" role="switch" aria-label="AI label" aria-checked="true" onclick="this.setAttribute('aria-checked',this.getAttribute('aria-checked')==='true'?'false':'true')">AI</div>
   <div role="switch" aria-label="Turn off commenting" aria-checked="true" onclick="this.setAttribute('aria-checked',this.getAttribute('aria-checked')==='true'?'false':'true')">Comments</div>
   <button onclick="fetch('/api/v1/media/configure_to_clips/',{method:'POST',body:JSON.stringify({ai:document.getElementById('ai').getAttribute('aria-checked')})}).then(()=>document.body.insertAdjacentHTML('beforeend','<p>Your reel has been shared</p>'))">Share</button></div></div>'''.replace('ACTOR',self.actual)
  r.fulfill(content_type='text/html',body='<html><body>'+body+'</body></html>')
 def upload(self):ui.prepare_and_share(self.page,self.context,self.root,self.job,time.monotonic())
 def test_real_chromium_upload_exact_actor_ai_off_comment_reload_and_no_duplicate(self):
  self.upload();self.assertEqual(self.shares,1);self.assertEqual(self.ai_when_shared,'false');self.assertEqual(c.state(self.root)[self.job['key']]['video_status'],'published')
  self.assertEqual(c.state(self.root)[self.job['key']]['selected_video_sha256'],self.job['video_sha256']);ui.comment(self.page,self.context,self.root,self.job,time.monotonic());self.assertTrue(engine.verified(self.root,self.job));self.assertEqual(self.comment_sends,1)
  ui.comment(self.page,self.context,self.root,self.job,time.monotonic());self.assertEqual(self.comment_sends,1)
 def test_wrong_logged_in_actor_never_uploads_or_shares(self):
  self.actual='another_user'
  with self.assertRaisesRegex(ui.SessionProblem,'账号不匹配'):self.upload()
  self.assertEqual(self.shares,0);self.assertFalse(c.submission(c.state(self.root).get(self.job['key'],{})))
 def test_unknown_prior_comment_intent_never_resends(self):
  self.upload();c.update(self.root,self.job['key'],comment_send_intent_at=c.stamp())
  with self.assertRaisesRegex(RuntimeError,'未重复发送'):ui.comment(self.page,self.context,self.root,self.job,time.monotonic())
  self.assertEqual(self.comment_sends,0)
 def test_metadata_rejects_wrong_caption_owner_time_old_code_and_draft(self):
  node=dict(code='TRIALabc123',owner=self.user,owner_id='123',caption=c.CAPTION,taken_at=time.time(),blocked=False);ident=dict(pk='123');self.assertTrue(ui.matches(node,self.job,ident,time.time(),time.time()))
  for changes in [dict(caption='wrong'),dict(owner='another',owner_id='456'),dict(taken_at=time.time()-3600),dict(blocked=True)]:self.assertFalse(ui.matches(dict(node,**changes),self.job,ident,time.time(),time.time()))
  self.assertFalse(ui.matches(node,self.job,ident,time.time(),time.time(),[node['code']]))

 def test_api_unavailable_uses_fixed_own_navigation_for_video_and_comment(self):
  self.api_available=False;self.upload();ui.comment(self.page,self.context,self.root,self.job,time.monotonic());self.assertTrue(engine.verified(self.root,self.job));self.assertEqual(self.shares,1);self.assertEqual(self.comment_sends,1)
 def test_api_unavailable_wrong_navigation_actor_never_shares(self):
  self.api_available=False;self.actual='other_account'
  with self.assertRaisesRegex(ui.SessionProblem,'账号不匹配'):self.upload()
  self.assertEqual(self.shares,0)
 def test_all_constant_page_evaluate_functions_compile_in_chromium(self):
  import ast
  from pathlib import Path
  tree=ast.parse(Path(ui.__file__).read_text());snippets=[n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'evaluate','evaluate_all'} and n.args and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str)]
  snippets.append(ui.OWN_PROFILE_NAV)
  for script in snippets:self.assertTrue(self.page.evaluate("(source)=>{ new Function('return ('+source+'\\n)'); return true; }",script.rstrip().rstrip(';')))

if __name__=='__main__':unittest.main()
