import contextlib
import io
import re
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import fb_upload as upload
import reel_audience_dialog_recovery as recovery
import install_reel_audience_recovery_20261119 as installer


HTML = '''<html><body>
<div role="dialog" aria-label="Reel settings" id="settings" style="width:400px;height:400px">
<button aria-label="Close" onclick="window.editorClosed=1">Editor close</button>
<button id="audience" onclick="document.querySelector('#picker').hidden=false">Friends Your friends on Facebook</button>
<textarea aria-label="Describe your reel...">Keep this caption</textarea>
<video src="fixture.mp4"></video><button onclick="window.posts=1">Post</button>
</div>
<div id="picker" role="dialog" aria-label="Choose audience" hidden style="width:350px;height:150px">
<input type="radio" id="public" aria-label="Public Anyone on or off Facebook">
<button onclick="if(document.querySelector('#public').checked){document.querySelector('#audience').textContent='Public Anyone on or off Facebook'};this.parentElement.hidden=true">Done</button>
</div>
OVERLAY
<script>
function dismissPrompt(){window.promptClicks=(window.promptClicks||0)+1;document.querySelector('#overlay').remove();document.querySelector('#settings').removeAttribute('aria-hidden');document.querySelector('#audience').hidden=false}
</script></body></html>'''
SKELETON = '''<div role="dialog" id="overlay" style="position:fixed;left:420px;top:80px;width:480px;height:160px;background:white;z-index:99">
<button aria-label="Close" onclick="dismissPrompt()">×</button><div style="height:20px;background:#ddd"></div></div>'''
CONTINUE = '''<div role="dialog" aria-label="Review audience" id="overlay" style="position:fixed;left:420px;top:80px;width:480px;height:160px;background:white;z-index:99">
<h2>Review audience</h2><p>Choose who can see your reels.</p><button onclick="dismissPrompt()">Continue</button></div>'''


class AudienceRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)

    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.context=self.browser.new_context(viewport=dict(width=1100,height=800))
        self.page=self.context.new_page()
        self.page.route('https://www.facebook.com/**',lambda r:r.fulfill(body='<html></html>',content_type='text/html'))
        self.page.goto('https://www.facebook.com/reels/create')
        self.original=upload.ensure_personal_public_audience
        exec(installer.PATCHED_FUNCTION,upload.__dict__)
        self.addCleanup(setattr,upload,'ensure_personal_public_audience',self.original)
        native=recovery.wait_for_public_controls
        self.enterContext(patch.object(recovery,'wait_for_public_controls',side_effect=lambda p,s,c:native(p,s,c,timeout_ms=800,grace_ms=30)))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def tearDown(self):self.context.close()

    def load(self,overlay=SKELETON):
        self.page.set_content(HTML.replace('OVERLAY',overlay))
        if overlay:
            self.page.locator('#settings').evaluate("e=>e.setAttribute('aria-hidden','true')")
            self.page.locator('#audience').evaluate('e=>e.hidden=true')

    def verify_kept(self):
        self.assertEqual(self.page.get_by_role('textbox',name='Describe your reel...',include_hidden=True).input_value(),'Keep this caption')
        self.assertEqual(self.page.locator('video').get_attribute('src'),'fixture.mp4')
        self.assertIsNone(self.page.evaluate('window.posts'))
        self.assertIsNone(self.page.evaluate('window.editorClosed'))

    def test_stalled_skeleton_close_then_public_without_closing_editor(self):
        self.load();upload.ensure_personal_public_audience(self.page)
        self.assertEqual(self.page.evaluate('window.promptClicks'),1)
        self.assertTrue(self.page.locator('#public').is_checked())
        self.assertIn('Public',self.page.locator('#audience').inner_text());self.verify_kept()

    def test_known_review_audience_continue_then_public(self):
        self.load(CONTINUE);upload.ensure_personal_public_audience(self.page)
        self.assertEqual(self.page.evaluate('window.promptClicks'),1);self.verify_kept()
        self.assertIn('Public',self.page.locator('#audience').inner_text())

    def test_prompt_that_finishes_loading_in_grace_is_not_clicked(self):
        self.load()
        self.page.evaluate("setTimeout(()=>{document.querySelector('#overlay').remove();document.querySelector('#settings').removeAttribute('aria-hidden');document.querySelector('#audience').hidden=false},10)")
        upload.ensure_personal_public_audience(self.page)
        self.assertIsNone(self.page.evaluate('window.promptClicks'));self.verify_kept()

    def test_no_prompt_never_uses_editor_close(self):
        self.load('');upload.ensure_personal_public_audience(self.page);self.verify_kept()

    def test_security_and_discard_and_unknown_dialogs_are_never_clicked(self):
        for title in ('Confirm this is your Meta Account','Discard reel','Unknown popup'):
            with self.subTest(title=title):
                overlay=CONTINUE.replace('Review audience',title)
                self.load(overlay)
                with self.assertRaises(recovery.AudienceRecoveryBlocked):upload.ensure_personal_public_audience(self.page)
                self.assertIsNone(self.page.evaluate('window.promptClicks'));self.verify_kept()

    def test_blank_dialog_with_password_control_is_not_a_loading_hint(self):
        self.load(SKELETON.replace('<div style=', '<input type="password"><div style='))
        with self.assertRaises(recovery.AudienceRecoveryBlocked):upload.ensure_personal_public_audience(self.page)
        self.assertIsNone(self.page.evaluate('window.promptClicks'));self.verify_kept()

    def test_duplicate_review_prompts_stop_without_any_click(self):
        self.load(CONTINUE+CONTINUE.replace('id="overlay"','id="second"'))
        with self.assertRaisesRegex(recovery.AudienceRecoveryBlocked,'不唯一'):upload.ensure_personal_public_audience(self.page)
        self.assertIsNone(self.page.evaluate('window.promptClicks'));self.verify_kept()

    def test_login_redirect_stops_without_dismissing(self):
        self.page.goto('https://www.facebook.com/checkpoint/')
        self.load()
        with self.assertRaisesRegex(recovery.AudienceRecoveryBlocked,'安全验证'):upload.ensure_personal_public_audience(self.page)
        self.assertIsNone(self.page.evaluate('window.promptClicks'))

    def test_public_must_still_be_saved_after_continue(self):
        self.load(CONTINUE)
        self.page.locator('#picker button').evaluate("e=>e.setAttribute('onclick','this.parentElement.hidden=true')")
        with patch('playwright.sync_api.expect',side_effect=__import__('test_personal').fast_expect):
            with self.assertRaises(AssertionError):upload.ensure_personal_public_audience(self.page)
        self.verify_kept()


if __name__=='__main__':unittest.main()
