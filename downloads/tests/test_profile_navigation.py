import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

from playwright.sync_api import Error as BrowserError, TimeoutError as BrowserTimeout

import fb_upload as upload


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.page=MagicMock()
        self.page.url='https://www.facebook.com/profile.php?id=1001'
        self.page.is_closed.return_value=False
        self.silent=contextlib.redirect_stdout(io.StringIO())
        self.silent.__enter__()

    def tearDown(self):
        self.silent.__exit__(None,None,None)

    def test_one_timeout_recovers_with_same_profile_get_and_checks_checkpoint(self):
        self.page.goto.side_effect=[BrowserError('Page.goto: net::ERR_TIMED_OUT'),MagicMock()]
        result=upload.navigate_profile(self.page,self.page.url)
        self.assertIsNotNone(result)
        self.assertEqual(self.page.goto.call_count,2)
        first,second=self.page.goto.call_args_list
        self.assertEqual(first,second)
        self.assertIn('locale=en_US',first.args[0])
        self.page.wait_for_timeout.assert_called_once_with(2000)

    def test_second_timeout_is_not_repeated(self):
        self.page.goto.side_effect=BrowserTimeout('timeout')
        with self.assertRaises(BrowserTimeout):
            upload.navigate_profile(self.page,self.page.url)
        self.assertEqual(self.page.goto.call_count,2)

    def test_proxy_ssl_abort_and_closed_browser_are_not_retried(self):
        for message in ('net::ERR_PROXY_CONNECTION_FAILED','net::ERR_CERT_AUTHORITY_INVALID',
                        'net::ERR_ABORTED','Target page, context or browser has been closed'):
            with self.subTest(message=message):
                self.page.reset_mock()
                self.page.goto.side_effect=BrowserError(message)
                with self.assertRaises(BrowserError):
                    upload.navigate_profile(self.page,self.page.url)
                self.assertEqual(self.page.goto.call_count,1)

    def test_verification_redirect_is_never_retried_on_timeout_or_success(self):
        for error in (BrowserTimeout('timeout'),None):
            self.page.reset_mock()
            self.page.url='https://www.facebook.com/two_step_verification/authentication/'
            self.page.goto.side_effect=error
            with self.assertRaisesRegex(RuntimeError,'安全验证'):
                upload.navigate_profile(self.page,'https://www.facebook.com/profile.php?id=1001')
            self.assertEqual(self.page.goto.call_count,1)

    def test_editor_post_route_and_non_facebook_urls_are_rejected(self):
        for url in ('https://www.facebook.com/reels/create','https://www.facebook.com/reel/123',
                    'https://example.com/me','http://www.facebook.com/example'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                upload.navigate_profile(self.page,url)
        self.page.goto.assert_not_called()

    def test_prepare_never_retries_editor_file_selection_or_post(self):
        entry=dict(url=self.page.url,name='Example',type='personal')
        with patch.object(upload,'navigate_profile') as navigate, \
             patch.object(upload,'ensure_identity',return_value={}), \
             patch.object(upload,'require_english_interface'), \
             patch.object(upload,'open_facebook_menu'), \
             patch.object(upload,'select_reel_video',side_effect=BrowserTimeout('file selection timeout')) as select:
            with self.assertRaises(BrowserTimeout):
                upload.prepare_reel(self.page,entry,MagicMock(),'caption')
        navigate.assert_called_once()
        select.assert_called_once()


if __name__=='__main__':
    unittest.main()
