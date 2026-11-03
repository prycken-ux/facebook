import contextlib,io,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
import add_fb_accounts
import fb_upload as upload
import safe_video_comments as comments
import probe_fb10_page02_actual_reels as probe


HTML='''<nav><a href="/reel/?s=tab" onclick="window.badClick=true">Reels</a></nav><main>
<div role=tablist><button role=tab aria-selected=true>Posts</button><button id=reels role=tab aria-selected=false onclick="openReels()">Reels</button></div>
<section id=content><article role=article><div role=status>Loading...</div></article></section></main>
<script>function openReels(){document.querySelector('#reels').setAttribute('aria-selected','true');history.pushState({},'', '/profile.php?id=61595204068114&sk=reels_tab&fbclid=synthetic');document.querySelector('#content').innerHTML='<a href="/reel/1500593451890233?fbclid=synthetic">Known video</a><a href="https://evil.example/reel/123">external</a>'}</script>'''


class ActualReelsProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context();self.page=self.context.new_page();self.context.route('https://www.facebook.com/**',lambda r:r.fulfill(content_type='text/html',body=HTML));self.page.goto(probe.OWNER)
    def tearDown(self):
        try:self.context.close()
        except Exception:pass
    def test_clicks_actual_page_tab_not_guessed_url_or_global_reels_and_reads_known_link(self):
        result=probe.probe_page(self.page,seconds=.6)
        self.assertTrue(result['selected']);self.assertTrue(result['known_video_found']);self.assertEqual(result['links'],[probe.KNOWN]);self.assertIn('sk=reels_tab',result['actual_url']);self.assertNotIn('fbclid',result['actual_url']);self.assertIsNone(self.page.evaluate('window.badClick'))
    def test_multiple_page_tabs_are_not_guessed(self):
        self.page.evaluate("document.querySelector('[role=tablist]').insertAdjacentHTML('beforeend','<button role=tab>Reels</button>')")
        with self.assertRaises(ValueError):probe.probe_page(self.page,seconds=.2)
        self.assertIsNone(self.page.evaluate('window.badClick'))
    def test_full_read_only_probe_leaves_all_business_journals_and_config_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
            root=Path(tmp);(root/'logs').mkdir();config=root/'upload_config.json'
            upload.save_json(config,dict(targets=[dict(account='fb10',target='page02',type='page',name=probe.NAME,url=probe.OWNER)]))
            upload.save_json(root/'logs/publish_state.json',{'existing':dict(account='fb10',target='page02',status='published',comment_status='sent')})
            upload.save_json(root/'logs/video_comments.json',{'existing':dict(status='sent')});upload.save_json(root/'logs/automatic_before_post_retry_claims.json',{'existing':'unchanged'})
            snapshots={p:p.read_bytes() for p in root.rglob('*.json')}
            for module,name,value in [(upload,'ROOT',root),(upload,'CONFIG',config),(add_fb_accounts,'ROOT',root)]:stack.enter_context(patch.object(module,name,value))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()));stack.enter_context(patch.object(probe,'close_selected_window'));stack.enter_context(patch.object(upload,'ensure_identity',return_value={}))
            stack.enter_context(patch('playwright.sync_api.sync_playwright'));stack.enter_context(patch.object(upload,'launch_context',return_value=self.context));stack.enter_context(patch.object(upload,'run_entry',side_effect=AssertionError('no upload')));stack.enter_context(patch.object(comments,'after_publication',side_effect=AssertionError('no comments')))
            result=probe.execute(seconds=.6);self.assertTrue(result['known_video_found'])
            for path,data in snapshots.items():self.assertEqual(path.read_bytes(),data)
            self.assertFalse(list((root/'logs').glob('*.lock')))
