"""Browser regression modeled on the user's recovered 13-action IG demonstration."""
import json,time,unittest
from unittest.mock import patch
from urllib.parse import urlparse
from test_ig10_browser_20261127 import BrowserFixture
import ig10_common_20261127 as c
import ig10_browser_20261127 as ui
import ig10_engine_20261127 as engine

class RecordedFlowTests(BrowserFixture):
 def setUp(self):
  self.ai_initial=True;self.ambiguous_ai=False;self.portal=False;self.delayed=False;self.payloads=[];super().setUp()
 def route(self,r):
  path=urlparse(r.request.url).path
  if path.startswith('/api/') or path in {'/fixture-comment','/reel/TRIALabc123/'}:
   if path.startswith('/api/v1/media/configure'):self.payloads.append(r.request.post_data_json)
   return super().route(r)
  body='''<a aria-label="Profile" href="/ACTOR/">Profile</a><button onclick="window.backgroundNext=(window.backgroundNext||0)+1">下一步</button>
  <a href="#" role="link" onclick="document.getElementById('composer').style.display='block'">创建<svg aria-label="新帖子" width="24" height="24"></svg></a><input id="avatar" type="file" accept="image/*">
  <script>window.continues=0;window.original=false;window.backgroundNext=0;
  function show(n){document.querySelectorAll('[data-stage]').forEach(x=>x.style.display=x.dataset.stage==n?'block':'none');document.getElementById('phase').textContent=['创建新帖子','裁剪','编辑','新 Reels'][n];document.getElementById('continue').style.display=(n==1||n==2)?'block':'none';document.getElementById('share').style.display=n==3?'block':'none';if(n==3&&DELAY){document.getElementById('caption').style.display='none';setTimeout(()=>document.getElementById('caption').style.display='block',1000);}}
  function next(){window.continues++;const n=document.getElementById('phase').textContent==='裁剪'?2:3;if(DELAY)setTimeout(()=>show(n),400);else show(n);}
  </script>
  <div DIALOG id="composer" style="display:none"><header><div id="phase">创建新帖子</div><div role="button" id="continue" style="display:none" onclick="next()">继续</div><div role="button" id="share" style="display:none" onclick="fetch('/api/v1/media/configure_to_clips/',{method:'POST',body:JSON.stringify({ai:String(document.getElementById('ai').checked),caption:document.getElementById('caption').innerText,audio:document.getElementById('audio').checked,comments_disabled:document.getElementById('off').checked,original:window.original,continues:window.continues,backgroundNext:window.backgroundNext})})">分享</div></header><video></video>
  <section data-stage="0"><p>把照片和视频拖放到这里</p><button>从电脑中选择</button><input id="video" type="file" accept="video/*" onchange="show(1)"></section>
  <section data-stage="1" style="display:none"><button aria-label="选择“裁剪”" onclick="document.getElementById('cropmenu').style.display='block'"><svg aria-label="选择“裁剪”"></svg></button></section>
  <section data-stage="2" style="display:none"><p>打开声音</p><input id="audio" type="checkbox" role="switch" aria-checked="true" checked></section>
  <section data-stage="3" style="display:none"><div id="caption" contenteditable="true" role="textbox" aria-label="添加配文...">演示文字必须被正式文案替换</div><div><span>添加 AI 标签</span><input id="ai" type="checkbox" role="switch" AI></div>
  <div role="button" aria-expanded="false" onclick="document.getElementById('settings').style.display='block';this.setAttribute('aria-expanded','true')">高级设置</div><div id="settings" style="display:none"><div><span>关闭评论</span><input id="off" type="checkbox" role="switch" checked></div></div></section></div>
  <div id="cropmenu" style="display:none"><button onclick="window.original=true;document.getElementById('cropmenu').style.display='none'">原图</button></div>'''
  body=body.replace('ACTOR',self.actual).replace('DIALOG','' if self.portal else 'role="dialog"').replace('DELAY','true' if self.delayed else 'false').replace('AI>','checked>' if self.ai_initial else '>')
  if self.ambiguous_ai:body=body.replace('<input id="ai" type="checkbox" role="switch" checked>','<input id="ai" type="checkbox" role="switch" checked><input type="checkbox" role="switch" checked>')
  r.fulfill(content_type='text/html; charset=utf-8',body='<html><body>'+body+'</body></html>')
 def assert_recorded_flow(self):
  self.upload();self.assertEqual(len(self.payloads),1);p=self.payloads[0];self.assertEqual(p['caption'],c.CAPTION);self.assertEqual(p['ai'],'false');self.assertTrue(p['audio']);self.assertFalse(p['comments_disabled']);self.assertTrue(p['original']);self.assertEqual(p['continues'],2);self.assertEqual(p['backgroundNext'],0)
  row=c.state(self.root)[self.job['key']];self.assertEqual(row['ai_control_evidence'],'visible_control_verified_off');self.assertEqual(row['comment_control_evidence'],'visible_control_verified_enabled');self.assertEqual(row['edit_advances'],2);ui.comment(self.page,self.context,self.root,self.job,time.monotonic());self.assertTrue(engine.verified(self.root,self.job));self.assertEqual(self.comment_sends,1)
 def test_recorded_continue_caption_unnamed_ai_comments_and_unchanged_audio(self):self.assert_recorded_flow()
 def test_recorded_ai_already_off_stays_off(self):self.ai_initial=False;self.assert_recorded_flow()
 def test_delayed_step_change_and_caption_never_click_continue_twice(self):self.delayed=True;self.assert_recorded_flow()
 def test_portal_scope_never_clicks_background_carousel_next_or_share(self):self.portal=True;self.assert_recorded_flow()
 def test_ambiguous_unnamed_ai_switch_blocks_share_before_submission(self):
  self.ambiguous_ai=True
  with self.assertRaisesRegex(RuntimeError,'无法唯一核对'):self.upload()
  self.assertEqual(len(self.payloads),0);self.assertFalse(c.submission(c.state(self.root)[self.job['key']]))

 def test_ai_inside_advanced_settings_is_verified_after_expanding(self):
  original=self.route
  def modified(route):
   class Wrapped:
    request=route.request
    def abort(self,*a,**k):return route.abort(*a,**k)
    def fulfill(self,*a,**k):
     if 'body' in k:
      k['body']=k['body'].replace('<div><span>添加 AI 标签</span>','<div id="airow" style="display:none"><span>添加 AI 标签</span>').replace("document.getElementById('settings').style.display='block';", "document.getElementById('settings').style.display='block';document.getElementById('airow').style.display='block';")
     return route.fulfill(*a,**k)
   return original(Wrapped())
  self.context.unroute('**/*');self.context.route('**/*',modified);self.assert_recorded_flow()
 def test_open_advanced_settings_is_not_collapsed_before_comment_verification(self):
  original=self.route
  def modified(route):
   class Wrapped:
    request=route.request
    def abort(self,*a,**k):return route.abort(*a,**k)
    def fulfill(self,*a,**k):
     if 'body' in k:k['body']=k['body'].replace('aria-expanded="false"','aria-expanded="true"').replace('id="settings" style="display:none"','id="settings"')
     return route.fulfill(*a,**k)
   return original(Wrapped())
  self.context.unroute('**/*');self.context.route('**/*',modified);self.assert_recorded_flow()

