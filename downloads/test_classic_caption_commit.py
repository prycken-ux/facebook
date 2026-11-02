import unittest
from unittest.mock import patch
from playwright.sync_api import sync_playwright
import fb_upload as upload
from test_personal import fast_expect

class ClassicCaptionCommitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.page=self.browser.new_page();self.text='Original caption\nhttps://www.amazon.com/s?tag=maas&me=SHOP\n#LifeLessons'
        self.page.set_content('''<div role="dialog" aria-label="Reel settings"><h2 onclick="document.querySelector('#suggestions').hidden=true;document.querySelector('#post').disabled=false">Reel settings</h2>
<textarea aria-label="Describe your reel..." oninput="document.querySelector('#suggestions').hidden=false"></textarea>
<div id=suggestions hidden><div role=option onclick="window.wrongSuggestion=true">#lifelessons</div></div>
<button id=post disabled onclick="window.posted=true">Post</button></div>''')
        self.field=self.page.get_by_role('textbox',name='Describe your reel...',exact=True)
        self.patch=patch('playwright.sync_api.expect',side_effect=fast_expect);self.patch.start()
    def tearDown(self):self.patch.stop();self.page.close()
    def test_neutral_title_commits_caption_without_selecting_suggestion_or_publishing(self):
        upload.fill_caption(self.field,self.text)
        self.assertTrue(self.page.locator('#suggestions').is_visible());self.assertFalse(self.page.locator('#post').is_enabled())
        upload.commit_classic_caption(self.page,self.field,self.text)
        upload.wait_prepost_upload(self.page,self.page.locator('#post'),timeout_ms=200,stable_ms=20)
        self.assertFalse(self.page.locator('#suggestions').is_visible());self.assertEqual(self.field.input_value(),self.text)
        self.assertIsNone(self.page.evaluate('window.wrongSuggestion'));self.assertIsNone(self.page.evaluate('window.posted'))
    def test_unknown_modal_or_changed_caption_never_reaches_publish_readiness(self):
        upload.fill_caption(self.field,self.text)
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=dialog>Unknown</div>')")
        with self.assertRaises(RuntimeError):upload.commit_classic_caption(self.page,self.field,self.text)
        self.assertIsNone(self.page.evaluate('window.posted'))
        self.page.get_by_role('dialog',name='Unknown').count()  # Exact settings still untouched.
        self.page.locator('[role=dialog]').last.evaluate('e=>e.remove()')
        self.page.get_by_role('heading').evaluate("e=>e.onclick=()=>document.querySelector('textarea').value='wrong text'")
        with self.assertRaises(AssertionError):upload.commit_classic_caption(self.page,self.field,self.text)
        self.assertIsNone(self.page.evaluate('window.posted'))
