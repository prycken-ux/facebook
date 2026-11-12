import contextlib
import io
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import fb_upload as upload
import recovery_numeric_identity as identity
from test_page_profile_switch import HTML


class NumericRecoveryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.context.add_cookies([dict(name='c_user', value='1003', domain='.facebook.com', path='/'),
                                 dict(name='i_user', value='1002', domain='.facebook.com', path='/')])
        self.html = HTML.replace('<h1>Example Page</h1>', '<span>Example Page</span>')
        self.context.route('https://www.facebook.com/**', lambda route: route.fulfill(content_type='text/html', body=self.html))
        self.page = self.context.new_page()
        self.entry = dict(account='fb09', target='page01', type='page', name='Example Page', url='https://www.facebook.com/profile.php?id=1001')
        self.silent = contextlib.redirect_stdout(io.StringIO())
        self.silent.__enter__()
        self.addCleanup(self.silent.__exit__, None, None, None)

    def test_missing_heading_still_switches_exact_page_and_never_touches_feed_button(self):
        self.page.goto(self.entry['url'])
        self.assertEqual(upload.profile_name_candidates(self.page, self.entry), [])
        proof = identity.ensure(self.page, self.entry, timeout_ms=1000, interactive=False)
        self.assertEqual(proof['method'], 'page_actor_id_match')
        self.assertTrue(upload.page_actor_matches(self.page, self.entry))
        self.assertEqual(self.page.evaluate("Number(localStorage.getItem('pick'))"), 1)
        self.assertEqual(self.page.evaluate("Number(localStorage.getItem('post'))"), 0)
        upload.recheck_publish_identity(self.page, self.entry, proof)

    def test_matching_numeric_actor_needs_no_heading_or_picker(self):
        self.page.goto(self.entry['url'])
        self.page.evaluate("document.cookie='i_user=1001; domain=.facebook.com; path=/'")
        self.assertFalse(identity.ensure(self.page, self.entry, interactive=False)['switched'])
        self.assertIsNone(self.page.evaluate("localStorage.getItem('pick')"))

    def test_enter_cannot_override_wrong_numeric_actor_and_s_skips_before_media(self):
        self.html = self.html.replace("pick('1001')", "pick('1002')")
        self.page.goto(self.entry['url'])
        with patch('builtins.input', side_effect=['', 'S']) as console:
            with self.assertRaisesRegex(RuntimeError, '用户跳过'):
                identity.ensure(self.page, self.entry, timeout_ms=300)
        self.assertEqual(console.call_count, 2)
        self.assertEqual(self.page.evaluate("Number(localStorage.getItem('post'))"), 0)

    def test_switching_login_owner_is_rejected_before_manual_override(self):
        self.html = self.html.replace("bump('pick');", "bump('pick');document.cookie='c_user=9999; domain=.facebook.com; path=/';")
        self.page.goto(self.entry['url'])
        with patch('builtins.input', side_effect=AssertionError('must not allow manual override')):
            with self.assertRaisesRegex(RuntimeError, '登录者变化'):
                identity.ensure(self.page, self.entry, timeout_ms=1000)

    def test_personal_name_without_h1_uses_visible_metadata_and_owner_proof(self):
        self.entry.update(type='personal', target='personal', name='New Person', url='https://www.facebook.com/profile.php?id=1003')
        self.html = '<html><title>(2) New Person | Facebook</title><main><span>New Person</span></main></html>'
        self.context.clear_cookies(name='i_user')
        self.page.goto(self.entry['url'])
        self.assertEqual(identity.public_name(self.page), 'New Person')
        proof = identity.ensure(self.page, self.entry, interactive=False)
        self.assertEqual(proof['method'], 'personal_actor_id_match')
        upload.recheck_publish_identity(self.page, self.entry, proof)
        self.html = '<title>New Person | Facebook</title><article>New Person</article>'
        self.page.reload()
        self.assertIsNone(identity.public_name(self.page))

    def test_personal_wrong_owner_or_route_cannot_pass_numeric_gate(self):
        self.entry.update(type='personal', target='personal')
        self.context.clear_cookies(name='i_user')
        self.page.goto(self.entry['url'])
        with self.assertRaisesRegex(RuntimeError, '个人账号与目标'):
            identity.ensure(self.page, self.entry, interactive=False)
        self.page.goto('https://www.facebook.com/profile.php?id=9999')
        with self.assertRaisesRegex(RuntimeError, '网址与目标'):
            identity.ensure(self.page, self.entry, interactive=False)

    def test_scoped_recheck_blocks_owner_change_after_media_and_restores_originals(self):
        self.page.goto(self.entry['url'])
        original = upload.ensure_identity
        original_recheck = upload.recheck_publish_identity
        with patch.object(upload, 'read_json', return_value={'targets':[self.entry]}):
            with identity.scoped({('fb09','page01')}):
                proof = upload.ensure_identity(self.page, self.entry)
                self.page.evaluate("document.cookie='c_user=9999; domain=.facebook.com; path=/'")
                with self.assertRaisesRegex(RuntimeError, '登录者变化'):
                    upload.recheck_publish_identity(self.page, self.entry, proof)
        self.assertIs(upload.ensure_identity, original)
        self.assertIs(upload.recheck_publish_identity, original_recheck)


if __name__ == '__main__':
    unittest.main()
