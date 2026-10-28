"""Exercise the supplied Your profiles & Pages picker flow in local Chromium."""
import contextlib
import io
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

import fb_upload as upload
import page_profile_switch as switcher


HTML = '''<html lang="en-US"><header role="banner">
<button aria-label="Your profile" onclick="bump('account');document.querySelector('#account').hidden=false">Avatar</button></header>
<main><section><h1>Example Page</h1><button>Follow</button></section><article>
<button onclick="bump('post')">See all profiles</button><span>Example Page</span></article></main>
<div id="account" role="menu" hidden><button onclick="bump('seeall');document.querySelector('#account').hidden=true;
document.querySelector('#picker').hidden=false">See all profiles</button></div>
<div id="picker" role="dialog" aria-label="Your profiles &amp; Pages" hidden><h2>Your profiles &amp; Pages</h2>
<input placeholder="Search profiles and Pages" oninput="search(this.value)">
<div id="target" role="button" onclick="pick('1001')"><span>Example Page</span><span>1 notification</span></div>
<div role="button" onclick="pick('1002')"><span>Another Page</span></div></div>
<script>function bump(key){localStorage.setItem(key,String(Number(localStorage.getItem(key)||0)+1))}
function pick(id){bump('pick');document.cookie='i_user='+id+'; domain=.facebook.com; path=/';
document.querySelector('#picker').hidden=true;}
function search(value){if(value==='Example Page')document.querySelector('#target').hidden=false;}
</script></html>'''


class ProfilePickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.context.add_cookies([dict(name='c_user', value='1003', domain='.facebook.com', path='/'),
                                 dict(name='i_user', value='1002', domain='.facebook.com', path='/')])
        self.context.route('https://www.facebook.com/**', self.route)
        self.page = self.context.new_page()
        self.html = HTML
        self.entry = dict(account='fb10', target='page02', type='page', name='Example Page',
            url='https://www.facebook.com/profile.php?id=1001')
        self.silent = contextlib.redirect_stdout(io.StringIO())
        self.silent.__enter__()

    def route(self, route):
        route.fulfill(content_type='text/html', body=self.html)

    def visit(self):
        self.page.goto(self.entry['url'])

    def tearDown(self):
        self.silent.__exit__(None, None, None)
        self.context.close()

    def count(self, name):
        return self.page.evaluate('(key)=>Number(localStorage.getItem(key)||0)', name)

    def test_avatar_menu_picker_selects_exact_name_and_verifies_numeric_id(self):
        self.visit()
        self.assertTrue(switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=1500))
        self.assertTrue(upload.page_actor_matches(self.page, self.entry))
        self.assertEqual(self.count('account'), 1)
        self.assertEqual(self.count('seeall'), 1)
        self.assertEqual(self.count('pick'), 1)
        self.assertEqual(self.count('post'), 0)

    def test_core_uses_picker_for_different_page_actor(self):
        self.visit()
        proof = upload.ensure_page_identity(self.page, self.entry, timeout_ms=2500, picker_delay_ms=0)
        self.assertEqual(proof['method'], 'page_actor_id_match')
        self.assertEqual(proof['switch_method'], 'profile_picker')
        self.assertTrue(proof['switched'])
        self.assertEqual(self.count('pick'), 1)

    def test_already_open_picker_is_not_toggled_closed(self):
        self.html += '<script>document.querySelector("#picker").hidden=false</script>'
        self.visit()
        switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=1500)
        self.assertEqual(self.count('account'), 0)
        self.assertEqual(self.count('seeall'), 0)
        self.assertEqual(self.count('pick'), 1)

    def test_already_open_account_menu_is_not_toggled_closed(self):
        self.html += '<script>document.querySelector("#account").hidden=false</script>'
        self.visit()
        switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=1500)
        self.assertEqual(self.count('account'), 0)
        self.assertEqual(self.count('seeall'), 1)

    def test_hidden_target_is_found_via_only_picker_search(self):
        self.html = self.html.replace('id="target" role=', 'id="target" hidden role=')
        self.visit()
        switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=1500)
        self.assertEqual(self.count('pick'), 1)

    def test_duplicate_page_names_are_refused_without_selection(self):
        self.html = self.html.replace('<span>Another Page</span>', '<span>Example Page</span>')
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '目标公共主页名称存在多个'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=1500)
        self.assertEqual(self.count('pick'), 0)

    def test_same_display_name_switching_to_wrong_id_never_passes(self):
        self.html = self.html.replace('onclick="pick(\'1001\')"', 'onclick="pick(\'1002\')"')
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '切换超时'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=600)
        self.assertEqual(self.count('pick'), 1)
        self.assertFalse(switcher.login_marker(self.page) == '')

    def test_login_owner_change_during_selection_is_refused(self):
        self.html = self.html.replace("function pick(id){", "function pick(id){document.cookie='c_user=99999; domain=.facebook.com; path=/';")
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '登录者身份变化'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=1500)

    def test_missing_login_owner_is_refused_before_any_click(self):
        self.context.clear_cookies(name='c_user')
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '缺少唯一的登录者身份'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=1500)
        self.assertEqual(self.count('account'), 0)

    def test_missing_target_does_not_select_another_page_or_feed_name(self):
        self.html = self.html.replace('<span>Example Page</span><span>1 notification</span>', '<span>Other Page</span>')
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '未加载|切换超时'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=600)
        self.assertEqual(self.count('pick'), 0)
        self.assertEqual(self.count('post'), 0)

    def test_wrong_target_url_and_personal_entry_never_open_menu(self):
        self.visit()
        for changes in (dict(url='https://www.facebook.com/profile.php?id=1005'), dict(type='personal')):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                switcher.switch_page_from_picker(self.page, dict(self.entry, **changes), timeout_ms=500)
        self.assertEqual(self.count('account'), 0)

    def test_ambiguous_avatar_controls_are_refused(self):
        self.html = self.html.replace('</header>', '<button aria-label="Your profile">Another avatar</button></header>')
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '多个可见入口'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=600)
        self.assertEqual(self.count('account'), 0)

    def test_no_known_account_button_does_not_guess_an_image(self):
        self.html = self.html.replace('aria-label="Your profile"', 'aria-label="Unknown control"')
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '未加载|切换超时'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=600)
        self.assertEqual(self.count('account'), 0)
        self.assertEqual(self.count('post'), 0)

    def test_named_account_control_outside_banner_is_supported(self):
        self.html = self.html.replace('<header role="banner">', '<nav aria-label="Account controls">').replace('</header>', '</nav>')
        self.visit()
        switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=1500)
        self.assertEqual(self.count('account'), 1)
        self.assertEqual(self.count('pick'), 1)
        self.assertEqual(self.count('post'), 0)

    def recorded_account_header(self,aria_hidden=False):
        # Reconstructed from the supplied top-controls metadata; no account
        # names, URLs, screenshots or session data are committed as fixtures.
        header='''<div role="navigation" aria-label="Account Controls and Settings" %s>
          <div role="button" aria-label="Facebook menu" aria-haspopup="dialog" onclick="bump('unrelated')"></div>
          <div role="button" aria-label="Notifications" aria-haspopup="dialog" onclick="bump('notifications')"></div>
          <div role="button" aria-label="Account, your profile" aria-haspopup="dialog" aria-expanded="false"
               onclick="bump('account');document.querySelector('#account').hidden=false">
            <svg role="img" aria-label="Your profile"><image /></svg>
          </div></div>''' % ('aria-hidden="true"' if aria_hidden else '')
        start=self.html.index('<header')
        end=self.html.index('</header>')+len('</header>')
        self.html=self.html[:start]+header+self.html[end:]

    def test_recorded_account_comma_your_profile_switches_without_notification_click(self):
        self.recorded_account_header()
        self.visit()
        proof=upload.ensure_page_identity(self.page,self.entry,timeout_ms=2500,picker_delay_ms=0)
        self.assertEqual(proof['switch_method'],'profile_picker')
        self.assertEqual(proof['method'],'page_actor_id_match')
        self.assertEqual(self.count('account'),1)
        self.assertEqual(self.count('seeall'),1)
        self.assertEqual(self.count('pick'),1)
        self.assertEqual(self.count('notifications'),0)
        self.assertEqual(self.count('unrelated'),0)
        self.assertEqual(self.count('post'),0)

    def test_recorded_visible_avatar_with_missing_accessibility_role_uses_exact_attribute(self):
        self.recorded_account_header(aria_hidden=True)
        self.visit()
        self.assertEqual(self.page.get_by_role('button',name='Account, your profile',exact=True).count(),0)
        self.assertTrue(switcher.switch_page_from_picker(self.page,self.entry,timeout_ms=1500))
        self.assertEqual(self.count('account'),1)
        self.assertEqual(self.count('notifications'),0)
        self.assertEqual(self.count('post'),0)

    def test_recorded_attribute_fallback_refuses_two_visible_avatars(self):
        self.recorded_account_header(aria_hidden=True)
        self.html=self.html.replace('</svg>', '</svg><div role="button" aria-label="Account, your profile">Second avatar</div>')
        self.visit()
        with self.assertRaisesRegex(RuntimeError,'多个可见入口'):
            switcher.switch_page_from_picker(self.page,self.entry,timeout_ms=600)
        self.assertEqual(self.count('account'),0)
        self.assertEqual(self.count('pick'),0)

    def test_recorded_label_in_feed_cannot_substitute_for_missing_avatar(self):
        self.html=self.html.replace('aria-label="Your profile"','aria-label="Unknown control"').replace(
            '<article>', '<article aria-hidden="true"><div role="button" aria-label="Account, your profile" onclick="bump(\'post\')">Misleading button</div>')
        self.visit()
        with self.assertRaisesRegex(RuntimeError,'未加载|切换超时'):
            switcher.switch_page_from_picker(self.page,self.entry,timeout_ms=600)
        self.assertEqual(self.count('post'),0)

    def test_recorded_account_label_still_requires_exact_actor_and_same_login(self):
        self.recorded_account_header()
        self.html=self.html.replace('onclick="pick(\'1001\')"','onclick="pick(\'1002\')"')
        self.visit()
        with self.assertRaisesRegex(RuntimeError,'切换超时'):
            switcher.switch_page_from_picker(self.page,self.entry,timeout_ms=600)
        self.assertEqual(self.count('pick'),1)
        self.assertEqual(self.count('post'),0)

    def test_return_to_profile_uses_commit_and_actual_ui_when_domcontentloaded_is_blocked(self):
        self.recorded_account_header()
        self.html += '<script src="/blocked-page-script.js"></script>'
        blocked=[]
        self.context.route('**/blocked-page-script.js',lambda route:blocked.append(route))
        try:
            self.page.goto(self.entry['url'],wait_until='commit')
            self.page.get_by_role('heading',name=self.entry['name'],exact=True).wait_for()
            with patch.object(self.page,'goto',wraps=self.page.goto) as navigate:
                self.assertTrue(switcher.switch_page_from_picker(self.page,self.entry,timeout_ms=3000))
                navigate.assert_not_called()
            self.assertEqual(self.page.evaluate('document.readyState'),'loading')
            self.assertTrue(upload.page_actor_matches(self.page,self.entry))
            self.assertEqual(self.count('post'),0)
        finally:
            for route in blocked:
                route.fulfill(content_type='application/javascript',body='')
            self.page.wait_for_load_state('domcontentloaded')

    def test_switch_already_at_exact_target_never_reloads_even_if_goto_would_timeout(self):
        self.recorded_account_header()
        self.visit()
        with patch.object(self.page,'goto',side_effect=AssertionError('redundant navigation must not happen')) as navigate:
            self.assertTrue(switcher.switch_page_from_picker(self.page,self.entry,timeout_ms=1500))
        navigate.assert_not_called()
        self.assertEqual(self.count('pick'),1)
        self.assertEqual(self.count('post'),0)

    def test_switch_landing_on_home_returns_to_configured_page_once(self):
        self.recorded_account_header()
        self.html=self.html.replace("document.querySelector('#picker').hidden=true;}",
                                    "document.querySelector('#picker').hidden=true;location.href='/';}")
        self.visit()
        with patch.object(self.page,'goto',wraps=self.page.goto) as navigate:
            self.assertTrue(switcher.switch_page_from_picker(self.page,self.entry,timeout_ms=3000))
        self.assertEqual(navigate.call_count,1)
        self.assertEqual(navigate.call_args.kwargs['wait_until'],'commit')
        self.assertEqual(upload.target_key(self.page.url),upload.target_key(self.entry['url']))
        self.assertEqual(self.count('post'),0)

    def test_profile_ui_load_must_complete_even_after_correct_actor_switch(self):
        self.recorded_account_header()
        self.visit()
        with patch.object(upload,'wait_profile_name',side_effect=upload.ProfileNameNotReady('profile not loaded')):
            with self.assertRaisesRegex(upload.ProfileNameNotReady,'profile not loaded'):
                switcher.switch_page_from_picker(self.page,self.entry,timeout_ms=1500)
        self.assertEqual(self.count('post'),0)

    def test_owner_change_during_committed_profile_load_is_refused(self):
        self.recorded_account_header()
        self.visit()
        def loaded(*args,**kwargs):
            self.context.add_cookies([dict(name='c_user',value='9999',domain='.facebook.com',path='/')])
        with patch.object(upload,'wait_profile_name',side_effect=loaded):
            with self.assertRaisesRegex(RuntimeError,'内容加载后身份或网址变化'):
                switcher.switch_page_from_picker(self.page,self.entry,timeout_ms=1500)
        self.assertEqual(self.count('post'),0)

    def test_account_label_with_current_profile_name_is_supported(self):
        self.html = self.html.replace('aria-label="Your profile"', 'aria-label="Your profile: Current Page"')
        self.visit()
        switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=1500)
        self.assertEqual(self.count('pick'), 1)

    def test_two_different_account_label_variants_are_ambiguous(self):
        self.html = self.html.replace('</header>', '<button aria-label="Your profile: Another account">Avatar</button></header>')
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '多个可见入口'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=600)
        self.assertEqual(self.count('pick'), 0)

    def test_feed_button_with_account_label_is_not_an_avatar_fallback(self):
        self.html = self.html.replace('aria-label="Your profile"', 'aria-label="Unknown avatar"').replace(
            '<article>', '<article><button aria-label="Your profile" onclick="bump(\'post\')">Misleading feed button</button>')
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '未加载|切换超时'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=600)
        self.assertEqual(self.count('post'), 0)
        self.assertEqual(self.count('pick'), 0)

    def test_checkpoint_stops_without_opening_profile_picker(self):
        self.page.goto('https://www.facebook.com/two_step_verification/authentication/')
        with self.assertRaisesRegex(RuntimeError, '登录或安全验证'):
            switcher.switch_page_from_picker(self.page, self.entry, timeout_ms=600)
        self.assertEqual(self.count('account'), 0)


if __name__ == '__main__':
    unittest.main()
