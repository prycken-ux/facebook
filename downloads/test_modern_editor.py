"""Exercise the recorded native-file/Edit/Settings Page flow in local Chromium."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import fb_upload as upload
from test_personal import fast_expect


PROFILE = '''<html lang="en-US"><h1>Example Page</h1>
<button onclick="document.querySelector('#menu').hidden=false">Facebook menu</button>
<div id="menu" role="dialog" aria-label="Menu" hidden>
<button onclick="document.querySelector('#file').click()">Reel</button></div>
<input id="file" type="file" hidden onchange="location.href='https://www.facebook.com/reels/create?locale=en_US'">
</html>'''

EDITOR = '''<html lang="en-US"><h1>Create reel</h1>
<div contenteditable="true" role="combobox" aria-label="Search">Keep search unchanged</div>
<div id="edit"><h2>Edit</h2><div id="description-wrap"><span>Describe your reel...</span>
<div id="caption" contenteditable="true"></div></div>
<button id="next" onclick="window.savedCaption=document.querySelector('#caption').innerText;
window.nextClicks=(window.nextClicks||0)+1;document.querySelector('#edit').hidden=true;
document.querySelector('#settings').hidden=false;updatePost()">Next</button></div>
<div id="settings" hidden><h2>Settings</h2>
<button type="button" aria-label="Add AI label Add AI label We require you to label content">
<input id="ai" type="checkbox" aria-label="Off" onchange="window.aiChanges=(window.aiChanges||0)+1"></button>
<button id="audience" type="button"
onclick="document.querySelector('#audience-dialog').hidden=false"><span role="img" aria-label="Post audience"></span><span style="display:block">Post audience</span><span style="display:block" id="audience-value">Friends</span></button>
<div id="audience-dialog" role="dialog" aria-label="Post audience" hidden>
<input id="public-option" type="radio" aria-label="Public Anyone on or off Facebook">
<button type="button" onclick="if(document.querySelector('#public-option').checked){
document.querySelector('#audience-value').textContent='Public'};
document.querySelector('#audience-dialog').hidden=true;updatePost()">Done</button></div>
<button id="post" disabled onclick="window.postClicks=(window.postClicks||0)+1">Post</button></div>
<script>function updatePost(){document.querySelector('#post').disabled=!(window.savedCaption &&
document.querySelector('#audience').textContent.includes('Public'))}</script></html>'''


class ModernEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.video = Path(self.temporary.name) / "fixture.mp4"
        self.video.write_bytes(b"fixture video bytes")
        self.context = self.browser.new_context()
        self.context.add_cookies([{"name": "i_user", "value": "1001", "domain": ".facebook.com", "path": "/", "secure": True}])
        self.context.route("https://www.facebook.com/**", self.route)
        self.page = self.context.new_page()
        self.editor = EDITOR
        self.entry = {"account": "fb01", "target": "page01", "type": "page", "name": "Example Page",
                      "url": "https://www.facebook.com/profile.php?id=1001", "ai_label": True}
        self.caption = "Fixture multiline caption\n#Example"
        self.expect_patch = patch("playwright.sync_api.expect", side_effect=fast_expect)
        self.expect_patch.start()
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()

    def route(self, route):
        html = self.editor if urlparse(route.request.url).path == "/reels/create" else PROFILE
        route.fulfill(content_type="text/html", body=html)

    def tearDown(self):
        self.silence.__exit__(None, None, None)
        self.expect_patch.stop()
        self.context.close()
        self.temporary.cleanup()

    def prepare(self):
        return upload.prepare_reel(self.page, self.entry, self.video, self.caption)

    def test_native_upload_fills_description_before_single_next_and_checks_settings(self):
        button, proof = self.prepare()
        self.assertEqual(proof["editor_layout"], "modern")
        self.assertEqual(proof["method"], "page_actor_id_match")
        self.assertEqual(self.page.evaluate("window.savedCaption"), self.caption)
        self.assertEqual(self.page.evaluate("window.nextClicks"), 1)
        self.assertEqual(self.page.get_by_role("combobox", name="Search").inner_text(), "Keep search unchanged")
        self.assertTrue(self.page.locator("#ai").is_checked())
        self.assertEqual(self.page.locator("#audience").text_content(), "Post audiencePublic")
        self.assertIn("Public", self.page.locator("#audience").inner_text())
        self.assertTrue(button.is_enabled())
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_manual_entry_pause_precedes_file_selection_and_real_overlay_can_be_closed(self):
        overlay = '''<div id="veil" hidden style="position:fixed;inset:0;background:#0008;z-index:999">
        <button onclick="document.querySelector('#veil').hidden=true">Dismiss overlay</button></div>'''
        profile = PROFILE.replace("document.querySelector('#menu').hidden=false",
                                  "document.querySelector('#menu').hidden=false;document.querySelector('#veil').hidden=false")
        profile = profile.replace('</html>', overlay + '</html>')

        def assist(prompt):
            self.assertIn('READY', prompt)
            self.assertTrue(self.page.locator('#veil').is_visible())
            self.assertEqual(self.page.locator('#file').evaluate('e=>e.files.length'), 0)
            self.page.get_by_role('button', name='Dismiss overlay', exact=True).click()
            return 'READY'

        answers = iter(['', 'pasted command', 'READY'])

        def with_blanks(prompt):
            answer = next(answers)
            self.assertEqual(self.page.locator('#file').evaluate('e=>e.files.length'), 0)
            if answer == 'READY':
                return assist(prompt)
            return answer

        with patch.dict(globals(), {'PROFILE': profile}), patch('builtins.input', side_effect=with_blanks) as decision:
            button, proof = upload.prepare_reel(self.page, self.entry, self.video, self.caption,
                                               pause_before_reel=True)
        self.assertEqual(decision.call_count, 3)
        self.assertEqual(self.page.evaluate('window.savedCaption'), self.caption)
        self.assertTrue(button.is_enabled())
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_cancel_entry_pause_selects_no_file_and_never_reaches_editor(self):
        with patch('builtins.input', return_value='CANCEL'), self.assertRaisesRegex(RuntimeError, '协助已取消'):
            upload.prepare_reel(self.page, self.entry, self.video, self.caption, pause_before_reel=True)
        self.assertEqual(self.page.locator('#file').evaluate('e=>e.files.length'), 0)
        self.assertNotIn('/reels/create', self.page.url)

    def test_already_enabled_ai_is_not_toggled_off(self):
        self.editor = EDITOR.replace('id="ai" type="checkbox"', 'id="ai" checked type="checkbox"')
        self.prepare()
        self.assertTrue(self.page.locator("#ai").is_checked())
        self.assertIsNone(self.page.evaluate("window.aiChanges"))

    def test_real_video_switches_previously_enabled_ai_off(self):
        self.entry['ai_label'] = False
        self.editor = EDITOR.replace('id="ai" type="checkbox"', 'id="ai" checked type="checkbox"')
        self.editor = self.editor.replace('aria-label="Off"', 'aria-label="On"')
        button, _ = self.prepare()
        self.assertFalse(self.page.locator('#ai').is_checked())
        self.assertEqual(self.page.evaluate('window.aiChanges'), 1)
        self.assertEqual(self.page.evaluate('window.savedCaption'), self.caption)
        self.assertTrue(button.is_enabled())
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_real_video_does_not_click_already_disabled_ai(self):
        self.entry['ai_label'] = False
        self.prepare()
        self.assertFalse(self.page.locator('#ai').is_checked())
        self.assertIsNone(self.page.evaluate('window.aiChanges'))
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_named_textarea_is_supported(self):
        self.editor = EDITOR.replace('<div id="caption" contenteditable="true"></div>',
                                     '<textarea id="caption" aria-label="Describe your reel..."></textarea>')
        self.editor = self.editor.replace("document.querySelector('#caption').innerText", "document.querySelector('#caption').value")
        self.prepare()
        self.assertEqual(self.page.evaluate("window.savedCaption"), self.caption)

    def test_hashtag_overlay_is_blurred_before_next_with_text_and_link_preserved(self):
        self.caption = 'A perspective\nhttps://example.com/?a=1&b=2\n#LifeLessons'
        self.editor = EDITOR.replace('id="caption" contenteditable="true"',
            'id="caption" contenteditable="true" '
            'oninput="document.querySelector(\'#tags\').hidden=false" '
            'onblur="document.querySelector(\'#tags\').hidden=true"')
        self.editor = self.editor.replace('</html>', '''
        <div id="tags" hidden style="position:fixed;inset:0;z-index:999">#lifelessonslearned 47K posts</div>
        <script>document.addEventListener('keydown',e=>{if(e.key==='Escape'){
        window.escapePressed=true;document.querySelector('#edit').hidden=true}})</script></html>''')
        button, _ = self.prepare()
        self.assertEqual(self.page.evaluate('window.savedCaption'), self.caption)
        self.assertEqual(self.page.evaluate('window.nextClicks'), 1)
        self.assertTrue(self.page.locator('#tags').is_hidden())
        self.assertTrue(button.is_enabled())
        self.assertIsNone(self.page.evaluate('window.escapePressed'))
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_persistent_hashtag_list_closes_on_normal_title_click_without_changing_caption(self):
        self.caption='Original caption\nhttps://example.com/?a=1&b=2\n#LifeLessons'
        self.editor=EDITOR.replace('id="caption" contenteditable="true"',
            'id="caption" contenteditable="true" oninput="document.querySelector(\'#tags\').hidden=false"')
        self.editor=self.editor.replace('</html>','''<div id="tags" hidden style="position:fixed;top:80px;left:0;width:90vw;height:80vh;z-index:999">
        <div>#lifelessons 30M posts</div><div>#lifelessonsfromfishing 100K posts</div></div>
        <script>document.querySelector('h1').addEventListener('click',()=>document.querySelector('#tags').hidden=true)</script></html>''')
        button,_=self.prepare()
        self.assertEqual(self.page.evaluate('window.savedCaption'),self.caption)
        self.assertEqual(self.page.evaluate('window.nextClicks'),1)
        self.assertTrue(button.is_enabled());self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_recognized_stubborn_hashtag_list_uses_focused_next_keyboard_only(self):
        self.caption='Original caption\nhttps://example.com/?a=1&b=2\n#LifeLessons'
        self.editor=EDITOR.replace('id="caption" contenteditable="true"',
            'id="caption" contenteditable="true" oninput="document.querySelector(\'#tags\').hidden=false"')
        self.editor=self.editor.replace('</html>','''<div id="tags" hidden style="position:fixed;top:80px;left:0;width:90vw;height:80vh;z-index:999">
        <div>#lifelessons 30M posts</div><div>#lifelessonsfromfishing 100K posts</div></div>
        <script>document.querySelector('#next').addEventListener('click',()=>document.querySelector('#tags').hidden=true)</script></html>''')
        button,_=self.prepare()
        self.assertEqual(self.page.evaluate('window.savedCaption'),self.caption)
        self.assertEqual(self.page.evaluate('window.nextClicks'),1)
        self.assertTrue(button.is_enabled());self.assertIsNone(self.page.evaluate('window.postClicks'))
        self.assertIn('键盘激活',self.silence._new_target.getvalue())

    def test_unknown_modal_never_uses_next_keyboard_or_changes_caption(self):
        self.editor=EDITOR.replace('id="caption" contenteditable="true"',
            'id="caption" contenteditable="true" oninput="document.querySelector(\'#unknown\').hidden=false"')
        self.editor=self.editor.replace('</html>','''<div id="unknown" role="dialog" hidden style="position:fixed;inset:0;z-index:999">Unknown security check</div></html>''')
        with self.assertRaisesRegex(RuntimeError,'未知弹窗'):
            self.prepare()
        self.assertIsNone(self.page.evaluate('window.nextClicks'));self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_blur_mutation_of_rich_caption_stops_before_next(self):
        self.editor = EDITOR.replace('id="caption" contenteditable="true"',
                                    'id="caption" contenteditable="true" onblur="this.innerText+=\' changed\'"')
        with self.assertRaises(AssertionError):
            self.prepare()
        self.assertIsNone(self.page.evaluate('window.nextClicks'))
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_ambiguous_description_never_advances_or_posts(self):
        self.editor = EDITOR.replace('<div id="caption" contenteditable="true"></div>',
                                     '<div id="caption" contenteditable="true"></div><div contenteditable="true"></div>')
        with self.assertRaisesRegex(RuntimeError, "关联多个可编辑区域"):
            self.prepare()
        self.assertIsNone(self.page.evaluate("window.nextClicks"))
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_unsaved_public_selection_stops_before_post(self):
        self.editor = EDITOR.replace("if(document.querySelector('#public-option').checked)", "if(false)")
        with self.assertRaises(AssertionError):
            self.prepare()
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_already_public_does_not_open_selector_or_reset_editor(self):
        self.editor = EDITOR.replace('id="audience-value">Friends', 'id="audience-value">Public')
        self.editor = self.editor.replace(
            "document.querySelector('#audience-dialog').hidden=false",
            "window.audienceClicks=1;location.href='https://www.facebook.com/reels/create?reset=1'"
        )
        button, _ = self.prepare()
        self.assertEqual(self.page.evaluate("window.savedCaption"), self.caption)
        self.assertIsNone(self.page.evaluate("window.audienceClicks"))
        self.assertNotIn("reset=1", self.page.url)
        self.assertTrue(button.is_enabled())
        self.assertTrue(self.page.locator("#ai").is_checked())
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_unknown_audience_does_not_open_selector_or_post(self):
        self.editor = EDITOR.replace('id="audience-value">Friends', 'id="audience-value">Only me')
        with self.assertRaisesRegex(RuntimeError, "未显示已识别的 Public/Friends"):
            self.prepare()
        self.assertTrue(self.page.locator("#audience-dialog").is_hidden())
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_missing_description_does_not_fill_unrelated_search(self):
        self.editor = EDITOR.replace('<div id="caption" contenteditable="true"></div>', '<div id="caption"></div>')
        self.page.goto("https://www.facebook.com/reels/create")
        with self.assertRaisesRegex(RuntimeError, "未找到新版"):
            upload.modern_caption_field(self.page, timeout_ms=100)
        self.assertEqual(self.page.get_by_role("combobox", name="Search").inner_text(), "Keep search unchanged")

    def test_stalled_next_is_retried_once_only_while_confirmed_edit_step_remains(self):
        self.editor=EDITOR.replace('<div id="edit">','''<div id="edit"><nav aria-label="Reel creation steps">
            <span>Edit ›</span><button type="button">Settings</button></nav>''').replace(
            'onclick="window.savedCaption=',"onclick=\"window.attempts=(window.attempts||0)+1;if(window.attempts===1)return;window.savedCaption=")
        self.page.goto('https://www.facebook.com/reels/create')
        upload.fill_caption(upload.modern_caption_field(self.page),self.caption)
        upload.advance_modern_reel(self.page,self.caption,timeout_ms=1500,retry_after_ms=100)
        self.assertEqual(self.page.evaluate('window.attempts'),2)
        self.assertEqual(self.page.evaluate('window.nextClicks'),1)
        self.assertEqual(self.page.evaluate('window.savedCaption'),self.caption)
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_unknown_stalled_edit_layout_is_not_blindly_clicked_again(self):
        self.editor=EDITOR.replace('onclick="window.savedCaption=',
            'onclick="window.attempts=(window.attempts||0)+1;return;window.savedCaption=')
        self.page.goto('https://www.facebook.com/reels/create')
        upload.fill_caption(upload.modern_caption_field(self.page),self.caption)
        with self.assertRaisesRegex(RuntimeError,'未确认进入 Settings'):
            upload.advance_modern_reel(self.page,self.caption,timeout_ms=300,retry_after_ms=50)
        self.assertEqual(self.page.evaluate('window.attempts'),1)
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_single_audience_label_is_verified_without_requiring_duplicated_text(self):
        self.editor=EDITOR.replace('<span role="img" aria-label="Post audience"></span>','')
        button,proof=self.prepare()
        self.assertTrue(button.is_enabled())
        self.assertIn('Public',self.page.locator('#audience').inner_text())
        self.assertIsNone(self.page.evaluate('window.postClicks'))


if __name__ == "__main__":
    unittest.main()
