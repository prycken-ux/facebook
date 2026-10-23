import contextlib
import io
import unittest
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import fb_upload as upload

HTML = '''<div role="banner"><div role="button" tabindex="0" id="menu" aria-label="Facebook menu"
aria-expanded="false" aria-haspopup="dialog" style="position:absolute;left:0;top:0;width:150px;height:50px"
onclick="openMenu()" onkeydown="if(event.key==='Enter'){openMenu()}">Menu</div>
<ul role="list" id="cover" style="position:absolute;left:0;top:0;margin:0;width:160px;height:60px;background:white;z-index:10"><li>Navigation</li></ul></div>
<div role="dialog" aria-label="Menu" id="drawer" hidden><button>Reel</button></div>
<button onclick="window.postClicks=(window.postClicks||0)+1">Post</button>
<script>function openMenu(){window.menuActions=(window.menuActions||0)+1;
document.querySelector('#menu').setAttribute('aria-expanded','true');document.querySelector('#drawer').hidden=false;}</script>'''


class MenuKeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.set_default_timeout(500)
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()

    def tearDown(self):
        self.silence.__exit__(None, None, None)
        self.page.close()

    def test_actual_banner_intercepts_click_but_keyboard_opens_only_menu(self):
        self.page.set_content(HTML)
        with self.assertRaises(PlaywrightTimeoutError):
            self.page.get_by_role('button', name='Facebook menu').click(timeout=150)
        upload.open_facebook_menu(self.page, 150, 1000)
        self.assertEqual(self.page.evaluate('window.menuActions'), 1)
        self.assertTrue(self.page.get_by_role('dialog', name='Menu').is_visible())
        self.assertTrue(self.page.locator('#cover').is_visible())
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_already_open_menu_is_not_toggled_or_clicked(self):
        self.page.set_content(HTML)
        self.page.evaluate('openMenu()')
        upload.open_facebook_menu(self.page, 150, 500)
        self.assertEqual(self.page.evaluate('window.menuActions'), 1)

    def test_unknown_security_dialog_is_not_bypassed_by_keyboard(self):
        self.page.set_content(HTML + '<div role="alertdialog" aria-label="Confirm identity" style="position:fixed;inset:0;z-index:99;background:white">Check</div>')
        with self.assertRaises(PlaywrightTimeoutError):
            upload.open_facebook_menu(self.page, 150, 300)
        self.assertIsNone(self.page.evaluate('window.menuActions'))
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_enter_without_real_opening_stops_before_file_selection(self):
        self.page.set_content(HTML.replace("if(event.key==='Enter'){openMenu()}", 'window.keyActions=1'))
        with self.assertRaisesRegex(RuntimeError, '未确认'):
            upload.open_facebook_menu(self.page, 150, 200)
        self.assertEqual(self.page.evaluate('window.keyActions'), 1)
        self.assertIsNone(self.page.evaluate('window.menuActions'))

    def test_disabled_menu_does_not_get_keyboard_activation(self):
        self.page.set_content(HTML.replace('aria-expanded="false"', 'aria-expanded="false" aria-disabled="true"'))
        with self.assertRaises(PlaywrightTimeoutError):
            upload.open_facebook_menu(self.page, 150, 200)
        self.assertIsNone(self.page.evaluate('window.menuActions'))


if __name__ == '__main__':
    unittest.main()
