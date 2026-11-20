import subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import owned_chrome_cleanup as cleanup
import patch_owned_chrome_cleanup_20261120 as patcher
import test_normal_chrome_batch as fixture
import normal_chrome_batch as normal

class OwnedCleanupTests(unittest.TestCase):
    def test_only_owned_headless_process_is_terminated_if_cdp_close_does_not_exit(self):
        p=MagicMock();p.poll.return_value=None;p.wait.side_effect=[subprocess.TimeoutExpired('owned',5),0]
        close=MagicMock();cleanup.finish_owned_process(p,'background',close)
        p.terminate.assert_called_once_with();close.assert_not_called();self.assertEqual(p.wait.call_count,2)
    def test_exited_owned_process_not_terminated_or_other_window_closed(self):
        p=MagicMock();p.poll.return_value=0;close=MagicMock();cleanup.finish_owned_process(p,'background',close)
        p.terminate.assert_not_called();close.assert_not_called()
    def test_visible_process_uses_normal_close_never_terminate(self):
        p=MagicMock();p.poll.return_value=None;p.wait.side_effect=[subprocess.TimeoutExpired('owned',5),0];close=MagicMock()
        cleanup.finish_owned_process(p,'foreground',close);close.assert_called_once();p.terminate.assert_not_called()
    def test_real_owned_child_handle_releases_without_selecting_any_pid(self):
        p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        try:
            with patch.object(cleanup.subprocess,'TimeoutExpired',subprocess.TimeoutExpired):
                cleanup.finish_owned_process(p,'background',lambda:None)
            self.assertIsNotNone(p.poll())
        finally:
            if p.poll() is None:p.terminate();p.wait(timeout=5)
    def test_patch_preserves_args_and_is_idempotent(self):
        source=(Path(__file__).parent/'fixtures/normal_chrome_original_20261120.txt').read_text();updated=patcher.transform(source)
        self.assertEqual(patcher.transform(updated),updated)
        before=source[source.index('    args='):source.index("    print('使用原资料")]
        self.assertIn(before,updated);self.assertIn('require_profile_free(profile,account)',updated)
    def test_unknown_custom_launcher_is_not_overwritten(self):
        with self.assertRaises(ValueError):patcher.transform('class NormalContext:pass\ndef launch_normal(x):return None\n')

class LaunchErrorTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.NormalChromeTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
    def test_authorization_error_remains_primary_even_if_close_fails(self):
        wrapper=MagicMock();wrapper.close.side_effect=RuntimeError('secondary close error')
        launch=normal.launcher_for_jobs([dict(self.fx.entry)])
        with patch.object(normal,'launch_normal',return_value=wrapper),patch.object(normal.local_files,'authorize',side_effect=ValueError('primary authorization error')):
            with self.assertRaisesRegex(ValueError,'primary authorization error'):launch(None,self.fx.entry)

    def test_cleanup_exception_does_not_replace_original_cdp_error(self):
        self.fx.pw.chromium.connect_over_cdp.side_effect=RuntimeError('local CDP failed')
        with patch.object(normal,'close_selected_window',side_effect=RuntimeError('profile busy')),patch('owned_chrome_cleanup.finish_owned_process',side_effect=RuntimeError('cleanup profile busy')):
            with self.assertRaisesRegex(RuntimeError,'本机控制连接失败'):normal.launch_normal(self.fx.pw,self.fx.entry)
        logs=list((self.fx.root/'logs').glob('chrome-launch-*-error.txt'));self.assertEqual(len(logs),1)
        text=logs[0].read_text();self.assertIn('本机控制连接失败',text);self.assertIn('cleanup profile busy',text)
    def test_after_session_created_navigation_error_remains_primary(self):
        self.fx.page.goto.side_effect=RuntimeError('primary navigation failed')
        with patch('owned_chrome_cleanup.finish_owned_process',side_effect=RuntimeError('cleanup failed')):
            with self.assertRaisesRegex(RuntimeError,'primary navigation failed'):normal.launch_normal(self.fx.pw,self.fx.entry)
    def test_failed_new_headless_launch_never_closes_an_unrelated_window(self):
        self.fx.pw.chromium.connect_over_cdp.side_effect=RuntimeError('connect failed')
        with patch.object(normal.background,'mode',return_value='background'):
            with self.assertRaises(RuntimeError):normal.launch_normal(self.fx.pw,self.fx.entry)
        self.fx.close.assert_not_called()

if __name__=='__main__':unittest.main()
