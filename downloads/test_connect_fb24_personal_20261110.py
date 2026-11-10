import hashlib,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
import connect_fb24_personal_20261110 as connect
import add_personal_accounts as app
import add_fb_accounts as legacy
import fb_upload as upload
import publication_preferences as preferences
import publish_priority_batch as priority
import automatic_batch_retry as retry
import test_add_personal_accounts as fixtures


class ExactFb24PersonalTests(unittest.TestCase):
    def setUp(self):
        self.original_prepare=connect.prepare
        self.f=fixtures.PersonalAdditionsTests();self.f.setUp();self.addCleanup(self.f.doCleanups);self.f.reserve()
        with legacy.locked():preferences.save_authorized()
        self.before={p:p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()}
        self.proof=dict(target_url='https://www.facebook.com/profile.php?id=90027',name='New Person',method='personal_actor_id_match',checked_at='2026-11-10T08:00:00+00:00')
    def prepare(self):
        def shortcuts(items):
            for item in items:Path(item['path']).write_bytes(b'one new login shortcut')
        with patch.object(legacy,'find_chrome',return_value=Path('/chrome')),patch.object(legacy,'write_shortcuts',side_effect=shortcuts):return self.original_prepare()
    def assert_preferences_preserved(self):
        for name in ('publication_preferences.json','common_caption_today.txt'):
            path=self.f.root/name;self.assertEqual(path.read_bytes(),self.before[path])
        path=self.f.root/'logs/publish_state.json';self.assertEqual(path.read_bytes(),self.before[path])
    def test_exact_fb24_is_fresh_and_idempotent_without_creating_other_numbers(self):
        self.assertEqual(self.prepare(),['fb24']);self.assertEqual(self.prepare(),['fb24'])
        for n in (25,26,27,28,29):self.assertFalse((self.f.root/'profiles'/('fb'+str(n))).exists())
        self.assertTrue((self.f.root/'videos/fb24/personal/inbox').is_dir())
        self.assertEqual(upload.CONFIG.read_bytes(),self.before[upload.CONFIG]);self.assert_preferences_preserved()
    def test_full_single_login_enables_only_one_new_target_and_resume_never_reopens(self):
        self.prepare()
        with patch.object(connect,'prepare',side_effect=self.prepare),patch.object(app,'open_accounts') as opened,patch('builtins.input',side_effect=['New Person',self.proof['target_url']]),patch.object(connect,'close_selected_window'),patch.object(connect,'verify',return_value=self.proof),patch.object(upload,'run_entry',side_effect=AssertionError('onboarding cannot publish')):
            self.assertEqual(connect.execute(),0)
        opened.assert_called_once_with(['fb24']);config=upload.read_json(upload.CONFIG,{})
        self.assertEqual(config['targets'][:-1],self.f.config['targets']);self.assertEqual(config['targets'][-1]['account'],'fb24');self.assertTrue(config['targets'][-1]['enabled'])
        with patch.object(connect,'prepare',side_effect=self.prepare),patch.object(app,'open_accounts',side_effect=AssertionError('already completed')),patch('builtins.input',side_effect=AssertionError('do not ask again')):self.assertEqual(connect.execute(),0)
        self.assertEqual(len(upload.read_json(upload.CONFIG,{})['targets']),len(self.f.config['targets'])+1);self.assert_preferences_preserved()
    def test_failed_login_can_skip_or_pause_and_never_enables_or_registers(self):
        self.prepare();before=upload.CONFIG.read_bytes()
        with patch.object(app,'open_accounts'),patch('builtins.input',side_effect=['New Person',self.proof['target_url'],'S']),patch.object(connect,'close_selected_window'),patch.object(connect,'verify',side_effect=RuntimeError('identity not verified')):self.assertFalse(connect.connect('fb24'))
        with patch.object(app,'open_accounts'),patch('builtins.input',return_value='Q'):
            with self.assertRaises(KeyboardInterrupt):connect.connect('fb24')
        self.assertEqual(upload.CONFIG.read_bytes(),before);self.assertEqual(upload.read_json(self.f.root/app.MANIFEST,{})['slots']['fb24']['state'],'pending');self.assert_preferences_preserved()
    def test_existing_person_under_an_alias_is_rejected_before_registration(self):
        self.prepare();before=upload.CONFIG.read_bytes();state=upload.read_json(self.f.root/'logs/publish_state.json',{})
        state['existing owner']=dict(account='fb03',status='published',identity_validation=dict(session_marker=hashlib.sha256(b'personal:90027').hexdigest()));upload.save_json(self.f.root/'logs/publish_state.json',state)
        with patch.object(app,'open_accounts'),patch('builtins.input',side_effect=['New Person','https://www.facebook.com/alias-name','S']),patch.object(connect,'close_selected_window'),patch.object(connect,'verify',return_value=self.proof):self.assertFalse(connect.connect('fb24'))
        self.assertEqual(upload.CONFIG.read_bytes(),before)
    def test_normal_chrome_owner_verification_does_not_export_session_marker_or_accept_changed_owner(self):
        self.prepare();context=MagicMock();context.cookies.return_value=[dict(name='c_user',value='90027')]
        proof=dict(self.proof,session_marker=hashlib.sha256(b'personal:90027').hexdigest());entry=dict(account='fb24',name='New Person',url=self.proof['target_url'])
        with patch('playwright.sync_api.sync_playwright'),patch.object(connect.normal,'launch_normal',return_value=context) as launch,patch.object(upload,'launch_context',side_effect=AssertionError('normal Chrome required')),patch.object(upload,'navigate_profile'),patch.object(upload,'require_no_advanced_protection'),patch.object(upload,'ensure_personal_identity',return_value=proof):
            value=connect.verify(entry);self.assertEqual(value['target_url'],self.proof['target_url']);self.assertNotIn('session_marker',value)
            context.cookies.return_value=[dict(name='c_user',value='90028')]
            with self.assertRaises(ValueError):connect.verify(entry)
        self.assertEqual(context.close.call_count,2)
    def test_one_verified_target_is_eligible_for_saved_caption_and_existing_safe_retry_flow(self):
        self.prepare();app.register('fb24','New Person',self.proof['target_url']);connect.activate('fb24',self.proof)
        row=upload.read_json(upload.CONFIG,{})['targets'][-1];video=upload.inbox_for(row)/'new.mp4';video.write_bytes(b'future single video')
        now=datetime.now(timezone.utc);date=now.astimezone(priority.batch.BJ).date().isoformat()
        path,value=priority.batch.freeze(date,'23:59',True,priority.daily.COMMENT,now,report_format='text',exclude_previous_plans=True)
        self.assertEqual([(j['account'],j['target']) for j in value['payload']['jobs']],[('fb24','personal')]);self.assertEqual(value['payload']['jobs'][0]['caption_text'],preferences.CAPTION)
        value.update(workflow='future-video-comments-v1',auto_retry_policy=retry.POLICY,comment_timing=priority.TIMING,priority_workflow=priority.PRIORITY_WORKFLOW_VERSION);upload.save_json(path,value)
        priority.validate(path,value,date);self.assertEqual(retry.load_source(path)[0],path)
        import scheduled_priority_workflow as workflow
        value.update(scheduled_priority_runner=workflow.VERSION,browser_launch_mode=workflow.normal.NORMAL_CHROME_VERSION,local_file_input_mode=workflow.local.VERSION)
        workflow.validate(path,value)
        registry=upload.read_json(self.f.root/app.MANIFEST,{});registry['slots']['fb24']['batch_id']='old-failed-batch';upload.save_json(self.f.root/app.MANIFEST,registry)
        with self.assertRaises(ValueError):workflow.validate(path,value)
    def test_active_publisher_lock_is_never_displaced(self):
        self.prepare();lock=self.f.root/'logs/upload.lock';lock.write_text('12345');before=upload.CONFIG.read_bytes()
        with self.assertRaises(RuntimeError):self.prepare()
        self.assertEqual(lock.read_text(),'12345');self.assertEqual(upload.CONFIG.read_bytes(),before)
    def test_higher_fb27_reservation_does_not_change_requested_number_or_get_moved(self):
        folder=self.f.root/'profiles/fb27';folder.mkdir();marker=folder/'keep-login';marker.write_bytes(b'preserve existing local login')
        self.assertEqual(self.prepare(),['fb24']);self.assertEqual(marker.read_bytes(),b'preserve existing local login')
    def test_existing_fb24_material_is_never_overwritten_or_restored(self):
        folder=self.f.root/'profiles/fb24';folder.mkdir();marker=folder/'keep';marker.write_bytes(b'existing local material')
        before=upload.CONFIG.read_bytes()
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(marker.read_bytes(),b'existing local material');self.assertEqual(upload.CONFIG.read_bytes(),before)
