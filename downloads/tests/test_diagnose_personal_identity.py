import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright, expect as real_expect

import diagnose_personal_identity as diag
import fb_upload as upload


def quick_expect(locator):
    assertion = real_expect(locator)
    class Quick:
        def __getattr__(self, name):
            method = getattr(assertion, name)
            return lambda *args, **kwargs: method(*args, **dict(kwargs, timeout=250))
    return Quick()


class DiagnosticBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def run_case(self, bodies, person='12345', actor=None, kind='personal'):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'logs').mkdir()
            target = 'personal' if kind == 'personal' else 'page01'
            entry = dict(account='fb20', target=target, type=kind,
                         workflow='personal_recording_v1' if kind == 'personal' else 'page_flow_configured',
                         name='Example Person', url='https://www.facebook.com/profile.php?id=12345')
            context = self.browser.new_context()
            cookies = [dict(name='c_user', value=person, domain='.facebook.com', path='/')]
            if actor:
                cookies.append(dict(name='i_user', value=actor, domain='.facebook.com', path='/'))
            context.add_cookies(cookies)
            requests = []
            def route(request):
                requests.append(request.request.url)
                request.fulfill(status=200, content_type='text/html', body=bodies[min(len(requests)-1, len(bodies)-1)])
            context.route('https://www.facebook.com/**', route)
            sentinel = root / 'publish_state.json'
            sentinel.write_bytes(b'untouched publication ledger')
            wait_name = upload.wait_profile_name
            check_page = upload.ensure_page_identity
            with patch.object(diag, 'ROOT', root), patch.object(upload, 'ROOT', root), \
                 patch.object(upload, 'launch_context', return_value=context), \
                 patch.object(upload, 'wait_profile_name', side_effect=lambda p, e, **kw: wait_name(p, e, timeout_ms=min(kw.get('timeout_ms', 300), 300))), \
                 patch.object(upload, 'ensure_page_identity', side_effect=lambda p, e: check_page(p, e, timeout_ms=500)), \
                 patch('playwright.sync_api.expect', side_effect=quick_expect), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = diag.inspect_entry(self.playwright, entry, root / 'capture', True, 100)
            files = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(files['publish_state.json'], b'untouched publication ledger')
            self.assertFalse(context.pages)
            return result, requests, files

    def test_blank_shell_refreshes_once_then_real_identity_passes(self):
        result, requests, files = self.run_case(['<header>Facebook</header>', '<h1>Example Person</h1>'])
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(len(requests), 2)
        self.assertIn('capture/before-refresh.png', files)
        self.assertIn('capture/passed.png', files)
        self.assertIn('logs/identity-fb20-personal.json', files)

    def test_loaded_profile_does_not_refresh(self):
        result, requests, files = self.run_case(['<h1>Example Person</h1>'])
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(len(requests), 1)
        self.assertNotIn('capture/before-refresh.png', files)

    def test_refresh_cannot_bypass_wrong_account_or_page_actor(self):
        for person, actor in [('99999', None), ('12345', '88888')]:
            with self.subTest(person=person, actor=actor):
                result, requests, files = self.run_case(['<header>Facebook</header>', '<h1>Example Person</h1>'], person, actor)
                self.assertEqual(result['result'], 'CHECK_REQUIRED')
                self.assertNotIn('logs/identity-fb20-personal.json', files)
                self.assertIn('capture/failed.png', files)

    def test_permanent_blank_is_bounded_and_saves_failure(self):
        result, requests, files = self.run_case(['<header>Facebook</header>'])
        self.assertEqual(result['result'], 'CHECK_REQUIRED')
        self.assertEqual(len(requests), 2)
        self.assertIn('capture/failed.json', files)
        self.assertNotIn('logs/identity-fb20-personal.json', files)
        self.assertLess(len(result['error']), 501)

    def test_page_actor_proof_is_saved_under_page_target(self):
        result, requests, files = self.run_case(['<h1>Example Person</h1>'], person='99999', actor='12345', kind='page')
        self.assertEqual(result['result'], 'PASS')
        proof = json.loads(files['logs/identity-fb20-page01.json'])
        self.assertEqual(proof['method'], 'page_actor_id_match')
        self.assertNotIn('logs/identity-fb20-personal.json', files)

    def test_other_active_page_is_not_accepted(self):
        result, requests, files = self.run_case(['<h1>Example Person</h1>'], person='99999', actor='77777', kind='page')
        self.assertEqual(result['result'], 'CHECK_REQUIRED')
        self.assertNotIn('logs/identity-fb20-page01.json', files)

    def test_page_switch_now_uses_existing_live_identity_rules(self):
        html = '''<h1>Example Person</h1><button onclick="document.cookie='i_user=12345; domain=.facebook.com; path=/'; this.remove()">Switch Now</button>'''
        result, requests, files = self.run_case([html], person='99999', actor='77777', kind='page')
        self.assertEqual(result['result'], 'PASS')
        self.assertTrue(json.loads(files['logs/identity-fb20-page01.json'])['switched'])


