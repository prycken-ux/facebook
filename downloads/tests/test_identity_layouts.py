"""Browser regressions for the uploaded identity-diagnostic screenshots."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

import fb_upload as upload


PERSONAL = '''<html lang="en-US"><main><section id="profile-header">
<div><span id="profile-name">Example Person</span></div>
<div><button>Edit profile</button><button>Add to story</button></div></section>
<section><h2>People You May Know</h2><h2>Posts</h2>
<div role="feed"><article><h3>Example Person updated their picture</h3></article></div></section>
</main></html>'''

PAGE = '''<html lang="en-US"><aside><h2>Manage Page</h2><h2>Example Page</h2><button>Edit Page</button></aside>
<main><section id="header"><h1>Example Page</h1><div id="controls"></div></section>
<div id="switch-area"></div><section role="feed"><article>Posts</article></section></main>
<script>function activate(){window.switchClicks=(window.switchClicks||0)+1;
document.cookie='i_user=1001; domain=.facebook.com; path=/';
document.querySelector('#switch-area').innerHTML='';}</script></html>'''


class IdentityLayoutTests(unittest.TestCase):
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
        self.context.route('https://www.facebook.com/**', self.route)
        self.page = self.context.new_page()
        self.html = PERSONAL
        self.me_url = 'https://www.facebook.com/example.person'
        self.me_html = None
        self.entry = dict(account='fb14', target='personal', type='personal', name='Example Person',
            url='https://www.facebook.com/profile.php?id=1003', workflow='personal_recording_v1')
        self.context.add_cookies([dict(name='c_user', value='1003', domain='.facebook.com', path='/')])
        self.silent = contextlib.redirect_stdout(io.StringIO())
        self.silent.__enter__()

    def tearDown(self):
        self.silent.__exit__(None, None, None)
        self.context.close()

    def route(self, route):
        if urlparse(route.request.url).path.rstrip('/') == '/me':
            route.fulfill(content_type='text/html', body='<script>location.replace(' + json.dumps(self.me_url) + ')</script>')
        else:
            route.fulfill(content_type='text/html', body=self.me_html or self.html)

    def visit(self):
        self.page.goto(self.entry['url'])

    def as_page(self, actor=None):
        self.entry.update(account='fb10', target='page02', type='page', name='Example Page',
            url='https://www.facebook.com/profile.php?id=1001', workflow='page_flow_configured')
        self.html = PAGE
        if actor:
            self.context.add_cookies([dict(name='i_user', value=actor, domain='.facebook.com', path='/')])

    def test_personal_name_without_heading_and_edit_profile_passes_real_owner(self):
        self.visit()
        self.assertEqual(self.page.get_by_role('heading', name='Example Person', exact=True).count(), 0)
        proof = upload.ensure_personal_identity(self.page, self.entry)
        self.assertEqual(proof['method'], 'personal_actor_id_match')

    def test_personal_new_name_markup_keeps_me_ownership_check_for_vanity(self):
        self.entry['url'] = self.me_url
        self.visit()
        proof = upload.ensure_personal_identity(self.page, self.entry)
        self.assertEqual(proof['method'], 'personal_me_redirect_match')

    def test_other_vanity_profile_cannot_pass_with_same_nonheading_name(self):
        self.entry['url'] = 'https://www.facebook.com/not.the.owner'
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '无法通过 Facebook 本人主页入口确认'):
            upload.ensure_personal_identity(self.page, self.entry)

    def test_numeric_me_redirect_still_needs_matching_cookie_and_canonical(self):
        self.entry['url'] = self.me_url
        self.me_url = 'https://www.facebook.com/profile.php?id=1003'
        self.me_html = '<link rel="canonical" href="' + self.entry['url'] + '">' + PERSONAL
        self.visit()
        self.assertEqual(upload.ensure_personal_identity(self.page, self.entry)['method'], 'personal_me_redirect_match')

    def test_wrong_numeric_me_redirect_is_rejected_despite_matching_name(self):
        self.entry['url'] = self.me_url
        self.me_url = 'https://www.facebook.com/profile.php?id=1004'
        self.me_html = '<link rel="canonical" href="' + self.entry['url'] + '">' + PERSONAL
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '无法通过 Facebook 本人主页入口确认'):
            upload.ensure_personal_identity(self.page, self.entry)

    def test_numeric_profile_wrong_owner_is_rejected_before_ui_probe(self):
        self.context.add_cookies([dict(name='c_user', value='1004', domain='.facebook.com', path='/')])
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '登录的个人账号与目标个人主页不一致'):
            upload.ensure_personal_identity(self.page, self.entry)

    def test_names_in_posts_or_sidebar_with_edit_controls_are_not_profile_header(self):
        for html in ('<article><div>Example Person</div><button>Edit profile</button></article>',
                     '<aside><h1>Example Person</h1><button>Edit profile</button></aside>',
                     '<div role="feed"><h1>Example Person</h1><button>Edit profile</button></div>',
                     '<div role="dialog"><h1>Example Person</h1><button>Edit profile</button></div>'):
            with self.subTest(html=html):
                self.html = html
                self.visit()
                with self.assertRaises(upload.ProfileNameNotReady):
                    upload.wait_profile_name(self.page, self.entry, timeout_ms=100)

    def test_matching_plain_text_requires_local_edit_control_and_not_disabled_control(self):
        for html in ('<div>Example Person</div><button>Follow</button>',
                     '<section><div>Example Person</div><button disabled>Edit profile</button></section>',
                     '<section><div>Example Person</div></section><aside><button>Edit profile</button></aside>'):
            with self.subTest(html=html):
                self.html = html
                self.visit()
                with self.assertRaises(upload.ProfileNameNotReady):
                    upload.wait_profile_name(self.page, self.entry, timeout_ms=100)

    def test_hidden_heading_does_not_mask_visible_new_personal_header(self):
        self.html = '<h1 hidden>Example Person</h1>' + PERSONAL
        self.visit()
        self.assertEqual(upload.ensure_personal_identity(self.page, self.entry)['method'], 'personal_actor_id_match')

    def test_page_waits_for_delayed_switch_now_instead_of_failing_on_skeleton(self):
        self.as_page()
        self.html += '''<script>setTimeout(()=>{document.querySelector('#switch-area').innerHTML=
        '<span>Switch into Example Page\\'s Page to start managing it.</span><button onclick="activate()">Switch Now</button>';},150)</script>'''
        self.visit()
        proof = upload.ensure_page_identity(self.page, self.entry, timeout_ms=1500)
        self.assertEqual(proof['method'], 'page_actor_id_match')
        self.assertTrue(proof['switched'])
        self.assertEqual(self.page.evaluate('window.switchClicks'), 1)

    def test_different_initial_page_actor_waits_for_delayed_known_switch(self):
        self.as_page('99999')
        self.html += '''<script>setTimeout(()=>{document.querySelector('#switch-area').innerHTML=
        '<a href="#" onclick="event.preventDefault();activate()">Switch Now</a>';},150)</script>'''
        self.visit()
        self.assertTrue(upload.ensure_page_identity(self.page, self.entry, timeout_ms=1500)['switched'])
        self.assertEqual(self.page.evaluate('window.switchClicks'), 1)

    def test_delayed_real_header_management_control_is_valid_without_actor_cookie(self):
        self.as_page()
        self.html += '''<script>setTimeout(()=>document.querySelector('#controls').innerHTML='<button>Edit Page</button>',150)</script>'''
        self.visit()
        self.assertEqual(upload.ensure_page_identity(self.page, self.entry, timeout_ms=1500)['method'],
                         'active_page_header_management_control')

    def test_sidebar_management_buttons_never_establish_active_page_identity(self):
        self.as_page()
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '仍无法确认公共主页身份'):
            upload.ensure_page_identity(self.page, self.entry, timeout_ms=150)

    def test_wrong_active_page_cannot_be_overridden_by_header_edit_button(self):
        self.as_page('99999')
        self.html = self.html.replace('<div id="controls"></div>', '<div id="controls"><button>Edit Page</button></div>')
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '发布身份与目标公共主页不一致'):
            upload.ensure_page_identity(self.page, self.entry, timeout_ms=150)

    def test_duplicate_switch_buttons_are_not_clicked(self):
        self.as_page()
        self.html += '<button onclick="activate()">Switch Now</button><button onclick="activate()">Switch Now</button>'
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '多个公共主页切换入口'):
            upload.ensure_page_identity(self.page, self.entry, timeout_ms=500)
        self.assertIsNone(self.page.evaluate('window.switchClicks'))

    def test_uncompleted_switch_does_not_loop_click_or_mark_success(self):
        self.as_page()
        self.html += '<button onclick="window.switchClicks=(window.switchClicks||0)+1">Switch Now</button>'
        self.visit()
        with self.assertRaisesRegex(RuntimeError, '仍无法确认公共主页身份'):
            upload.ensure_page_identity(self.page, self.entry, timeout_ms=400)
        self.assertEqual(self.page.evaluate('window.switchClicks'), 1)

    def test_wrong_target_url_stops_before_switch(self):
        self.as_page()
        self.html += '<button onclick="activate()">Switch Now</button>'
        self.visit()
        self.entry['url'] = 'https://www.facebook.com/profile.php?id=1002'
        with self.assertRaisesRegex(RuntimeError, '不同主页'):
            upload.ensure_page_identity(self.page, self.entry, timeout_ms=500)
        self.assertIsNone(self.page.evaluate('window.switchClicks'))

    def test_checkpoint_is_not_refreshed_or_bypassed_by_name_wait(self):
        self.page.goto('https://www.facebook.com/two_step_verification/authentication/')
        with self.assertRaisesRegex(RuntimeError, '登录或安全验证'):
            upload.wait_profile_name(self.page, self.entry, timeout_ms=100)


if __name__ == '__main__':
    unittest.main()
