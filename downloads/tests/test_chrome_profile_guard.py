import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import chrome_profile_guard as guard
import fb_upload as upload


class ProfileGuardTests(unittest.TestCase):
    def result(self, payload, code=0):
        return MagicMock(returncode=code, stdout=json.dumps(payload).encode(), stderr=b'private data not echoed')

    def test_exact_profile_payload_and_no_kill_or_raw_command_output(self):
        profile = Path('/fixture/profiles/fb10')
        with patch.object(guard.sys, 'platform', 'win32'), \
             patch.object(guard.subprocess, 'run', return_value=self.result([dict(pid=1234, name='chrome.exe')])) as run:
            with self.assertRaisesRegex(RuntimeError, 'fb10.*1234') as error:
                guard.require_profile_free(profile, 'fb10')
        self.assertNotIn('private', str(error.exception))
        args = run.call_args
        self.assertEqual(json.loads(args.kwargs['input']), {'profile': str(profile)})
        self.assertFalse(args.kwargs.get('shell', False))
        self.assertNotIn('Stop-Process', guard.QUERY)
        self.assertNotIn('taskkill', guard.QUERY)
        self.assertIn('OrdinalIgnoreCase', guard.QUERY)

    def test_empty_owner_result_allows_launch(self):
        with patch.object(guard.sys, 'platform', 'win32'), \
             patch.object(guard.subprocess, 'run', return_value=self.result([])):
            guard.require_profile_free(Path('/fixture'), 'fb10')

    def test_invalid_or_failed_query_does_not_leak_stderr_or_claim_profile_free(self):
        for result in (self.result([], 1), self.result({'pid': 3}), self.result([dict(pid=1, name='chrome.exe', CommandLine='secret')]),
                       self.result([dict(pid=True, name='chrome.exe')])):
            with self.subTest(result=result), patch.object(guard.sys, 'platform', 'win32'), \
                 patch.object(guard.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(RuntimeError, '无法核对') as error:
                    guard.profile_owners(Path('/fixture'))
                self.assertNotIn('private', str(error.exception))
                self.assertNotIn('secret', str(error.exception))

    def test_timeout_is_bounded_and_non_windows_does_not_spawn_powershell(self):
        with patch.object(guard.sys, 'platform', 'win32'), \
             patch.object(guard.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell', 20)):
            with self.assertRaisesRegex(RuntimeError, '无法核对'):
                guard.profile_owners(Path('/fixture'))
        with patch.object(guard.sys, 'platform', 'linux'), patch.object(guard.subprocess, 'run') as run:
            self.assertEqual(guard.profile_owners(Path('/fixture')), [])
        run.assert_not_called()

    def test_uploader_checks_profile_before_launch_and_keeps_existing_sandbox(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(upload, 'ROOT', Path(folder)):
            (Path(folder) / 'profiles/fb10').mkdir(parents=True)
            playwright = MagicMock()
            entry = dict(account='fb10', target='page01')
            with patch.object(guard, 'require_profile_free', side_effect=RuntimeError('profile busy')):
                with self.assertRaisesRegex(RuntimeError, 'profile busy'):
                    upload.launch_context(playwright, entry)
            playwright.chromium.launch_persistent_context.assert_not_called()
            with patch.object(guard, 'require_profile_free') as check:
                upload.launch_context(playwright, entry)
            check.assert_called_once_with(Path(folder) / 'profiles/fb10', 'fb10')
            self.assertTrue(playwright.chromium.launch_persistent_context.call_args.kwargs['chromium_sandbox'])


    def test_launch_failure_saves_raw_log_and_prints_only_brief_error(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(upload, 'ROOT', Path(folder)):
            (Path(folder) / 'profiles/fb10').mkdir(parents=True)
            playwright = MagicMock()
            playwright.chromium.launch_persistent_context.side_effect = RuntimeError('Browser closed\nfull browser command line detail')
            with patch.object(guard, 'require_profile_free'):
                with self.assertRaisesRegex(RuntimeError, '尚未选择视频') as error:
                    upload.launch_context(playwright, dict(account='fb10', target='page01'))
            self.assertNotIn('full browser command line detail', str(error.exception))
            logs = list((Path(folder) / 'logs').glob('browser-start-fb10-*.txt'))
            self.assertEqual(len(logs), 1)
            self.assertIn('full browser command line detail', logs[0].read_text())

    def test_cookie_setup_failure_closes_partial_browser_context(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(upload, 'ROOT', Path(folder)):
            (Path(folder) / 'profiles/fb10').mkdir(parents=True)
            playwright = MagicMock()
            context = playwright.chromium.launch_persistent_context.return_value
            context.add_cookies.side_effect = RuntimeError('context setup failed')
            with patch.object(guard, 'require_profile_free'):
                with self.assertRaisesRegex(RuntimeError, '初始化失败'):
                    upload.launch_context(playwright, dict(account='fb10', target='page01'))
            context.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
