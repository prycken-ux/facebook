import contextlib
import html
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
import fb_upload as upload
import add_fb_accounts
import diagnose_personal_identity as identity
import safe_video_comments as comments
import send_fb06_comment_once as single


class DirectCommentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)

    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir()
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(patch.object(add_fb_accounts,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'VERSION','2.42'))
        self.stack.enter_context(patch.object(identity,'close_selected_window'))
        self.stack.enter_context(patch.object(upload,'ensure_identity',return_value={'method':'page_actor_id_match'}))
        self.stack.enter_context(patch.object(upload,'recheck_publish_identity'));self.stack.enter_context(patch.object(upload,'page_actor_matches',return_value=True))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        entry=dict(account='fb06',target='page01',type='page',name='Michelle Hamer',url=single.OWNER,enabled=False)
        upload.save_json(upload.CONFIG,{'targets':[entry]});self.config_before=upload.CONFIG.read_bytes()
        self.state_path=self.root/'logs/publish_state.json';self.state_path.write_text('{"some-upload": {"status": "published"}}');self.state_before=self.state_path.read_bytes()
        self.saved=[];self.calls=0;self.persist=True
        self.context=self.browser.new_context();self.context.expose_function('persistApprovedComment',self.save)
        self.context.route('https://www.facebook.com/**',self.route)
        self.context.new_page()

    def tearDown(self):
        try:self.context.close()
        except Exception:pass
        self.stack.close();self.temp.cleanup()

    def save(self,text):
        self.calls+=1
        if self.persist:self.saved.append(text)

    def route(self,route):
        if urlparse(route.request.url).path.startswith('/reel/'):
            existing=''.join('<div role="article" aria-label="Comment by Michelle Hamer"><a href="'+single.OWNER+'">Michelle Hamer</a><span>'+html.escape(text)+'</span></div>' for text in self.saved)
            body='''<html><main><a href="OWNER">Michelle Hamer</a>
<div id="compose"><div id="field" role="textbox" contenteditable="true" aria-label="Comment as Michelle Hamer"></div>
<button aria-label="Comment" onclick="submitComment()">Comment</button></div>EXISTING</main>
<script>async function submitComment(){const f=document.querySelector('#field'),text=f.innerText;
 await window.persistApprovedComment(text);
 const a=document.createElement('div');a.role='article';a.setAttribute('aria-label','Comment by Michelle Hamer');
 const author=document.createElement('a');author.href='OWNER';author.textContent='Michelle Hamer';a.append(author);
 const span=document.createElement('span');span.textContent=text;a.append(span);document.body.append(a);f.innerText='';}
</script></html>'''.replace('OWNER',single.OWNER).replace('EXISTING',existing)
        else:body='<html><h1>Michelle Hamer</h1></html>'
        route.fulfill(body=body,content_type='text/html')

    def run_one(self):
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=self.context):
            result=single.send_one(self.root,self.root,open_result=False,verify_timeout_ms=600)
        reports=list((self.root/'logs').glob('fb06-single-comment-*/result.json'))
        self.assertEqual(len(reports),1)
        report=json.loads(reports[0].read_text())
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before);self.assertEqual(self.state_path.read_bytes(),self.state_before)
        return result,report

    def test_one_exact_authorized_comment_is_sent_and_confirmed_after_fresh_navigation(self):
        result,report=self.run_one()
        self.assertEqual(result,0);self.assertEqual(self.calls,1);self.assertEqual(self.saved,[single.TEXT])
        self.assertEqual(report['verification'],'own_comment_seen_after_reload');self.assertEqual(report['status'],'sent')
        self.assertFalse(report['video_reuploaded']);self.assertEqual(report['permalink'],single.LINK)

    def test_existing_own_full_comment_is_not_sent_again(self):
        self.saved=[single.TEXT]
        result,report=self.run_one()
        self.assertEqual(result,0);self.assertEqual(self.calls,0);self.assertEqual(report['status'],'already_present')

    def test_optimistic_comment_without_persistence_is_unknown_and_not_sent_a_second_time(self):
        self.persist=False
        result,report=self.run_one()
        self.assertEqual(result,3);self.assertEqual(self.calls,1);self.assertEqual(self.saved,[])
        self.assertEqual(report['status'],'needs_review')
        ledger=upload.read_json(self.root/'logs/video_comments.json',{})
        self.assertEqual(next(iter(ledger.values()))['status'],'needs_review')

    def test_wrong_page_identity_never_fills_or_sends(self):
        with patch.object(upload,'page_actor_matches',return_value=False):result,report=self.run_one()
        self.assertEqual(result,3);self.assertEqual(self.calls,0);self.assertEqual(report['status'],'manual_required')
