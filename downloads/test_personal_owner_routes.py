import contextlib
import io
import json
import unittest
from unittest.mock import patch
from playwright.sync_api import sync_playwright
import fb_upload as upload
import personal_owner_routes as app


class PersonalAliasBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context();self.addCleanup(self.context.close)
        self.context.add_cookies([dict(name='c_user',value='1001',domain='.facebook.com',path='/')])
        self.page=self.context.new_page();self.me='https://www.facebook.com/new.person';self.numeric_alias=True;self.canonical='https://www.facebook.com/new.person';self.change_owner=False
        self.context.route('https://www.facebook.com/**',self.route)
        self.entry=dict(account='fb17',target='personal',type='personal',workflow='personal_recording_v1',name='New Person',url='https://www.facebook.com/profile.php?id=1001')
        self.silence=contextlib.redirect_stdout(io.StringIO());self.silence.__enter__();self.addCleanup(self.silence.__exit__,None,None,None)
    def route(self,route):
        url=route.request.url
        if '/me?' in url or url.endswith('/me'):
            if self.change_owner:self.context.add_cookies([dict(name='c_user',value='9999',domain='.facebook.com',path='/')])
            if 'profile.php' in self.me:self.numeric_alias=False
            route.fulfill(content_type='text/html',body='<script>location.replace('+json.dumps(self.me)+')</script>');return
        if 'profile.php?id=1001' in url and self.numeric_alias:
            route.fulfill(content_type='text/html',body='<script>location.replace("https://www.facebook.com/new.person")</script>');return
        route.fulfill(content_type='text/html',body='<html lang="en-US"><title>New Person | Facebook</title><link rel="canonical" href="'+self.canonical+'"><main><h1>New Person</h1><button>Edit profile</button></main><button onclick="window.posts=1">Post</button></html>')
    def visit(self):
        self.page.goto(self.entry['url']);self.page.wait_for_url('**/new.person')
    def test_numeric_link_redirecting_to_vanity_passes_me_and_owner_proof_without_posting(self):
        self.visit()
        proof=app.ensure_personal(self.page,self.entry)
        self.assertEqual(proof['verified_aliases'],['slug:new.person'])
        self.assertEqual(proof['route_method'],'me_redirect_owner_match')
        upload.recheck_publish_identity(self.page,self.entry,proof)
        self.assertIsNone(self.page.evaluate('window.posts'))
    def test_same_display_name_on_someone_else_route_fails_me_ownership(self):
        self.page.goto('https://www.facebook.com/other.person')
        with self.assertRaisesRegex(RuntimeError,'本人主页入口'):app.ensure_personal(self.page,self.entry)
        self.assertIsNone(self.page.evaluate('window.posts'))
    def test_numeric_me_canonical_alias_is_accepted_for_the_same_owner(self):
        self.me=self.entry['url'];self.visit()
        proof=app.ensure_personal(self.page,self.entry)
        self.assertEqual(proof['verified_aliases'],['slug:new.person'])
    def test_login_owner_change_and_page_actor_cannot_be_accepted_by_same_name(self):
        self.visit();self.change_owner=True
        with self.assertRaisesRegex(RuntimeError,'登录者变化'):app.ensure_personal(self.page,self.entry)
        self.context.add_cookies([dict(name='c_user',value='1001',domain='.facebook.com',path='/'),dict(name='i_user',value='9000',domain='.facebook.com',path='/')])
        self.change_owner=False
        with patch('builtins.input',return_value='S'),self.assertRaisesRegex(RuntimeError,'尚未切回本人'):
            app.ensure_personal(self.page,self.entry)
    def test_non_profile_routes_do_not_pass_even_with_matching_owner_cookie(self):
        self.page.goto('https://www.facebook.com/friends')
        with self.assertRaisesRegex(RuntimeError,'不是可核验'):app.ensure_personal(self.page,self.entry)
    def test_scoped_final_recheck_rejects_owner_change_and_restores_hooks(self):
        self.visit();original=upload.ensure_identity
        with patch.object(upload,'read_json',return_value={'targets':[self.entry]}),app.scoped({'fb17'}):
            proof=upload.ensure_identity(self.page,self.entry)
            self.context.add_cookies([dict(name='c_user',value='9999',domain='.facebook.com',path='/')])
            with self.assertRaisesRegex(RuntimeError,'登录者变化'):upload.recheck_publish_identity(self.page,self.entry,proof)
        self.assertIs(upload.ensure_identity,original)


if __name__=='__main__':unittest.main()
