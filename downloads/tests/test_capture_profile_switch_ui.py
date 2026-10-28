import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from playwright.sync_api import sync_playwright

import capture_profile_switch_ui as capture


HTML = '''<header role="banner"><a href="https://www.facebook.com/?private=do-not-export">Home</a>
<button aria-label="Account menu"><svg role="img" aria-label="Your profile"></svg></button></header>
<div role="dialog"><h2>Your profiles &amp; Pages</h2><input aria-label="Search profiles and Pages" value="do-not-export">
<div role="button"><span>Example Page</span><span>1 notification</span></div></div>'''


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.context.route('https://www.facebook.com/**',lambda route: route.fulfill(content_type='text/html',body=HTML))
        self.page = self.context.new_page()
        self.page.goto('https://www.facebook.com/profile.php?id=1001')
        self.silent = contextlib.redirect_stdout(io.StringIO())
        self.silent.__enter__()

    def tearDown(self):
        self.silent.__exit__(None,None,None)
        self.context.close()

    def test_actual_banner_name_and_nested_image_label_are_captured(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            capture.capture(self.page,folder,'picker')
            controls=json.loads((folder/'picker-controls.json').read_text())
            buttons=controls[0]['controls']
            self.assertEqual(buttons[1]['label'],'Account menu')
            self.assertEqual(buttons[1]['images'][0]['label'],'Your profile')
            self.assertTrue((folder/'picker.png').is_file())
            self.assertIn('Account menu',(folder/'picker-banner-0.txt').read_text())
            self.assertNotIn('do-not-export',(folder/'picker-dialog-0.txt').read_text())

    def test_url_destinations_are_removed_from_accessibility_snapshot(self):
        result=capture.clean_aria('- link "Home":\n  - /url: https://example.invalid/?private=value\n- button "Account"')
        self.assertNotIn('private',result)
        self.assertIn('Account',result)

    def test_controls_do_not_serialize_search_values_or_raw_dom(self):
        value=self.page.get_by_role('dialog').evaluate(capture.CONTROLS_JS)
        text=json.dumps(value)
        self.assertNotIn('do-not-export',text)
        self.assertNotIn('href',text)
        self.assertNotIn('outerHTML',text)

    def test_missing_banner_role_still_captures_avatar_outside_notifications(self):
        self.page.set_content('''<html><body style="margin:0">
            <div style="height:56px;display:flex;justify-content:flex-end">
              <div role="button" aria-label="Notifications" aria-haspopup="dialog">Bell</div>
              <div role="button" aria-haspopup="menu" data-testid="account-control" style="width:40px;height:40px">
                <svg role="img" aria-label="Current profile"><image href="private-avatar-url" /></svg>
              </div>
            </div>
            <div role="dialog" aria-label="Notifications"><h1>Notifications</h1>
              <button aria-label="Notification Actions">Actions</button></div>
            <input type="password" value="private-form-value"></body></html>''')
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            capture.capture(self.page,folder,'automatic-failure')
            scoped=json.loads((folder/'automatic-failure-controls.json').read_text())
            self.assertEqual([region['role'] for region in scoped],['dialog'])
            top=json.loads((folder/'automatic-failure-top-controls.json').read_text())
            avatar=next(row for row in top['controls'] if row['testId']=='account-control')
            self.assertEqual(avatar['hasPopup'],'menu')
            self.assertEqual(avatar['images'][0]['label'],'Current profile')
            self.assertFalse(avatar['inDialog'])
            serialized=json.dumps(top)
            self.assertNotIn('private-avatar-url',serialized)
            self.assertNotIn('private-form-value',serialized)

    def test_automatic_stages_never_prompt_or_click_controls(self):
        self.page.evaluate('''() => {window.clicks=0;document.addEventListener('click',()=>window.clicks++);}''')
        read=Mock(side_effect=AssertionError('automatic capture must not prompt'))
        with tempfile.TemporaryDirectory() as temp,patch.object(self.page,'wait_for_timeout') as wait:
            folder=Path(temp)
            capture.collect_stages(self.page,folder,automatic=True,read=read)
            self.assertEqual([call.args[0] for call in wait.call_args_list],[5000,10000])
            self.assertTrue((folder/'initial-top-controls.json').is_file())
            self.assertTrue((folder/'loaded-5s-top-controls.json').is_file())
            self.assertTrue((folder/'loaded-15s-top-controls.json').is_file())
            self.assertEqual(self.page.evaluate('window.clicks'),0)
        read.assert_not_called()

    def test_top_controls_collect_labelledby_text_without_exporting_link_targets(self):
        self.page.set_content('''<div><span id="name">Profile menu label</span>
            <a role="button" aria-labelledby="name" href="https://example.invalid/private-link">Open</a>
            <input value="private-search-value"></div>''')
        value=self.page.locator('body').evaluate(capture.TOP_CONTROLS_JS)
        button=next(row for row in value['controls'] if row['labelledByText']=='Profile menu label')
        self.assertEqual(button['tag'],'A')
        self.assertNotIn('private-link',json.dumps(value))
        self.assertNotIn('private-search-value',json.dumps(value))

    def test_blank_or_pasted_commands_do_not_act_as_ready(self):
        answers=iter(['','Some pasted command','READY'])
        capture.wait_for_picker(self.page,read=lambda prompt:next(answers))
        self.assertTrue(self.page.get_by_role('dialog').is_visible())

    def test_cancel_and_eof_stop_collection(self):
        with self.assertRaisesRegex(RuntimeError,'已取消'):
            capture.wait_for_picker(self.page,read=lambda prompt:'CANCEL')
        def eof(prompt):
            raise EOFError
        with self.assertRaisesRegex(RuntimeError,'已取消'):
            capture.wait_for_picker(self.page,read=eof)

    def test_security_checkpoint_stops_without_capturing(self):
        self.page.goto('https://www.facebook.com/two_step_verification/authentication/')
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'evidence'
            with self.assertRaisesRegex(RuntimeError,'登录或安全验证'):
                capture.capture(self.page,folder,'security')
            self.assertFalse(folder.exists())


if __name__ == '__main__':
    unittest.main()
