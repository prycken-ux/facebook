import contextlib,io,sys,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import start_nov02_comment_backfill_20261103 as start


class CommentBackfillEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'upload_config.json').write_bytes(b'unchanged')
        self.stack=contextlib.ExitStack();self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()));self.stack.enter_context(patch.object(sys,'platform','win32'))
        clock=self.stack.enter_context(patch.object(start,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,3,5,tzinfo=timezone.utc)
        self.runner=b"print('only comments')\n";self.installer=b"def install(root):\n (root/'installer-called').write_text('yes')\n";self.recovery=b"def recover_locks(root):\n (root/'recovery-called').write_text('yes')\n"
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def test_current_install_starts_only_fresh_comments_interpreter(self):
        with patch.object(start,'download_verified',side_effect=[self.runner,self.installer,self.recovery]),patch.object(start.subprocess,'run',side_effect=[SimpleNamespace(returncode=0),SimpleNamespace(returncode=3)]) as run:
            self.assertEqual(start.start(self.root),3)
        self.assertFalse((self.root/'installer-called').exists());self.assertTrue((self.root/'recovery-called').exists());self.assertEqual(run.call_args.kwargs['input'],self.runner)
        self.assertNotIn('publish_new_with_comments.py',run.call_args.args[0]);self.assertEqual((self.root/'upload_config.json').read_bytes(),b'unchanged')
    def test_old_install_updates_then_checks_before_comments(self):
        with patch.object(start,'download_verified',side_effect=[self.runner,self.installer,self.recovery]),patch.object(start.subprocess,'run',side_effect=[SimpleNamespace(returncode=10),SimpleNamespace(returncode=0),SimpleNamespace(returncode=0)]) as run:
            self.assertEqual(start.start(self.root),0)
        self.assertTrue((self.root/'installer-called').exists());self.assertEqual(run.call_count,3);self.assertEqual(run.call_args.kwargs['input'],self.runner)
    def test_failed_download_or_failed_fresh_check_never_starts_comments(self):
        with patch.object(start,'download_verified',side_effect=[self.runner,self.installer,RuntimeError('download failure')]),patch.object(start.subprocess,'run') as run:
            with self.assertRaises(RuntimeError):start.start(self.root)
        self.assertFalse((self.root/'recovery-called').exists());run.assert_not_called()
        with patch.object(start,'download_verified',side_effect=[self.runner,self.installer,self.recovery]),patch.object(start.subprocess,'run',side_effect=[SimpleNamespace(returncode=10),SimpleNamespace(returncode=10)]) as run:
            with self.assertRaises(RuntimeError):start.start(self.root)
        self.assertEqual(run.call_count,2);self.assertTrue(all('input' not in call.kwargs for call in run.call_args_list))