from test_ig10_workflow_20261127 import Fixture
class RecordedEditorGateTests(Fixture):
 def prepare(self):
  path,batch=self.plan();j=batch['payload']['jobs'][0];error='网页按钮尚未找到：^(Next|下一步)$';folder=self.root/'logs/diagnostics/next-failure';evidence=dict(account=j['account'],username=j['username'],key=j['key'],kind='video',error=error,page_url=ui.BASE+'/',visible_text=j['username']+'\n裁剪\n继续')
  c.save(folder/'diagnostic.json',evidence);c.update(self.root,j['key'],account=j['account'],username=j['username'],video_sha256=j['video_sha256'],batch_sha256=batch['sha256'],selected_file=j['video'],selected_video_sha256=j['video_sha256'],video_status='failed_before_post',error=error,identity=dict(username=j['username']),identity_verified_at=c.stamp(),diagnostic=str(folder.relative_to(self.root)))
  gate=dict(blocked=True,passed=False,batch_sha256=batch['sha256'],job_key=j['key'],navigation_syntax_repair='old-nav',create_entry_repair='old-create');return batch,j,gate
 def test_exact_continue_mismatch_recovery_preserves_ledger_and_previous_repair(self):
  batch,j,gate=self.prepare();before=(self.root/'logs/ig-publication-state.json').read_bytes();fixed=engine.recover_recorded_editor_gate(self.root,batch,gate);self.assertFalse(fixed['blocked']);self.assertFalse(fixed['passed']);self.assertEqual(fixed['create_entry_repair'],'old-create');self.assertTrue(fixed['recorded_editor_repair']);self.assertEqual((self.root/'logs/ig-publication-state.json').read_bytes(),before);blocked=dict(fixed,blocked=True);self.assertEqual(engine.recover_recorded_editor_gate(self.root,batch,blocked),blocked)
 def test_submission_or_comment_evidence_cannot_release_recorded_gate(self):
  batch,j,gate=self.prepare()
  for field in ['post_intent_at','submit_click_returned_at','comment_send_intent_at']:
   before=c.state(self.root);c.update(self.root,j['key'],**{field:c.stamp()});self.assertEqual(engine.recover_recorded_editor_gate(self.root,batch,gate),gate);c.save(self.root/'logs/ig-publication-state.json',before)
 def test_export_uses_actual_redirected_desktop(self):
  path,batch=self.plan();desktop=self.base/'ActualDesktop';desktop.mkdir()
  with patch.object(c,'desktop_hint',return_value=desktop):archive=engine.export(self.root,batch)
  self.assertEqual(archive.parent,desktop);self.assertTrue(archive.exists())

if __name__=='__main__':unittest.main()
