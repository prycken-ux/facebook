"""Reproduce the notification overlay that intercepted the Facebook menu."""
import contextlib
import io
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import fb_upload as upload


FIXTURE = """<button id="menu" onclick="window.menuClicks=(window.menuClicks||0)+1">Facebook menu</button>
<button onclick="window.outsideClicks=(window.outsideClicks||0)+1">Close</button>
<div id="prompt" role="alertdialog" aria-modal="true" aria-label="Push notifications request"
style="position:fixed;inset:0;background:white;z-index:999">
<button onclick="window.allowClicks=(window.allowClicks||0)+1">Turn on</button>
<button id="decline" onclick="window.declineClicks=(window.declineClicks||0)+1;document.querySelector('#prompt').hidden=true">Not now</button>
</div><button onclick="window.postClicks=(window.postClicks||0)+1">Post</button>"""


class NotificationPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.set_default_timeout(800)
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()

    def tearDown(self):
        self.silence.__exit__(None, None, None)
        self.page.close()

    def test_real_overlay_reproduces_old_timeout_then_safe_dismissal_opens_menu(self):
        self.page.set_content(FIXTURE)
        with self.assertRaises(PlaywrightTimeoutError):
            self.page.get_by_role('button', name='Facebook menu', exact=True).click(timeout=150)
        upload.open_facebook_menu(self.page)
        self.assertEqual(self.page.evaluate('window.declineClicks'), 1)
        self.assertEqual(self.page.evaluate('window.menuClicks'), 1)
        for variable in ('allowClicks', 'outsideClicks', 'postClicks'):
            self.assertIsNone(self.page.evaluate('window.' + variable))

    def test_alternative_negative_labels_and_scoped_close(self):
        for label in ("Don't allow", 'Close', 'Not Now'):
            with self.subTest(label=label):
                self.page.set_content(FIXTURE.replace('>Not now<', '>' + label + '<'))
                self.page.evaluate('window.menuClicks=0;window.declineClicks=0')
                upload.open_facebook_menu(self.page)
                self.assertEqual(self.page.evaluate('window.declineClicks'), 1)
                self.assertEqual(self.page.evaluate('window.menuClicks'), 1)
                self.assertIsNone(self.page.evaluate('window.outsideClicks'))

    def test_absent_prompt_does_not_touch_unrelated_buttons(self):
        self.page.set_content(FIXTURE.replace('id="prompt"', 'id="prompt" hidden'))
        upload.open_facebook_menu(self.page)
        self.assertEqual(self.page.evaluate('window.menuClicks'), 1)
        self.assertIsNone(self.page.evaluate('window.declineClicks'))
        self.assertIsNone(self.page.evaluate('window.outsideClicks'))

    def test_unknown_or_ambiguous_dismissal_stops_without_allowing_notifications(self):
        for html in (FIXTURE.replace('>Not now<', '>Continue<'),
                     FIXTURE.replace('</div>', '<button>Close</button></div>')):
            with self.subTest(html=html):
                self.page.set_content(html)
                with self.assertRaisesRegex(RuntimeError, '没有唯一'):
                    upload.open_facebook_menu(self.page)
                self.assertIsNone(self.page.evaluate('window.menuClicks'))
                self.assertIsNone(self.page.evaluate('window.allowClicks'))
                self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_unrelated_security_dialog_is_not_dismissed(self):
        self.page.set_content(FIXTURE.replace('Push notifications request', 'Confirm your identity'))
        with self.assertRaises(PlaywrightTimeoutError):
            upload.open_facebook_menu(self.page)
        self.assertIsNone(self.page.evaluate('window.declineClicks'))
        self.assertIsNone(self.page.evaluate('window.menuClicks'))

    def test_delayed_overlay_is_dismissed_during_menu_wait(self):
        self.page.set_content(FIXTURE.replace('id="menu"', 'id="menu" disabled').replace('id="prompt"', 'id="prompt" hidden'))
        self.page.evaluate("""() => {
            setTimeout(()=>document.querySelector('#prompt').hidden=false, 50);
            setTimeout(()=>document.querySelector('#menu').disabled=false, 100);
        }""")
        upload.open_facebook_menu(self.page)
        self.assertEqual(self.page.evaluate('window.declineClicks'), 1)
        self.assertEqual(self.page.evaluate('window.menuClicks'), 1)

    def test_handler_does_not_remain_active_after_menu_step(self):
        self.page.set_content(FIXTURE)
        upload.open_facebook_menu(self.page)
        self.page.evaluate("document.querySelector('#prompt').hidden=false")
        with self.assertRaises(PlaywrightTimeoutError):
            self.page.get_by_role('button', name='Facebook menu', exact=True).click(timeout=150)
        self.assertEqual(self.page.evaluate('window.declineClicks'), 1)

    def test_handler_is_removed_on_menu_failure(self):
        self.page.set_content(FIXTURE.replace('id="menu"', 'id="menu" disabled').replace('id="prompt"', 'id="prompt" hidden'))
        with patch.object(self.page, 'remove_locator_handler', wraps=self.page.remove_locator_handler) as remove:
            with self.assertRaises(PlaywrightTimeoutError):
                upload.open_facebook_menu(self.page)
            remove.assert_called_once()


if __name__ == '__main__':
    unittest.main()
