import ctypes,io,os,signal,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import publish_eligible60_real_20261123 as driver

class InterruptIsolationTests(unittest.TestCase):
    def test_manual_console_entry_keeps_normal_ctrl_c_behavior(self):
        with patch.dict(os.environ,{},clear=True),patch.object(signal,'signal') as handler:
            self.assertIsNone(driver.isolate_background_interrupts());handler.assert_not_called()
    def test_background_worker_ignores_console_ctrl_c_and_ctrl_break(self):
        kernel=MagicMock();kernel.SetConsoleCtrlHandler.return_value=1
        with patch.dict(os.environ,{'FB_PUBLISH_ISOLATED_BACKGROUND':'1'}),patch.object(driver.sys,'platform','win32'), \
             patch.object(signal,'signal') as handler,patch.object(signal,'SIGBREAK',21,create=True),patch.object(ctypes,'WinDLL',return_value=kernel,create=True):
            self.assertEqual(driver.isolate_background_interrupts(),'console_interrupts_ignored')
            handler.assert_any_call(signal.SIGINT,signal.SIG_IGN);handler.assert_any_call(21,signal.SIG_IGN)
        kernel.SetConsoleCtrlHandler.assert_called_once_with(None,True)
    def test_detached_process_with_no_console_is_accepted(self):
        kernel=MagicMock();kernel.SetConsoleCtrlHandler.return_value=0
        with patch.dict(os.environ,{'FB_PUBLISH_ISOLATED_BACKGROUND':'1'}),patch.object(driver.sys,'platform','win32'), \
             patch.object(signal,'signal'),patch.object(ctypes,'WinDLL',return_value=kernel,create=True),patch.object(ctypes,'get_last_error',return_value=6,create=True):
            self.assertEqual(driver.isolate_background_interrupts(),'detached_without_console')
    def test_unknown_windows_guard_error_stops_before_publishing(self):
        kernel=MagicMock();kernel.SetConsoleCtrlHandler.return_value=0
        with patch.dict(os.environ,{'FB_PUBLISH_ISOLATED_BACKGROUND':'1'}),patch.object(driver.sys,'platform','win32'), \
             patch.object(signal,'signal'),patch.object(ctypes,'WinDLL',return_value=kernel,create=True),patch.object(ctypes,'get_last_error',return_value=5,create=True):
            with self.assertRaisesRegex(RuntimeError,'Windows错误：5'):driver.isolate_background_interrupts()
    def test_file_only_background_logs_do_not_write_parent_console_or_pipe(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'logs').mkdir();out=io.StringIO();err=io.StringIO()
            def execute(_):
                print('progress marker');print('diagnostic marker',file=driver.sys.stderr);return 3
            with patch.dict(os.environ,{'FB_PUBLISH_FILE_LOG_ONLY':'1'}),patch.object(driver.sys,'platform','win32'), \
                 patch.object(driver.sys,'stdout',out),patch.object(driver.sys,'stderr',err),patch.object(driver,'execute',side_effect=execute):
                self.assertEqual(driver.main(root),3)
            self.assertEqual(out.getvalue(),'');self.assertEqual(err.getvalue(),'')
            saved=(root/driver.LOG).read_text();self.assertIn('progress marker',saved);self.assertIn('diagnostic marker',saved)

if __name__=='__main__':unittest.main()
