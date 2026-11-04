import copy,json,unittest
from unittest.mock import patch
import remove_failed_three_personal_20261104 as remove
import add_personal_accounts as app
import add_fb_accounts as legacy
import fb_upload as upload
import test_add_personal_accounts as fixtures


class RemoveThreeTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.PersonalAdditionsTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.fx.reserve()
        self.original_manifest=upload.read_json(self.fx.root/app.MANIFEST,{})
        self.original={p:p.read_bytes() for p in self.fx.root.rglob('*') if p.is_file() and p.name!=app.MANIFEST}
        with legacy.locked():self.assertEqual(app.reserve(3,remove.BATCH_ID),list(remove.ACCOUNTS))
        for account in remove.ACCOUNTS:
            (self.fx.root/'profiles'/account/'private-session').write_bytes(b'private test data')
            (self.fx.root/'videos'/account/'personal/inbox/video.mp4').write_bytes(b'new video stays private')
            (self.fx.shortcut_dir/(account+' 登录.lnk')).write_bytes(b'new shortcut')
        self.close=self.fx.stack.enter_context(patch.object(remove,'close_selected_window'))
    def assert_old(self):
        for path,content in self.original.items():self.assertEqual(path.read_bytes(),content)
    def test_permanent_cleanup_removes_three_profiles_shortcuts_videos_and_reservations_without_backups(self):
        self.assertEqual(remove.execute(),0)
        self.assertEqual([c.args[0] for c in self.close.call_args_list],list(remove.ACCOUNTS))
        for account in remove.ACCOUNTS:
            self.assertFalse((self.fx.root/'profiles'/account).exists());self.assertFalse((self.fx.root/'videos'/account).exists())
            self.assertFalse((self.fx.shortcut_dir/(account+' 登录.lnk')).exists())
        self.assertEqual(upload.read_json(self.fx.root/app.MANIFEST,{}),self.original_manifest)
        self.assertFalse((self.fx.root/'logs'/remove.PROGRESS).exists());self.assert_old()
        self.assertFalse((self.fx.root/'backups').exists())
        self.close.reset_mock();self.assertEqual(remove.execute(),0);self.close.assert_not_called()
    def test_existing_mixed_backups_are_scrubbed_but_other_accounts_and_their_backups_survive(self):
        folder=self.fx.root/'backups/mixed-fb24-and-fb01';folder.mkdir(parents=True)
        old=self.fx.config['targets'][0];new=dict(account='fb24',name='Failed login',url='https://www.facebook.com/profile.php?id=90024')
        upload.save_json(folder/'upload_config.json',dict(targets=[old,new],custom='preserve'))
        upload.save_json(folder/'onboarding-proof.json',dict(account='fb25',proof={'private':'test'}))
        upload.save_json(folder/app.MANIFEST,upload.read_json(self.fx.root/app.MANIFEST,{}))
        (folder/'fb26').mkdir();(folder/'fb26/cache').write_bytes(b'private cache')
        remove.execute()
        self.assertTrue(folder.is_dir());self.assertEqual(upload.read_json(folder/'upload_config.json',{}),dict(targets=[old],custom='preserve'))
        self.assertFalse((folder/'onboarding-proof.json').exists());self.assertFalse((folder/'fb26').exists())
        self.assertEqual(upload.read_json(folder/app.MANIFEST,{}),self.original_manifest);self.assert_old()
    def test_config_registry_and_publication_rows_for_exact_three_are_removed_without_other_changes(self):
        for name,key in [('upload_config.json','targets'),('account_registry.json','accounts')]:
            value=upload.read_json(self.fx.root/name,{});value[key].append(dict(account='fb24',name='New person'))
            upload.save_json(self.fx.root/name,value)
        state=upload.read_json(self.fx.root/'logs/publish_state.json',{});state['new24']=dict(account='fb24',status='failed_before_post');upload.save_json(self.fx.root/'logs/publish_state.json',state)
        remove.execute();self.assert_old()
    def test_window_close_failure_leaves_all_data_and_registrations_untouched(self):
        before={p:p.read_bytes() for p in self.fx.root.rglob('*') if p.is_file()}
        self.close.side_effect=RuntimeError('profile still busy')
        with self.assertRaises(RuntimeError):remove.execute()
        for path,data in before.items():self.assertEqual(path.read_bytes(),data)
    def test_partial_removal_error_can_resume_after_registration_was_already_removed(self):
        real=remove.shutil.rmtree
        def fail(path,*args,**kwargs):
            if path==self.fx.root/'profiles/fb25':raise PermissionError('simulated file busy')
            return real(path,*args,**kwargs)
        with patch.object(remove.shutil,'rmtree',side_effect=fail):
            with self.assertRaises(PermissionError):remove.execute()
        self.assertTrue((self.fx.root/'logs'/remove.PROGRESS).exists())
        self.assertEqual(remove.execute(),0);self.assertFalse((self.fx.root/'logs'/remove.PROGRESS).exists());self.assert_old()
    def test_changed_batch_or_foreign_slot_refuses_before_deleting_anything(self):
        path=self.fx.root/app.MANIFEST;value=upload.read_json(path,{})
        value['slots']['fb24']['batch_id']='different-batch';upload.save_json(path,value)
        with self.assertRaises(ValueError):remove.execute()
        self.close.assert_not_called();self.assertTrue((self.fx.root/'profiles/fb24/private-session').exists())
    def test_missing_ownership_record_does_not_delete_reused_account_numbers(self):
        upload.save_json(self.fx.root/app.MANIFEST,self.original_manifest)
        with self.assertRaises(ValueError):remove.execute()
        self.close.assert_not_called();self.assertTrue((self.fx.root/'profiles/fb24/private-session').exists())
    def test_malformed_backup_containing_selected_account_stops_before_any_deletion(self):
        folder=self.fx.root/'backups';folder.mkdir();(folder/'mixed.json').write_bytes(b'{"account":"fb24"')
        with self.assertRaises(ValueError):remove.execute()
        self.close.assert_not_called();self.assertTrue((self.fx.root/'profiles/fb24/private-session').exists())
    def test_active_upload_lock_stops_cleanup_without_removing_lock(self):
        lock=self.fx.root/'logs/upload.lock';lock.write_text('12345')
        with self.assertRaises(RuntimeError):remove.execute()
        self.assertEqual(lock.read_text(),'12345');self.close.assert_not_called()
    def test_link_to_another_accounts_profile_stops_before_any_deletion(self):
        folder=self.fx.root/'backups';folder.mkdir();(folder/'fb24').symlink_to(self.fx.root/'profiles/fb01',target_is_directory=True)
        with self.assertRaises(ValueError):remove.execute()
        self.close.assert_not_called();self.assert_old()
    def test_scrub_preserves_other_batch_members_and_counts(self):
        value=dict(accounts=['fb24','fb27'],count=2,other='keep')
        self.assertEqual(remove.scrub(value),dict(accounts=['fb27'],count=1,other='keep'))
        self.assertIs(remove.scrub(dict(account='fb26',private='test')),remove.DROP)
