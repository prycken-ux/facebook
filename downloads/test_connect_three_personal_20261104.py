import copy,io,unittest
from pathlib import Path
from unittest.mock import patch
import connect_three_personal_20261104 as connect
import add_personal_accounts as app
import add_fb_accounts as legacy
import fb_upload as upload
import scheduled_material_batch as batch
import test_add_personal_accounts as fixtures


class ThreePersonalTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.PersonalAdditionsTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.fx.reserve()  # Original onboarding owns fb14-fb23, so next are 24-26.
        self.before={p:p.read_bytes() for p in self.fx.root.rglob('*') if p.is_file()}
        with legacy.locked():self.selected=app.reserve(3,connect.BATCH_ID)
        self.proof=dict(target_url='https://www.facebook.com/profile.php?id=90024',name='New Person',method='personal_actor_id_match',checked_at='2026-11-04T08:00:00+00:00')
    def test_exact_three_profiles_preserve_existing_records_sessions_and_repeat_without_new_numbers(self):
        self.assertEqual(self.selected,['fb24','fb25','fb26'])
        with legacy.locked():self.assertEqual(app.reserve(3,connect.BATCH_ID),self.selected)
        for path,data in self.before.items():
            if path.name!=app.MANIFEST:self.assertEqual(path.read_bytes(),data)
        self.assertFalse((self.fx.root/'profiles/fb27').exists())
        self.assertFalse(batch.eligible(dict(account='fb24',target='personal',url=self.proof['target_url']),True))
    def test_login_registration_and_identity_activation_connects_to_frozen_job_selection(self):
        with patch.object(app,'open_accounts') as opened,patch('builtins.input',side_effect=['New Person',self.proof['target_url']]),patch.object(connect,'close_selected_window') as closed,patch.object(connect,'verify',return_value=self.proof):
            self.assertTrue(connect.connect('fb24'))
        opened.assert_called_once_with(['fb24']);closed.assert_called_once_with('fb24')
        config=upload.read_json(upload.CONFIG,{})
        self.assertEqual(config['targets'][:-1],self.fx.config['targets'])
        row=config['targets'][-1];self.assertTrue(row['enabled']);self.assertEqual(row['workflow'],'personal_recording_v1')
        self.assertNotIn('prepared_at',row)
        self.assertTrue(batch.eligible(row,True))
        job={k:row[k] for k in ('account','target','url')};self.assertTrue(batch.eligible(job,True))
        self.assertFalse(batch.eligible(dict(job,url='https://www.facebook.com/profile.php?id=999'),True))
        self.assertFalse(batch.eligible(dict(job,target='page01',type='page'),True))
        for n in ('16','18','21'):self.assertFalse(batch.eligible(dict(account='fb'+n,target='personal'),True))
        self.assertEqual((self.fx.root/'logs/publish_state.json').read_bytes(),self.before[self.fx.root/'logs/publish_state.json'])
        with patch.object(app,'open_accounts',side_effect=AssertionError('connected must not reopen')),patch('builtins.input',side_effect=AssertionError('already connected')):
            self.assertTrue(connect.connect('fb24'))
    def test_wrong_identity_or_network_error_never_registers_or_enables_and_can_skip(self):
        config=upload.CONFIG.read_bytes()
        with patch.object(app,'open_accounts'),patch('builtins.input',side_effect=['New Person',self.proof['target_url'],'S']),patch.object(connect,'close_selected_window'),patch.object(connect,'verify',side_effect=RuntimeError('identity mismatch')):
            self.assertFalse(connect.connect('fb24'))
        self.assertEqual(upload.CONFIG.read_bytes(),config)
        manifest=upload.read_json(self.fx.root/app.MANIFEST,{})
        self.assertEqual(manifest['slots']['fb24']['state'],'pending');self.assertNotIn('publishing_ready',manifest['slots']['fb24'])
    def test_duplicate_existing_owner_stops_before_identity_browser_or_registration(self):
        config=upload.CONFIG.read_bytes()
        with patch.object(app,'open_accounts'),patch('builtins.input',side_effect=['Old Person',self.fx.config['targets'][0]['url'],'S']),patch.object(connect,'verify') as verify,patch.object(connect,'close_selected_window') as closed:
            self.assertFalse(connect.connect('fb24'))
        verify.assert_not_called();closed.assert_not_called();self.assertEqual(upload.CONFIG.read_bytes(),config)
    def test_activation_proof_conflict_and_failed_config_save_leave_registration_disabled(self):
        app.register('fb24','New Person',self.proof['target_url'])
        before=upload.CONFIG.read_bytes()
        with self.assertRaises(ValueError):connect.activate('fb24',dict(self.proof,target_url='https://www.facebook.com/profile.php?id=999'))
        self.assertEqual(upload.CONFIG.read_bytes(),before)
        save=upload.save_json
        def fail_manifest(path,value):
            if path==self.fx.root/app.MANIFEST:raise OSError('simulated failure')
            save(path,value)
        with patch.object(upload,'save_json',side_effect=fail_manifest):
            with self.assertRaises(OSError):connect.activate('fb24',self.proof)
        self.assertEqual(upload.CONFIG.read_bytes(),before);self.assertFalse(batch.eligible(dict(account='fb24',target='personal',url=self.proof['target_url']),True))
    def test_q_preserves_profiles_and_active_lock_prevents_activation(self):
        with patch.object(app,'open_accounts'),patch('builtins.input',return_value='Q'):
            with self.assertRaises(KeyboardInterrupt):connect.connect('fb24')
        app.register('fb24','New Person',self.proof['target_url'])
        lock=self.fx.root/'logs/upload.lock';lock.write_text('12345')
        with self.assertRaises(RuntimeError):connect.activate('fb24',self.proof)
        self.assertEqual(lock.read_text(),'12345')
    def test_unverified_registered_new_personal_accounts_are_not_eligible(self):
        app.register('fb24','New Person',self.proof['target_url'])
        row=upload.read_json(upload.CONFIG,{})['targets'][-1]
        self.assertFalse(batch.eligible(row,True))
        self.assertFalse(batch.eligible(dict(account='fb99',target='personal',url=self.proof['target_url']),True))
