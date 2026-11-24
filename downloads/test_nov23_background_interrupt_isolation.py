import ctypes,io,json,os,signal,tempfile,unittest
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
    def test_worker_receipt_records_real_pid_and_preserves_other_launch_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'logs').mkdir();shared=root/'logs/eligible60-2026-11-23-queue.json'
            shared.write_text('{"launch_id":"older","phase":"running","pid":123}')
            previous=shared.read_bytes();token='a'*32
            with patch.dict(os.environ,{'FB_PUBLISH_LAUNCH_ID':token}):
                driver.worker_status(root,'preparing','preparing')
                ack=json.loads((root/'logs'/('eligible60-2026-11-23-worker-'+token+'.json')).read_text())
                self.assertEqual(ack['pid'],os.getpid());self.assertEqual(ack['launch_id'],token);self.assertEqual(shared.read_bytes(),previous)
                driver.worker_status(root,'running','running')
                self.assertEqual(json.loads(shared.read_text())['launch_id'],token)
                driver.worker_status(root,'review_required','done')
                self.assertEqual(json.loads(shared.read_text())['phase'],'review_required')
    def test_failed_second_launch_does_not_overwrite_active_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'logs').mkdir();shared=root/'logs/eligible60-2026-11-23-queue.json'
            shared.write_text('{"launch_id":"older","phase":"running","pid":123}');before=shared.read_bytes()
            with patch.dict(os.environ,{'FB_PUBLISH_LAUNCH_ID':'b'*32}):driver.worker_status(root,'failed','another worker exists')
            self.assertEqual(shared.read_bytes(),before)

if __name__=='__main__':unittest.main()
