import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import start_new_batch_20261102 as runner


class SingleLineNewBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'upload_config.json').write_bytes(b'preserve-config')
        self.recovery = b"def recover_locks(root):\n (root/'lock-check-called').write_text('checked')\n"
        self.installer = b"from pathlib import Path\nimport sys\n(Path(sys.argv[1])/'installer-called').write_text('installed')\n"
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(sys, 'platform', 'win32'))
        self.stack.enter_context(patch.object(sys, 'argv', ['bootstrap', str(self.root)]))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def test_install_then_fresh_verify_and_exact_authorized_new_batch_runner(self):
        for code in (0, 3):
            with patch.object(runner, 'download_verified', side_effect=[self.recovery, self.installer]), patch.object(runner.subprocess, 'run', side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=code)]) as execute:
                self.assertEqual(runner.run(self.root), code)
            self.assertTrue((self.root / 'lock-check-called').exists())
            self.assertTrue((self.root / 'installer-called').exists())
            self.assertEqual(execute.call_args_list[0].args[0][1], '-c')
            self.assertEqual(execute.call_args_list[1].args[0], [sys.executable, str(self.root / 'publish_new_with_comments.py'), '--date', '2026-11-02', '--real-footage'])
            self.assertEqual((self.root / 'upload_config.json').read_bytes(), b'preserve-config')

    def test_all_downloads_finish_before_any_mutation(self):
        with patch.object(runner, 'download_verified', side_effect=[self.recovery, RuntimeError('download failed')]), patch.object(runner.subprocess, 'run') as execute:
            with self.assertRaises(RuntimeError):
                runner.run(self.root)
        self.assertFalse((self.root / 'lock-check-called').exists())
        self.assertFalse((self.root / 'installer-called').exists())
        execute.assert_not_called()

    def test_failed_fresh_version_check_never_starts_comments(self):
        with patch.object(runner, 'download_verified', side_effect=[self.recovery, self.installer]), patch.object(runner.subprocess, 'run', side_effect=runner.subprocess.CalledProcessError(1, 'verify')) as execute:
            with self.assertRaises(runner.subprocess.CalledProcessError):
                runner.run(self.root)
        self.assertEqual(execute.call_count, 1)

    def test_unverified_download_never_returns_executable_bytes(self):
        # Restore platform for Python's TLS implementation in this Linux test.
        with patch.object(sys, 'platform', 'linux'), patch.object(runner.urllib.request, 'urlopen', side_effect=lambda *a, **k: contextlib.closing(io.BytesIO(b'print("untrusted")'))):
            with self.assertRaisesRegex(RuntimeError, 'Verified download failed'):
                runner.download_verified('commit', 'name.py', '0' * 64)


if __name__ == '__main__':
    unittest.main()
