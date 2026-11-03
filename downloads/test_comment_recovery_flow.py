import contextlib,html,io,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
import add_fb_accounts
import fb_upload as upload
import daily_publish_and_comments as daily
import safe_video_comments as comments
import repair_oct31_published_comments as repair

class CommentRecoveryFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack()
        for module,attr,value in [(upload,'ROOT',self.root),(upload,'CONFIG',self.root/'upload_config.json'),(add_fb_accounts,'ROOT',self.root)]:self.stack.enter_context(patch.object(module,attr,value))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()));self.stack.enter_context(patch.object(daily,'close_selected_window'));self.stack.enter_context(patch.object(upload,'ensure_identity',return_value={}));self.stack.enter_context(patch.object(upload,'recheck_publish_identity'));self.stack.enter_context(patch.object(upload,'page_actor_matches',return_value=True))
        self.stack.enter_context(patch.object(upload,'run_entry',side_effect=AssertionError('no video upload permitted')))
        self.entry=dict(account='fb01',target='page01',type='page',name='Example Page',url='https://www.facebook.com/profile.php?id=1001')
        self.job=dict(account='fb01',target='page01',filename='already-published.mp4',key='a'*64,url=self.entry['url'],caption_text='Exact original caption #LifeLessons')
        self.state={'a'*64:dict(account='fb01',target='page01',url=self.entry['url'],video='E:\\FB-AutoUpload\\completed\\already-published.mp4',created='2026-11-02T07:10:00+00:00',published_at='2026-11-02T07:13:00+00:00',status='published',comment_status='manual_required')}
        self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state);upload.save_json(upload.CONFIG,{'targets':[self.entry]});self.config_before=upload.CONFIG.read_bytes()
        self.manifest=dict(payload=dict(date='2026-10-31',jobs=[self.job]),sha256='b'*64)
        self.saved=[];self.sends=0;self.persist=True
        self.context=self.browser.new_context(timezone_id='Asia/Shanghai');self.context.expose_function('persistComment',self.save);self.context.route('https://www.facebook.com/**',self.route);self.context.new_page()
    def tearDown(self):
        try:self.context.close()
        except Exception:pass
        self.stack.close();self.temp.cleanup()
    def save(self,text):
        self.sends+=1
        if self.persist:self.saved.append(text)
    def route(self,r):
        if urlparse(r.request.url).path.startswith('/reel/'):
            existing=''.join('<div role=article aria-label="Comment by Example Page"><a href="'+self.entry['url']+'">Example Page</a><span>'+html.escape(text)+'</span></div>' for text in self.saved)
            body='''<main><a href="OWNER" aria-label="Example Page, see owner profile">Example Page</a>EXISTING<div><div id=field role=textbox contenteditable=true aria-label="Comment as Example Page"></div><button aria-label="Post comment" onclick="send()">Post comment</button></div></main><script>async function send(){let f=document.querySelector('#field'),t=f.innerText;await window.persistComment(t);let a=document.createElement('div');a.role='article';a.setAttribute('aria-label','Comment by Example Page');a.innerHTML='<a href="OWNER">Example Page</a>';let s=document.createElement('span');s.textContent=t;a.append(s);document.querySelector('main').append(a);f.innerText=''}</script>'''.replace('OWNER',self.entry['url']).replace('EXISTING',existing)
        else:
            card='<article role=article><h2><a href="'+self.entry['url']+'">Example Page</a></h2><a href="/reel/9001"><time datetime="2026-11-02T07:12:00Z">2h</time></a><div data-ad-preview="message">'+self.job['caption_text']+'</div><a href="/reel/9001">Watch reel</a></article>'
            body='<main><article role=article><div role=status>Loading...</div></article></main><script>setTimeout(()=>document.querySelector("main").innerHTML='+json.dumps(card)+',120)</script>'
        r.fulfill(content_type='text/html',body=body)
    def run_comments(self):
        original=comments.verify_after_reload
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=self.context),patch.object(comments,'verify_after_reload',side_effect=lambda *a,**k:original(*a,**dict(k,timeout_ms=250))):
            return daily.backfill(self.manifest,None,future_only=True,reporter=lambda *a:None)
    def test_no_saved_link_loading_posts_real_lookup_send_and_refresh_are_one_pipeline(self):
        rows=self.run_comments();self.assertEqual(rows[0]['status'],'sent');self.assertEqual(self.saved,[daily.COMMENT]);self.assertEqual(self.sends,1)
        state=upload.read_json(self.state_path,{})['a'*64];self.assertEqual(state['status'],'published');self.assertEqual(state['permalink'],'https://www.facebook.com/reel/9001');self.assertEqual(state['comment_link_job_key'],'a'*64)
        receipt=next(iter(upload.read_json(self.root/'logs/video_comments.json',{}).values()));self.assertEqual(receipt['verification'],'own_comment_seen_after_reload');self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        with patch.object(upload,'launch_context',side_effect=AssertionError('must not reopen browser')):
            self.assertEqual(daily.backfill(self.manifest,None,future_only=True,reporter=lambda *a:None)[0]['status'],'sent')
    def test_optimistic_only_comment_is_not_confirmed_and_never_sent_twice(self):
        self.persist=False;rows=self.run_comments();self.assertEqual(rows[0]['status'],'needs_review');self.assertEqual(self.sends,1)
        with patch.object(upload,'launch_context',side_effect=AssertionError('must not resend')):
            self.assertEqual(daily.backfill(self.manifest,None,future_only=True,reporter=lambda *a:None)[0]['status'],'needs_review')
        self.assertEqual(self.sends,1)
    def test_repair_gate_stops_batch_after_an_unknown_first_comment_without_uploading(self):
        def pretend(value,*a,**k):k['rows'].append(dict(self.job,status='needs_review',error='unknown'))
        with patch.object(repair,'source_manifest',return_value=self.manifest),patch.object(repair.daily,'backfill',side_effect=pretend) as send,patch.object(repair,'datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,11,2,7,0,tzinfo=timezone.utc)
            self.assertEqual(repair.execute(),3)
        self.assertEqual(send.call_count,1);self.assertEqual(upload.read_json(self.state_path,{})['a'*64]['status'],'published')
        self.assertFalse(list(self.root.rglob('*.csv')))
    def test_retry_audit_distinguishes_installation_only_from_bound_real_post_receipt(self):
        self.assertIn('没有实际自动补发记录',repair.retry_audit()['message'])
        claim=dict(account='fb01',target='page01',source_manifest='source.json',source_sha256='c'*64,reserved_at='2026-11-02T07:00:00+00:00')
        upload.save_json(self.root/'logs/automatic_before_post_retry_claims.json',dict(schema='automatic-before-post-retry-claims-v1',jobs={'a'*64:claim}))
        state=self.state['a'*64];state.update(automatic_retry=dict(source_manifest='source.json',source_sha256='c'*64,retry_number=1),post_intent_at='2026-11-02T07:12:00+00:00',confirmation_method='fresh_success_ui_and_composer_closed');upload.save_json(self.state_path,self.state)
        self.assertEqual(repair.retry_audit()['rows'][0]['category'],'自动补发后已取得成功回执')
        state['confirmation_method']='user_verified_manual_post';upload.save_json(self.state_path,self.state)
        self.assertNotEqual(repair.retry_audit()['rows'][0]['category'],'自动补发后已取得成功回执')
