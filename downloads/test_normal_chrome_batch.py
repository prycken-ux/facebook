import contextlib,io,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from playwright.sync_api import sync_playwright
import fb_upload as upload
import normal_chrome_batch as normal


class NormalChromeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.profile=self.root/'profiles/fb02';self.profile.mkdir(parents=True)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry=dict(account='fb02',target='page01',type='page',name='Example',url='https://www.facebook.com/profile.php?id=1002')
        self.pw=MagicMock();self.browser=MagicMock();self.context=MagicMock();self.page=MagicMock()
        self.context.pages=[self.page];self.browser.contexts=[self.context];self.pw.chromium.connect_over_cdp.return_value=self.browser
        self.close=self.stack.enter_context(patch.object(normal,'close_selected_window'))
        self.stack.enter_context(patch.object(normal,'require_profile_free'))
        self.stack.enter_context(patch.object(normal,'find_chrome',return_value=Path('/chrome.exe')))
        self.stack.enter_context(patch.object(upload,'checkpoint'));self.stack.enter_context(patch.object(upload,'require_no_advanced_protection'))
        def popen(*args,**kwargs):
            (self.profile/'DevToolsActivePort').write_text('12345\n/devtools/browser/local-test-token\n')
            process=MagicMock();process.poll.return_value=None;return process
        self.popen=self.stack.enter_context(patch.object(normal.subprocess,'Popen',side_effect=popen))
    def test_same_normal_profile_and_flags_preserve_extensions_and_use_only_loopback_control(self):
        wrapper=normal.launch_normal(self.pw,self.entry)
        args=self.popen.call_args.args[0]
        self.assertIn('--user-data-dir='+str(self.profile),args);self.assertIn('--profile-directory=Default',args)
        self.assertIn('--remote-debugging-address=127.0.0.1',args);self.assertIn('--remote-debugging-port=0',args)
        self.assertFalse(any(v.startswith(('--disable-extensions','--proxy-server','--no-proxy-server','--no-sandbox')) for v in args))
        self.assertTrue(self.pw.chromium.connect_over_cdp.call_args.args[0].startswith('ws://127.0.0.1:'))
        wrapper.close();wrapper.close();self.close.assert_called_once_with('fb02')
        self.browser.new_browser_cdp_session.return_value.send.assert_called_once_with('Browser.close')
    def test_warmup_retries_only_read_navigation_and_rejects_other_account_scope(self):
        self.page.goto.side_effect=[RuntimeError('net::ERR_PROXY_CONNECTION_FAILED'),None]
        wrapper=normal.launch_normal(self.pw,self.entry);self.assertEqual(self.page.goto.call_count,2);wrapper.close()
        self.popen.reset_mock()
        with self.assertRaises(ValueError):normal.launch_normal(self.pw,dict(self.entry,account='fb03'))
        self.popen.assert_not_called()
    def test_invalid_endpoint_is_not_connected_and_cdp_errors_do_not_expose_debug_address(self):
        path=self.profile/'bad-endpoint';path.write_text('12345\nws://outside.example/private\n')
        with self.assertRaises(ValueError):normal.endpoint(path)
        self.pw.chromium.connect_over_cdp.side_effect=RuntimeError('private local-test-token address')
        with self.assertRaises(RuntimeError) as result:normal.launch_normal(self.pw,self.entry)
        self.assertNotIn('local-test-token',str(result.exception));self.close.assert_called_once_with('fb02')
    def test_launcher_rejects_pairs_and_owners_outside_the_frozen_batch(self):
        launch=normal.launcher_for_jobs([dict(self.entry),dict(account='fb10',target='page02',url='https://www.facebook.com/profile.php?id=1010')])
        wrapper=MagicMock()
        with patch.object(normal,'launch_normal',return_value=wrapper) as native,patch.object(normal.local_files,'authorize') as authorize:
            self.assertIs(launch(None,self.entry),wrapper)
            authorize.assert_called_once()
            with self.assertRaises(ValueError):launch(None,dict(self.entry,account='fb03'))
            with self.assertRaises(ValueError):launch(None,dict(self.entry,url='https://www.facebook.com/profile.php?id=9999'))
            self.assertEqual(native.call_count,1)


class RealLocalCdpTests(unittest.TestCase):
    def test_connect_control_and_graceful_close_work_with_a_real_local_browser(self):
        with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
            fixture=pw.chromium.launch_persistent_context(tmp,executable_path='/usr/bin/chromium',headless=True,
                args=['--remote-debugging-address=127.0.0.1','--remote-debugging-port=0'])
            browser=pw.chromium.connect_over_cdp(normal.endpoint(Path(tmp)/'DevToolsActivePort'))
            wrapper=normal.NormalContext(browser,browser.contexts[0],'fb02');page=wrapper.new_page()
            page.set_content('<h1>Original profile session</h1>');self.assertEqual(page.locator('h1').inner_text(),'Original profile session')
            with patch.object(normal,'close_selected_window') as close:wrapper.close()
            self.assertFalse(browser.is_connected());close.assert_called_once_with('fb02')
