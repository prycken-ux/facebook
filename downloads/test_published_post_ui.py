import html,json,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
import published_video_lookup as lookup
import safe_video_comments as comments

class PublishedPostUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context(timezone_id='Asia/Shanghai');self.page=self.context.new_page();self.text='Exact original caption with #LifeLessons'
        self.entry=dict(account='fb01',target='page01',name='Example Page',type='page',url='https://www.facebook.com/profile.php?id=1001')
        self.start=datetime(2026,11,2,7,10,tzinfo=timezone.utc).timestamp();self.end=self.start+300;self.body=''
        self.context.route('https://www.facebook.com/**',lambda r:r.fulfill(content_type='text/html',body=self.body))
    def tearDown(self):self.context.close()
    def card(self,vid='9001',owner='1001',caption=None,stamp='2026-11-02T07:12:00Z'):
        caption=self.text if caption is None else caption
        return '<article role="article"><h2><a href="https://www.facebook.com/profile.php?id='+owner+'">Example Page</a></h2><a href="/reel/'+vid+'"><time datetime="'+stamp+'">2h</time></a><div data-ad-preview="message">'+html.escape(caption)+'</div><a href="/reel/'+vid+'">Watch reel</a></article>'
    def find(self,timeout=1500):return lookup.find_published(self.page,self.context,self.entry,self.text,self.start,self.end,timeout_ms=timeout)
    def test_actual_loading_snapshot_shape_waits_for_posts_then_extracts_correct_video(self):
        self.body='<main><article role=article><div role=status>Loading...</div></article><article role=article><div role=status>Loading...</div></article></main><a href="/reel/111">Old global reel</a><script>setTimeout(()=>document.querySelector("main").innerHTML='+json.dumps(self.card())+',160)</script>'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'lookup.json';result=lookup.find_published(self.page,self.context,self.entry,self.text,self.start,self.end,timeout_ms=2000,diagnostic_path=path)
            self.assertEqual(result,('https://www.facebook.com/reel/9001','verified_owner_caption_time'))
            self.assertEqual(json.loads(path.read_text())['ui_candidates'],1)
    def test_wrong_owner_caption_time_and_nested_shared_video_never_supply_target(self):
        for body in [self.card(owner='999'),self.card(caption='Different caption'),self.card(stamp='2026-10-31T07:12:00Z')]:
            self.body=body
            with self.assertRaises(RuntimeError):self.find(timeout=800)
        self.body=self.card().replace('<a href="/reel/9001"><time','<a href="/posts/not-video"><time').replace('<a href="/reel/9001">Watch reel</a>','<article role=article><a href="/reel/777">Foreign nested video</a></article>')
        with self.assertRaises(RuntimeError):self.find(timeout=800)
    def test_duplicate_matching_posts_never_choose_first_or_newest(self):
        self.body=self.card()+self.card(vid='9002')
        with self.assertRaisesRegex(RuntimeError,'多个视频'):self.find()
    def test_expand_exact_post_caption_before_matching(self):
        self.body=self.card(caption='Exact original caption with ...').replace('Exact original caption with ...','Exact original caption with ...<button onclick="this.parentElement.textContent='+html.escape(json.dumps(self.text),quote=True)+'">See more</button>')
        self.assertEqual(self.find()[0],'https://www.facebook.com/reel/9001')
    def test_absolute_hover_time_uses_browser_timezone_and_never_uses_stale_global_tooltip(self):
        card=self.card().replace('<a href="/reel/9001"><time datetime="2026-11-02T07:12:00Z">2h</time></a>','<a href="/posts/123?__cft__=opaque" onmouseenter="document.querySelector(\'#tip\').textContent=\'Monday, November 2, 2026 at 3:12 PM\'">2h</a>')
        self.body=card+'<div id=tip role=tooltip></div>'
        self.assertEqual(self.find(timeout=1500)[0],'https://www.facebook.com/reel/9001')
        self.body=card.replace('onmouseenter="document.querySelector(\'#tip\').textContent=\'Monday, November 2, 2026 at 3:12 PM\'"','')+'<div id=tip role=tooltip>Monday, November 2, 2026 at 3:12 PM</div>'
        with self.assertRaises(RuntimeError):self.find(timeout=1000)
    def test_uninspected_matching_caption_never_allows_choosing_the_first_video(self):
        uncertain=self.card(vid='9002').replace('<time datetime="2026-11-02T07:12:00Z">2h</time>','2h')
        self.body=self.card()+uncertain
        with self.assertRaises(RuntimeError):self.find(timeout=1000)

    def test_graphql_story_proof_works_even_without_video_is_published_field(self):
        story=dict(__typename='Story',actors=[{'id':'1001'}],message={'text':self.text},creation_time=self.start+120,attachments=[{'media':{'__typename':'Video','id':'9022','owner':{'id':'1001'}}}])
        self.body='<script type="application/json">'+json.dumps({'data':story})+'</script>'
        self.assertEqual(self.find(timeout=800)[0],'https://www.facebook.com/reel/9022')
        collector=comments.PublicationLinks(self.context,self.entry,self.text,datetime.fromtimestamp(self.start,timezone.utc).isoformat());collector.armed=True
        response=type('Response',(),dict(url='https://www.facebook.com/api/graphql/',text=lambda self:json.dumps({'data':story})))()
        collector.receive(response);self.assertEqual(collector.links,{'https://www.facebook.com/reel/9022'})
    def test_loading_timeout_explains_the_missing_posts_and_saves_only_diagnostics(self):
        self.body='<article role=article><div role=status>Loading...</div></article>'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'diag.json'
            with self.assertRaisesRegex(RuntimeError,'Loading'):lookup.find_published(self.page,self.context,self.entry,self.text,self.start,self.end,timeout_ms=1000,diagnostic_path=path)
            data=json.loads(path.read_text());self.assertEqual(data['ui']['loading'],1);self.assertNotIn('cookies',data);self.assertNotIn('raw',data)
    def test_expanded_author_profile_accessible_name_is_accepted_only_for_exact_owner(self):
        self.body='<a href="/profile.php?id=1001" aria-label="Example Page, see owner profile">Example Page</a>';self.page.goto(self.entry['url'])
        comments.require_video_author(self.page,self.entry,timeout_ms=200)
        self.page.locator('a').evaluate("e=>e.href='/profile.php?id=999'")
        with self.assertRaises(RuntimeError):comments.require_video_author(self.page,self.entry,timeout_ms=150)