class DiagnosticProcessTests(unittest.TestCase):
    def test_explicit_targets_do_not_expand_to_other_pages_or_accounts(self):
        self.assertEqual(diag.parse_target_pairs('fb10/page02,fb22/personal'),
                         [('fb10', 'page02'), ('fb22', 'personal')])
        for value in ('fb10/page02,fb10/page02', 'fb10/../page02', 'fb10', 'fb00/page01', 'fb10/page02,'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                diag.parse_target_pairs(value)

    def test_close_is_scoped_graceful_and_rechecks_freedom(self):
        with patch.object(diag.sys, 'platform', 'win32'), \
             patch.object(diag.subprocess, 'run', return_value=MagicMock(returncode=0)) as run, \
             patch.object(diag, 'require_profile_free') as guard:
            diag.close_selected_window('fb14')
        self.assertEqual(json.loads(run.call_args.kwargs['input']), {'profile': str(diag.ROOT / 'profiles/fb14')})
        self.assertIn('OrdinalIgnoreCase', diag.CLOSE_WINDOWS)
        self.assertIn('CloseMainWindow()', diag.CLOSE_WINDOWS)
        self.assertNotIn('Stop-Process', diag.CLOSE_WINDOWS)
        self.assertNotIn('taskkill', diag.CLOSE_WINDOWS)
        self.assertFalse(run.call_args.kwargs.get('shell', False))
        guard.assert_called_once_with(diag.ROOT / 'profiles/fb14', 'fb14')

    def test_unclosed_background_process_is_not_forced(self):
        with patch.object(diag.sys, 'platform', 'win32'), \
             patch.object(diag.subprocess, 'run', return_value=MagicMock(returncode=0)) as run, \
             patch.object(diag, 'require_profile_free', side_effect=RuntimeError('busy')) as guard, \
             patch.object(diag.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                diag.close_selected_window('fb14')
        self.assertEqual(guard.call_count, 10)
        self.assertEqual(run.call_count, 1)

    def test_url_metadata_discards_tracking_credentials_and_fragments(self):
        self.assertEqual(diag.safe_url('https://user:private@www.facebook.com/profile.php?id=123&token=private#private'),
                         'https://www.facebook.com/profile.php?id=123')

    def test_missing_profile_preflight_never_recreates_it(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(diag, 'ROOT', Path(temp)):
            config = dict(targets=[dict(account='fb14', target='personal', type='personal', name='Person',
                url='https://www.facebook.com/profile.php?id=12345', workflow='personal_recording_v1')])
            with patch.object(upload, 'read_json', return_value=config):
                with self.assertRaisesRegex(ValueError, '缺少原浏览器资料'):
                    diag.selected_entries(['fb14'])
            self.assertFalse((Path(temp) / 'profiles').exists())

    def test_twenty_target_scope_preserves_partial_registration(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(diag, 'ROOT', Path(temp)):
            missing = {('fb16', 'personal'), ('fb17', 'personal'), ('fb18', 'personal'),
                       ('fb21', 'personal'), ('fb10', 'page10')}
            rows = []
            for n, (account, target) in enumerate(diag.NEW_ONBOARDING):
                if (account, target) in missing:
                    continue
                (Path(temp) / 'profiles' / account).mkdir(parents=True, exist_ok=True)
                personal = target == 'personal'
                rows.append(dict(account=account, target=target, type='personal' if personal else 'page',
                    name='Person ' + str(n), url='https://www.facebook.com/profile.php?id=' + str(10000+n),
                    workflow='personal_recording_v1' if personal else 'page_flow_configured', enabled=False))
            config = dict(targets=rows)
            original = json.dumps(config, sort_keys=True)
            with patch.object(upload, 'read_json', return_value=config):
                selected, absent = diag.select_pairs(diag.NEW_ONBOARDING, allow_missing=True)
            self.assertEqual(len(selected), 15)
            self.assertEqual({(r['account'], r['target']) for r in absent}, missing)
            self.assertEqual(json.dumps(config, sort_keys=True), original)
            self.assertFalse((Path(temp) / 'profiles/fb16').exists())

    def test_duplicate_url_or_target_refuses_before_browser_launch(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(diag, 'ROOT', Path(temp)):
            row = dict(account='fb14', target='personal', type='personal', name='Person',
                url='https://www.facebook.com/profile.php?id=12345', workflow='personal_recording_v1')
            (Path(temp) / 'profiles/fb14').mkdir(parents=True)
            for rows in ([row, dict(row)], [row, dict(row, account='fb15')]):
                with self.subTest(rows=rows), patch.object(upload, 'read_json', return_value=dict(targets=rows)):
                    with self.assertRaises(ValueError):
                        diag.select_pairs([('fb14','personal'), ('fb15','personal')])


if __name__ == '__main__':
    unittest.main()
