import contextlib,html,io,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
import fb_upload as upload
import safe_video_comments as comments
import daily_publish_and_comments as daily


class ImmediatePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(upload,'recheck_publish_identity'));self.stack.enter_context(patch.object(upload,'page_actor_matches',return_value=True))
        self.stack.enter_context(patch('published_video_lookup.find_published',side_effect=AssertionError('fresh receipt must avoid reopening timeline')))
        self.entry=dict(account='fb01',target='page01',name='Example Page',type='page',url='https://www.facebook.com/profile.php?id=1001',enabled=True,_authorized_comment_text=daily.COMMENT,_immediate_verified_comment=True)
        self.video=upload.inbox_for(self.entry)/'new.mp4';self.video.parent.mkdir(parents=True);self.video.write_bytes(b'brand new video');self.video.with_suffix('.txt').write_text('Exact new caption')
        for file in [self.video,self.video.with_suffix('.txt')]:os.utime(file,(time.time()-180,time.time()-180))
        self.key=upload.job_key(self.entry,self.video);self.state={};self.path=self.root/'logs/publish_state.json';upload.save_json(self.path,self.state)
        self.saved=[];self.posts=0;self.sends=0;self.persist=True;self.visited=[]
        self.context=self.browser.new_context();self.page=self.context.new_page();self.context.expose_function('recordVideoPost',self.video_post);self.context.expose_function('persistComment',self.comment_post);self.context.route('https://www.facebook.com/**',self.route)
    def tearDown(self):
        try:self.context.close()
        except Exception:pass
        self.stack.close();self.temp.cleanup()
    def video_post(self):
        row=upload.read_json(self.path,{})[self.key];self.assertEqual(row['status'],'posting');self.assertTrue(row['post_intent_at']);self.posts+=1
    def comment_post(self,text):
        row=upload.read_json(self.path,{})[self.key];self.assertEqual(row['status'],'published');self.assertEqual(row['permalink'],'https://www.facebook.com/reel/9001')
        ledger=upload.read_json(self.root/'logs/video_comments.json',{});self.assertTrue(any(r['status']=='sending' for r in ledger.values()));self.sends+=1
        if self.persist:self.saved.append(text)
    def route(self,r):
        self.visited.append(r.request.url)
        if urlparse(r.request.url).path.startswith('/reel/'):
            existing=''.join('<div role=article aria-label="Comment by Example Page"><a href="'+self.entry['url']+'">Example Page</a><span>'+html.escape(t)+'</span></div>' for t in self.saved)
            body='''<main><a href="OWNER" aria-label="Example Page, see owner profile">Example Page</a>EXISTING<div><div id=field role=textbox contenteditable=true aria-label="Comment as Example Page"></div><button aria-label="Post comment" onclick="send()">Post comment</button></div></main><script>async function send(){let f=document.querySelector('#field'),t=f.innerText;await window.persistComment(t);let a=document.createElement('div');a.role='article';a.setAttribute('aria-label','Comment by Example Page');a.innerHTML='<a href="OWNER">Example Page</a>';let s=document.createElement('span');s.textContent=t;a.append(s);document.querySelector('main').append(a);f.innerText=''}</script>'''.replace('OWNER',self.entry['url']).replace('EXISTING',existing)
        else:
            body='''<main><form id=editor><button id=publish type=button onclick="publishVideo()">Post</button></form></main><script>async function publishVideo(){await window.recordVideoPost();document.querySelector('#editor').remove();let s=document.createElement('section');s.innerHTML='<h2>Your reel is published.</h2><a href="/reel/9001">View reel</a>';document.querySelector('main').append(s)}</script>'''
        r.fulfill(content_type='text/html',body=body)
    def run_video(self,unknown=False):
        def prepare(page,*args,**kwargs):page.goto(self.entry['url']);return page.locator('#publish'),{}
        original=comments.verify_after_reload
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=self.context),patch.object(upload,'prepare_reel',side_effect=prepare),patch.object(comments,'verify_after_reload',side_effect=lambda *a,**k:original(*a,**dict(k,timeout_ms=250))):
            if unknown:
                with patch.object(upload,'wait_for_receipt',side_effect=upload.ReceiptNeedsReview('unknown')):
                    return upload.run_entry(self.entry,self.state,self.path,True,filename=self.video.name,expected_job_key=self.key,defer_comments=False)
            return upload.run_entry(self.entry,self.state,self.path,True,filename=self.video.name,expected_job_key=self.key,defer_comments=False)
    def test_real_receipt_send_and_reload_finish_before_browser_closes_without_profile_lookup(self):
        self.run_video();row=upload.read_json(self.path,{})[self.key]
        self.assertEqual(row['status'],'published');self.assertEqual(row['comment_status'],'sent');self.assertEqual(self.posts,1);self.assertEqual(self.sends,1);self.assertEqual(self.saved,[daily.COMMENT]);self.assertTrue(Path(row['archived_video']).is_file())
        self.assertEqual(sum(urlparse(u).path=='/profile.php' for u in self.visited),1)
        item=next(iter(upload.read_json(self.root/'logs/video_comments.json',{}).values()));self.assertEqual(item['verification'],'own_comment_seen_after_reload')
        with patch.object(upload,'launch_context',side_effect=AssertionError('published job must not reopen')):
            self.assertFalse(upload.run_entry(self.entry,upload.read_json(self.path,{}),self.path,True,filename=self.video.name,expected_job_key=self.key))
    def test_comment_not_retained_after_refresh_keeps_video_success_and_never_resends(self):
        self.persist=False;self.run_video();row=upload.read_json(self.path,{})[self.key]
        self.assertEqual(row['status'],'published');self.assertEqual(row['comment_status'],'needs_review');self.assertEqual(self.sends,1);self.assertTrue(Path(row['archived_video']).is_file())
        with patch.object(upload,'launch_context',side_effect=AssertionError('must not reupload')):
            self.assertFalse(upload.run_entry(self.entry,upload.read_json(self.path,{}),self.path,True,filename=self.video.name,expected_job_key=self.key))
        self.assertEqual(self.sends,1)
    def test_unknown_video_outcome_never_sends_comment(self):
        with self.assertRaises(upload.ReceiptNeedsReview):self.run_video(unknown=True)
        self.assertEqual(upload.read_json(self.path,{})[self.key]['status'],'needs_review');self.assertEqual(self.sends,0)
    def test_comment_error_keeps_the_successful_video_archived(self):
        with patch.object(comments,'immediate_verified_comment',side_effect=RuntimeError('comment panel unavailable')):self.run_video()
        row=upload.read_json(self.path,{})[self.key];self.assertEqual(row['status'],'published');self.assertEqual(row['comment_status'],'manual_required');self.assertTrue(Path(row['archived_video']).is_file());self.assertEqual(self.posts,1);self.assertEqual(self.sends,0)
