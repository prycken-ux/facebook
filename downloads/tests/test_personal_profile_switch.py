import unittest

import fb_upload as upload
import page_profile_switch as switcher
import test_page_profile_switch as fixtures


class PersonalSwitchTests(fixtures.ProfilePickerTests):
    # Keep only dedicated tests in this subclass; inherited Page regressions
    # remain useful and exercise the shared exact-name picker implementation.
    def as_personal(self,vanity=False):
        self.entry=dict(account='fb10',target='personal',type='personal',workflow='personal_recording_v1',
            name='Example Person',url='https://www.facebook.com/example.person' if vanity else
                'https://www.facebook.com/profile.php?id=1003',auto_switch_personal=True)
        self.html=self.html.replace('Example Page','Example Person').replace("pick('1001')","pick('1003')")
        self.recorded_account_header()

    def test_numeric_personal_owner_switches_from_page_without_post(self):
        self.as_personal()
        self.visit()
        proof=upload.ensure_personal_identity(self.page,self.entry)
        self.assertEqual(proof['method'],'personal_actor_id_match')
        self.assertEqual(self.count('pick'),1)
        self.assertEqual(self.count('notifications'),0)
        self.assertEqual(self.count('post'),0)

    def test_vanity_owner_still_requires_me_redirect_after_switch(self):
        self.as_personal(vanity=True)
        self.context.route('https://www.facebook.com/me**',lambda route:route.fulfill(
            content_type='text/html',body='<script>location.replace("https://www.facebook.com/example.person")</script>'))
        self.visit()
        proof=upload.ensure_personal_identity(self.page,self.entry)
        self.assertEqual(proof['method'],'personal_me_redirect_match')
        self.assertEqual(self.count('pick'),1)
        self.assertEqual(self.count('post'),0)

    def test_same_name_vanity_not_owned_by_login_is_rejected(self):
        self.as_personal(vanity=True)
        self.context.route('https://www.facebook.com/me**',lambda route:route.fulfill(
            content_type='text/html',body='<script>location.replace("https://www.facebook.com/different.owner")</script>'))
        self.visit()
        with self.assertRaisesRegex(RuntimeError,'无法通过 Facebook 本人主页入口'):
            upload.ensure_personal_identity(self.page,self.entry)
        self.assertEqual(self.count('post'),0)

    def test_auto_switch_is_opt_in_and_default_guard_does_not_click(self):
        self.as_personal()
        self.entry.pop('auto_switch_personal')
        self.visit()
        with self.assertRaises(upload.PageActorActive):
            upload.ensure_personal_identity(self.page,self.entry)
        self.assertEqual(self.count('account'),0)

    def test_wrong_numeric_owner_is_rejected_before_picker(self):
        self.as_personal()
        self.entry['url']='https://www.facebook.com/profile.php?id=9999'
        self.visit()
        with self.assertRaisesRegex(RuntimeError,'数字 ID 不一致'):
            switcher.switch_personal_from_picker(self.page,self.entry,timeout_ms=600)
        self.assertEqual(self.count('account'),0)

    def test_selection_does_not_accept_another_page_actor(self):
        self.as_personal()
        self.html=self.html.replace("pick('1003')","pick('1005')")
        self.visit()
        with self.assertRaisesRegex(RuntimeError,'切换超时'):
            switcher.switch_personal_from_picker(self.page,self.entry,timeout_ms=600)
        self.assertEqual(self.count('post'),0)

    def test_login_owner_change_during_personal_selection_is_rejected(self):
        self.as_personal()
        self.html=self.html.replace('function pick(id){',"function pick(id){document.cookie='c_user=9999; domain=.facebook.com; path=/';")
        self.visit()
        with self.assertRaisesRegex(RuntimeError,'登录者变化'):
            switcher.switch_personal_from_picker(self.page,self.entry,timeout_ms=600)
        self.assertEqual(self.count('post'),0)

    def test_already_personal_owner_never_opens_picker(self):
        self.as_personal()
        self.context.add_cookies([dict(name='i_user',value='1003',domain='.facebook.com',path='/')])
        self.visit()
        upload.ensure_personal_identity(self.page,self.entry)
        self.assertEqual(self.count('account'),0)


if __name__=='__main__':unittest.main()
