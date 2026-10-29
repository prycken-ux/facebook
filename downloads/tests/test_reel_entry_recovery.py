import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright,TimeoutError as BrowserTimeout

import fb_upload as upload


HTML='''<div role="dialog" aria-label="Menu"><div role="button" tabindex="0" aria-label="Reel"
style="position:absolute;left:10px;top:20px;width:120px;height:40px"
onclick="window.mouse=(window.mouse||0)+1;document.querySelector('#file').click()"
onkeydown="if(event.key==='Enter'){window.keyboard=(window.keyboard||0)+1;document.querySelector('#file').click()}">Reel</div></div>
<div role="banner"><div id="cover" style="position:absolute;left:0;top:0;width:180px;height:100px;background:white;z-index:50">Navigation</div></div>
<input id="file" type="file" hidden onchange="window.files=(window.files||0)+1">
<button onclick="window.post=(window.post||0)+1">Post</button>'''


class ReelEntryRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)

    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.page=self.browser.new_page()
        self.temp=tempfile.TemporaryDirectory();self.video=Path(self.temp.name)/'exact.mp4'
        self.video.write_bytes(b'exact source')
        self.silence=contextlib.redirect_stdout(io.StringIO());self.silence.__enter__()
        self.page.set_content(HTML)
        self.reel=self.page.get_by_role('button',name='Reel',exact=True)

    def tearDown(self):self.silence.__exit__(None,None,None);self.page.close();self.temp.cleanup()

    def test_banner_blocked_reel_uses_keyboard_for_same_control_and_selects_file_once(self):
        method=upload.select_reel_video(self.page,self.reel,self.video,timeout_ms=300)
        self.assertEqual(method,'native_file_chooser')
        self.assertEqual(self.page.evaluate('window.files'),1)
        self.assertEqual(self.page.evaluate('window.keyboard'),1)
        self.assertIsNone(self.page.evaluate('window.mouse'))
        self.assertIsNone(self.page.evaluate('window.post'))

    def test_unknown_modal_is_not_bypassed_to_activate_reel(self):
        self.page.set_content(HTML+'<div role="alertdialog" aria-label="Confirm identity" style="position:fixed;inset:0;z-index:99;background:white">Check</div>')
        with self.assertRaisesRegex(RuntimeError,'未知弹窗'):
            upload.select_reel_video(self.page,self.reel,self.video,timeout_ms=150)
        self.assertIsNone(self.page.evaluate('window.keyboard'))
        self.assertIsNone(self.page.evaluate('window.files'))

    def test_chooser_already_started_when_click_reports_timeout_never_activates_again(self):
        self.page.locator('#cover').evaluate('e=>e.remove()')
        original=self.reel.click
        def click(*args,**kwargs):
            original(*args,**kwargs)
            raise BrowserTimeout('click completion timed out after chooser')
        with patch.object(self.reel,'click',side_effect=click):
            self.assertEqual(upload.select_reel_video(self.page,self.reel,self.video,timeout_ms=1000),'native_file_chooser')
        self.assertEqual(self.page.evaluate('window.files'),1)
        self.assertIsNone(self.page.evaluate('window.keyboard'))

    def test_advanced_protection_stops_without_closing_or_changing_passkey(self):
        protection='''<div role="dialog"><h2>Your account needs Advanced Protection</h2>
            <button onclick="window.changedSecurity=1">Create passkey</button>
            <button onclick="window.closedSecurity=1">Close</button></div>'''
        self.page.set_content(HTML+protection)
        with self.assertRaises(upload.AccountActionRequired):upload.open_facebook_menu(self.page,150,150)
        with self.assertRaises(upload.AccountActionRequired):upload.select_reel_video(self.page,self.reel,self.video,timeout_ms=150)
        self.assertIsNone(self.page.evaluate('window.changedSecurity'))
        self.assertIsNone(self.page.evaluate('window.closedSecurity'))
        self.assertIsNone(self.page.evaluate('window.files'))


if __name__=='__main__':unittest.main()
