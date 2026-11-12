import contextlib
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

import fb_upload as upload
import personal_owner_registration as app


class VerifiedOwnerNameCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        (self.root/'profiles/fb17').mkdir(parents=True)
        self.entry=dict(account='fb17',target='personal',type='personal',workflow='personal_recording_v1',name='Current owner',url='https://www.facebook.com/profile.php?id=20001')
        self.proof=dict(target_url=self.entry['url'],name='Current owner',method='personal_actor_id_match',
                        session_marker=hashlib.sha256(b'personal:20001').hexdigest(),recovery_login_marker='login',verified_aliases=[])
        self.saved=dict(self.entry,name='Saved Person')
        upload.save_json(upload.CONFIG,dict(targets=[self.saved]))
        upload.save_json(self.root/'account_registry.json',dict(accounts=[]))
        upload.save_json(self.root/'additional_personal_accounts.json',dict(slots={}))
        self.page=MagicMock()

    def test_exact_owner_reuses_saved_name_before_consulting_a_missing_page_title(self):
        with patch.object(app.routes,'stable_actor',return_value=self.proof['session_marker']),patch.object(app.routes.numeric,'public_name',side_effect=AssertionError('cache should be first')),patch('builtins.input',side_effect=AssertionError('must not ask')):
            self.assertEqual(app.automatic_name(self.page,'fb17',self.entry,self.proof),'Saved Person')

    def test_old_person_on_same_account_number_cannot_supply_new_owners_name(self):
        wrong=dict(self.saved,url='https://www.facebook.com/profile.php?id=20002',name='Old person')
        upload.save_json(upload.CONFIG,dict(targets=[wrong]))
        self.assertIsNone(app.cached_name('fb17',self.entry,self.proof))
        self.page.locator.return_value.count.return_value=1
        self.page.locator.return_value.get_attribute.return_value='Fresh Person | Facebook'
        with patch.object(app.routes,'stable_actor'),patch.object(app.routes.numeric,'public_name',return_value=None):
            self.assertEqual(app.automatic_name(self.page,'fb17',self.entry,self.proof),'Fresh Person')

    def test_registry_and_verified_alias_are_allowed_but_unproved_alias_is_not(self):
        upload.save_json(upload.CONFIG,dict(targets=[]))
        alias=dict(self.saved,url='https://www.facebook.com/saved.person');alias.pop('target')
        upload.save_json(self.root/'account_registry.json',dict(accounts=[alias]))
        self.assertIsNone(app.cached_name('fb17',self.entry,self.proof))
        self.assertEqual(app.cached_name('fb17',self.entry,dict(self.proof,verified_aliases=['slug:saved.person'])),'Saved Person')

    def test_generic_login_titles_and_conflicting_saved_names_are_not_guessed(self):
        for text in ('Facebook','(20+) Facebook','Facebook — log in or sign up','Log in to Facebook'):
            self.assertIsNone(app.clean_name(text))
        upload.save_json(upload.CONFIG,dict(targets=[self.saved,dict(self.saved,name='Conflicting name')]))
        with self.assertRaises(ValueError):app.cached_name('fb17',self.entry,self.proof)

    def test_actual_discovery_uses_saved_name_and_never_calls_input(self):
        context=MagicMock();context.pages=[self.page];context.cookies.return_value=[dict(name='c_user',value='20001')]
        with patch('playwright.sync_api.sync_playwright'),patch.object(app.old,'assert_free'),patch.object(app.old,'close_selected_window'), \
             patch.object(app.old.normal,'launch_normal',return_value=context),patch.object(upload,'navigate_profile'), \
             patch.object(app.routes,'ensure_personal',return_value=dict(self.proof)),patch.object(app.routes,'stable_actor',return_value=self.proof['session_marker']), \
             patch('builtins.input',side_effect=AssertionError('no repeated name entry')):
            entry,proof=app.discover('fb17')
        self.assertEqual(entry['name'],'Saved Person');self.assertEqual(proof['name'],'Saved Person')
        context.close.assert_called_once()


if __name__=='__main__':unittest.main()
