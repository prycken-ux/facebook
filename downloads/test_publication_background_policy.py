import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import publication_background_policy as policy
import publish_eligible78_materials_20261117 as app

class BackgroundOnlyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_automatic_boundary_overrides_stale_foreground_and_manual_token_does_not_allow_posting_ui(self):
        calls=[];entry=dict(account='fb03',target='personal')
        def original(pw,row):calls.append((policy.normal.background.mode(self.root),row.get('_local_file_selfcheck')));return object()
        with patch.object(policy.normal,'launch_normal',side_effect=original),policy.installed():
            with patch.object(policy.normal.background,'mode',return_value='foreground'):policy.normal.launch_normal(None,entry)
            with policy.manual_verification():
                policy.normal.launch_normal(None,dict(entry,_local_file_selfcheck=True));policy.normal.launch_normal(None,entry)
            policy.normal.launch_normal(None,entry)
        self.assertEqual(calls,[('background',None),('foreground',True),('background',None),('background',None)])
    def test_manual_token_is_reset_after_validation_error(self):
        try:
            with policy.manual_verification():raise RuntimeError('owner must fix login')
        except RuntimeError:pass
        self.assertFalse(policy._MANUAL.get())
    def test_real_launcher_arguments_headless_automatic_visible_only_manual_then_headless(self):
        (self.root/'profiles/fb03').mkdir(parents=True);port=self.root/'profiles/fb03/DevToolsActivePort';args=[]
        context=MagicMock();context.pages=[MagicMock()];browser=MagicMock();browser.contexts=[context];pw=MagicMock();pw.chromium.connect_over_cdp.return_value=browser
        entry=dict(account='fb03',target='personal',type='personal',workflow='personal_recording_v1',name='Original owner',url='https://www.facebook.com/profile.php?id=123')
        def start(command,**kwargs):
            args.append(command);port.write_text('9222\n/devtools/browser/abc-123\n');return MagicMock()
        with patch.object(policy.normal.upload,'ROOT',self.root),patch.object(policy.normal,'find_chrome',return_value=Path('chrome.exe')), \
             patch.object(policy.normal,'require_profile_free'),patch.object(policy.normal.subprocess,'Popen',side_effect=start), \
             patch.object(policy.normal.upload,'checkpoint'),patch.object(policy.normal.upload,'require_no_advanced_protection'),policy.installed():
            policy.normal.launch_normal(pw,entry)
            with policy.manual_verification():policy.normal.launch_normal(pw,dict(entry,_local_file_selfcheck=True))
            policy.normal.launch_normal(pw,entry)
        self.assertTrue(all('--headless=new' in args[i] and '--new-window' not in args[i] for i in (0,2)))
        self.assertIn('--new-window',args[1]);self.assertNotIn('--headless=new',args[1]);self.assertTrue(all('--user-data-dir='+str(self.root/'profiles/fb03') in a for a in args))
    def test_retire_modes_preserves_progress_and_is_idempotent(self):
        controller=dict(modes={'fb03':'foreground_minimized','fb09':'foreground','fb10':'background'},waves=[dict(manifest='original.json',sha256='a'*64)],rows=[dict(video_status='needs_review',comment_status='sent')])
        before=copy.deepcopy(controller);policy.retire_foreground_modes(controller)
        self.assertEqual(controller['waves'],before['waves']);self.assertEqual(controller['rows'],before['rows']);self.assertTrue(all(v=='background' for v in controller['modes'].values()))
        self.assertEqual(controller['retired_foreground_mode_history'][0]['modes'],{'fb03':'foreground_minimized','fb09':'foreground'})
        snapshot=copy.deepcopy(controller);policy.retire_foreground_modes(controller);self.assertEqual(controller,snapshot)
    def test_save_background_backs_up_original_preferences_without_touching_other_files(self):
        path=self.root/policy.normal.background.SETTINGS;original=dict(schema=policy.normal.background.SCHEMA,mode='foreground',custom_setting='retain');policy.upload.save_json(path,original)
        untouched=self.root/'publish_state.json';untouched.write_bytes(b'unchanged')
        policy.save_background(self.root);self.assertEqual(policy.normal.background.mode(self.root),'background');self.assertEqual(policy.upload.read_json(path,{})['custom_setting'],'retain')
        backup=next((self.root/'backups').rglob(path.name));self.assertEqual(policy.upload.read_json(backup,{}),original)
        before=path.read_bytes();policy.save_background(self.root);self.assertEqual(path.read_bytes(),before);self.assertEqual(untouched.read_bytes(),b'unchanged')
    def test_existing_manual_window_is_scoped_and_returns_to_background(self):
        context=MagicMock();page=MagicMock();seen=[]
        def open_window(pw,entry,mode):seen.append((policy._MANUAL.get(),mode));return context,page
        with patch('playwright.sync_api.sync_playwright'),patch.object(app.owners.guided,'open_for_check',side_effect=open_window),patch.object(app.extra,'wait_session'),patch.object(app.first.upload,'ensure_identity'):
            self.assertEqual(app.manual_existing(dict(account='fb03',target='personal')),'background')
        self.assertEqual(seen,[(True,'foreground')]);self.assertFalse(policy._MANUAL.get());context.close.assert_called_once()
    def test_new_manual_window_never_offers_legacy_foreground_publishing_fallback(self):
        context=MagicMock();page=MagicMock();entry=dict(account='fb26',target='personal');proof=dict(method='personal_actor_id_match');seen=[]
        def open_window(pw,row,mode):seen.append((policy._MANUAL.get(),mode));return context,page
        with patch('playwright.sync_api.sync_playwright'),patch.object(app.owners,'known_owner',return_value='id:123'),patch.object(app.owners.guided,'open_for_check',side_effect=open_window), \
             patch.object(app.owners,'identify_current',return_value=(entry,proof)),patch.object(app.owners,'discover_manual',side_effect=AssertionError('No legacy F fallback')):
            self.assertEqual(app.manual_new('fb26'),(entry,proof,'background'))
        self.assertEqual(seen,[(True,'foreground')]);self.assertFalse(policy._MANUAL.get());context.close.assert_called_once()

if __name__=='__main__':unittest.main()
