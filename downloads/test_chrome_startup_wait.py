import tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import chrome_startup_wait as wait
import patch_chrome_startup_wait_20261120 as patcher

class StartupWaitTests(unittest.TestCase):
    def test_launcher_exit_before_endpoint_does_not_abort_valid_relaunch(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'DevToolsActivePort';process=MagicMock();process.poll.return_value=0
            def tick(_):path.write_text('valid')
            with patch.object(wait.time,'sleep',side_effect=tick):
                self.assertEqual(wait.wait_endpoint(process,path,lambda p:p.read_text()),'valid')
    def test_missing_endpoint_remains_failure_and_includes_exit_code_and_diagnostic(self):
        process=MagicMock();process.poll.return_value=7;process._fb_startup_log='local-diagnostic.txt'
        with tempfile.TemporaryDirectory() as folder,patch.object(wait.time,'monotonic',side_effect=[0,31]):
            with self.assertRaisesRegex(RuntimeError,'退出码 7.*local-diagnostic.txt'):
                wait.wait_endpoint(process,Path(folder)/'missing',lambda p:None)
    def test_partial_endpoint_is_retried_without_connecting_invalid_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'port';path.write_text('partial')
            def validate(p):
                if p.read_text()!='complete':raise ValueError('incomplete')
                return 'endpoint'
            with patch.object(wait.time,'sleep',side_effect=lambda _:path.write_text('complete')):
                self.assertEqual(wait.wait_endpoint(MagicMock(),path,validate),'endpoint')
    def test_patch_preserves_profile_proxy_background_and_batch_authorization(self):
        old=(Path(__file__).parent/'fixtures/normal_chrome_original_20261120.txt').read_text();new=patcher.transform(old)
        self.assertEqual(patcher.transform(new),new)
        for text in ('require_profile_free(profile,account)','--remote-debugging-address=127.0.0.1','local_files.authorize','*background.arguments(run_mode)'):
            self.assertIn(text,new)
        self.assertNotIn('if process.poll() is not None:raise RuntimeError',new)
    def test_unknown_launcher_rejected(self):
        with self.assertRaises(ValueError):patcher.transform('x=1')

if __name__=='__main__':unittest.main()
