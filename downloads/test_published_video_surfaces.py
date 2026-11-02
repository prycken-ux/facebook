import contextlib,io,json,unittest
from datetime import datetime,timezone
from unittest.mock import patch
from urllib.parse import parse_qs,urlparse
from playwright.sync_api import sync_playwright
import published_video_lookup as lookup
import published_video_surfaces as tabs


class VideoSurfaceProofTests(unittest.TestCase):
    def test_grid_video_must_carry_all_its_own_proof(self):
        node=dict(__typename='Video',id='9001',owner={'id':'1001'},description='Exact caption',creation_time=1000,is_published=True)
        self.assertEqual(tabs.standalone_videos(node,'1001','Exact caption',900,1100),{'https://www.facebook.com/reel/9001'})
        for change in [dict(owner={'id':'999'}),dict(description='other'),dict(creation_time=500),dict(is_published=False),dict(is_published=None),dict(is_pending=True),dict(is_draft=True),dict(permalink_url='https://www.facebook.com/reel/9999')]:
            self.assertFalse(tabs.standalone_videos(dict(node,**change),'1001','Exact caption',900,1100))
        nested=dict(message={'text':'Exact caption'},media={k:v for k,v in node.items() if k!='description'})
        self.assertFalse(tabs.standalone_videos(nested,'1001','Exact caption',900,1100))


class VideoSurfaceBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context();self.page=self.context.new_page()
        self.entry=dict(account='fb10',target='page07',type='page',name='Example Page',url='https://www.facebook.com/profile.php?id=1001')
        self.start=datetime(2026,11,2,9,10,tzinfo=timezone.utc).timestamp();self.end=self.start+300
        self.video=dict(__typename='Video',id='9001',owner={'id':'1001'},description='Exact caption',creation_time=self.start+60,is_published=True)
        self.multiple=False;self.visited=[]
        def route(r):
            self.visited.append(r.request.url);tab=parse_qs(urlparse(r.request.url).query).get('sk',[''])[0]
            body='<article role=article><div role=status>Loading...</div></article>'
            if tab=='reels':body='<script type="application/json">'+json.dumps(self.video)+'</script>'
            if tab=='videos' and self.multiple:body='<script type="application/json">'+json.dumps(dict(self.video,id='9002'))+'</script>'
            r.fulfill(content_type='text/html',body=body)
        self.context.route('https://www.facebook.com/**',route)
    def tearDown(self):self.context.close()
    def find(self,known=()):
        with contextlib.redirect_stdout(io.StringIO()):
            return tabs.find_on_tabs(self.page,self.context,self.entry,'Exact caption',self.start,self.end,surface_seconds=1,known_links=known)
    def test_reels_tab_provides_exact_proof_without_using_a_newest_video_guess(self):
        link,notes=self.find();self.assertEqual(link,'https://www.facebook.com/reel/9001');self.assertEqual(len(notes),2)
        self.assertTrue(all(parse_qs(urlparse(u).query)['id']==['1001'] for u in self.visited))
    def test_conflicting_candidates_from_different_tabs_or_prior_profile_stop_lookup(self):
        self.multiple=True
        with self.assertRaises(ValueError):self.find()
        self.multiple=False
        with self.assertRaises(ValueError):self.find(known={'https://www.facebook.com/reel/9999'})
    def test_production_profile_loading_timeout_reaches_tabs_and_keeps_exact_binding(self):
        original=tabs.find_on_tabs
        with patch.object(tabs,'find_on_tabs',side_effect=lambda *a,**k:original(*a,**dict(k,surface_seconds=1))),contextlib.redirect_stdout(io.StringIO()):
            link,method=lookup.find_published(self.page,self.context,self.entry,'Exact caption',self.start,self.end,timeout_ms=15000)
        self.assertEqual(link,'https://www.facebook.com/reel/9001');self.assertEqual(method,'verified_owner_caption_time_reels_tabs')
