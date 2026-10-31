import contextlib
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from playwright.sync_api import sync_playwright
import fb_upload as upload
import safe_video_comments as comments
import publish_new_with_comments as future

class FutureCommentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context();self.page=self.context.new_page()
        self.entry=dict(name='Example Page',url='https://www.facebook.com/profile.php?id=1001',type='page',account='fb01',target='page01')
        self.text='Get your own copy:\nhttps://www.amazon.com/s?tag=maas&me=SHOP'
    def tearDown(self):self.context.close()
    def render(self,label='Comment by Example Page',href='/profile.php?id=1001',url='https://www.amazon.com/s?tag=maas&me=SHOP',extra=''):
        self.page.set_content('<div role="article" aria-label="'+label+'"><a href="https://www.facebook.com'+href+'">Example Page</a><span>Get your own copy:</span><a href="'+url.replace('&','&amp;')+'">https://www.amazon.com/s...</a>'+extra+'</div>')
    def test_redirect_reordered_query_and_fbclid_are_equivalent(self):
        self.render(url='https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.amazon.com%2Fs%3Fme%3DSHOP%26tag%3Dmaas%26fbclid%3Dextra')
        self.assertTrue(comments.scan_comments(self.page,self.entry,self.text))
    def test_observed_facebook_attribution_does_not_hide_successful_own_comment(self):
        from urllib.parse import quote
        self.text='Get your own copy:\nhttps://www.amazon.com/s?maas=campaign&ref_=aa_maas&tag=maas&me=SHOP&marketplaceID=ATVPDKIKX0DER'
        actual=self.text.split('\n')[1]+'&content_source=fb&fb_content_id=synthetic_content&channel_type=fb&fbclid=synthetic_click'
        self.render(href='/profile.php?id=1001&comment_id=synthetic&__tn__=R',url='https://l.facebook.com/l.php?u='+quote(actual,safe='')+'&h=synthetic&__tn__=R')
        self.assertTrue(comments.scan_comments(self.page,self.entry,self.text))
        for before,after in [('me=SHOP','me=OTHER'),('tag=maas','tag=OTHER'),('marketplaceID=ATVPDKIKX0DER','marketplaceID=OTHER'),('maas=campaign','maas=OTHER'),('ref_=aa_maas','ref_=OTHER')]:
            self.render(url='https://l.facebook.com/l.php?u='+quote(actual.replace(before,after),safe=''))
            self.assertFalse(comments.scan_comments(self.page,self.entry,self.text))
        for tail in ['&unexpected=changed','&content_source=external','&channel_type=external']:
            self.render(url='https://l.facebook.com/l.php?u='+quote(actual+tail,safe=''))
            self.assertFalse(comments.scan_comments(self.page,self.entry,self.text))
    def test_different_author_product_or_missing_affiliate_parameter_is_not_proof(self):
        for change in [dict(href='/profile.php?id=999'),dict(url='https://www.amazon.com/dp/123?tag=maas&me=SHOP'),dict(url='https://www.amazon.com/s?me=SHOP')]:
            self.render(**change);self.assertFalse(comments.scan_comments(self.page,self.entry,self.text))
    def test_unlabelled_comment_needs_comment_permalink_and_reply(self):
        self.render(label='');self.assertFalse(comments.scan_comments(self.page,self.entry,self.text))
        self.render(label='',extra='<a href="?comment_id=321">1m</a><button>Reply</button>')
        self.assertTrue(comments.scan_comments(self.page,self.entry,self.text))
    def test_nested_other_author_and_draft_are_not_comment_proof(self):
        self.page.set_content('<div role=article aria-label="Comment by Example Page"><a href="'+self.entry['url']+'">Example Page</a><div role=article aria-label="Comment by Other">'+self.text+'</div><div role=textbox contenteditable=true>'+self.text+'</div></div>')
        self.assertFalse(comments.scan_comments(self.page,self.entry,self.text))
    def test_fresh_heading_button_can_save_exact_link_but_old_global_button_cannot(self):
        self.context.route('https://www.facebook.com/**',lambda r:r.fulfill(content_type='text/html',body='<main><button onclick="window.bad=true">View reel</button></main>'))
        self.page.goto(self.entry['url']);upload.install_receipt_watch(self.page)
        self.page.evaluate('window.__fbUploadWatch.armed=true')
        self.page.evaluate("""()=>{const s=document.createElement('section');s.innerHTML='<h2>Your reel is published.</h2><button>View reel</button>';s.querySelector('button').onclick=()=>location.href='/reel/9991';document.body.append(s)}""")
        link,_=comments.resolve_published_link(self.page,self.context,None,timeout_ms=1000)
        self.assertEqual(link,'https://www.facebook.com/reel/9991');self.assertIsNone(self.page.evaluate('window.bad'))
    def test_reload_confirms_only_persisted_comments_and_never_resends(self):
        import html
        for persisted in [True,False]:
            with self.subTest(persisted=persisted),tempfile.TemporaryDirectory() as tmp:
                self.page.close();self.page=self.context.new_page();saved=[]
                def route(r):
                    existing=''.join('<div role="article" aria-label="Comment by Example Page"><a href="'+self.entry['url']+'">Example Page</a><span>'+html.escape(t)+'</span></div>' for t in saved)
                    r.fulfill(content_type='text/html',body='<main>'+existing+'<div role="textbox" contenteditable="true" aria-label="Comment as Example Page"></div></main>')
                self.context.route('https://www.facebook.com/**',route)
                self.page.goto('https://www.facebook.com/reel/9991')
                if persisted:saved.append(self.text)
                key='a'*64;item=dict(status='verifying',permalink=self.page.url)
                ledger_key=comments.hashlib.sha256((key+'\0'+comments.text_hash(self.text)).encode()).hexdigest()
                with patch.object(upload,'ROOT',Path(tmp)),patch.object(upload,'recheck_publish_identity'),patch.object(upload,'page_actor_matches',return_value=True):
                    upload.save_json(Path(tmp)/'logs/video_comments.json',{ledger_key:item})
                    result=comments.verify_after_reload(self.page,self.entry,{},key,self.text,item,timeout_ms=100)
                    self.assertEqual(result['status'],'sent' if persisted else 'needs_review',result)
                self.context.unroute('https://www.facebook.com/**',route)
    def test_future_runner_finishes_all_uploads_before_comments_without_old_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'logs/frozen.json';now=datetime(2026,11,1,4,tzinfo=timezone.utc)
            value={'payload':{'start':now.isoformat(),'jobs':[]}};events=[]
            with patch.object(upload,'ROOT',root),patch.object(future,'datetime',wraps=datetime) as clock,patch.object(future,'locked',return_value=contextlib.nullcontext()),patch.object(future.batch,'freeze',return_value=(path,value)),patch.object(future.batch,'run',side_effect=lambda *a,**k:events.append('uploads')),patch.object(future.daily,'backfill',side_effect=lambda *a,**k:events.append('comments')) as send,patch.object(future.batch,'results',return_value=[]):
                clock.now.return_value=now
                self.assertEqual(future.execute('2026-11-01',True),0)
            self.assertEqual(events,['uploads','comments']);self.assertTrue(send.call_args.kwargs['future_only'])
    def test_future_runner_refuses_old_date_or_unconfirmed_footage(self):
        with self.assertRaises(ValueError):future.execute('1900-01-01',True)
        with self.assertRaises(ValueError):future.execute('2026-11-01',False)
