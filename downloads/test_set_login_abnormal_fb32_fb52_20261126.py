import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import set_login_abnormal_fb32_fb52_20261126 as policy

class DisableAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'upload_config.json').write_text('{"targets":[]}')
        self.payload=dict(schema='publication-account-exclusions-v1',excluded_accounts=sorted(policy.BASE_EXCLUDED),custom='keep')
        self.old=dict(payload=self.payload,sha256=policy.digest(self.payload));self.path=self.root/'publication_account_exclusions.json';policy.save(self.path,self.old)
        self.registry=dict(schema='additional-personal-logins-v1',batches={'keep':'original'},slots={a:dict(state='registered',publishing_ready=True,identity_verified_at='original',mapping=dict(account=a,target='personal',type='personal',workflow='personal_recording_v1',url='https://www.facebook.com/profile.php?id='+a[2:]),cookie_metadata='unchanged') for a in ['fb31','fb32','fb52']})
        policy.save(self.root/'additional_personal_accounts.json',self.registry)
        self.sentinel=self.root/'logs/publish_state.json';self.sentinel.parent.mkdir();self.sentinel.write_text('{"original":"keep"}')
    def test_exact_two_disabled_preserving_existing_stops_history_and_other_account(self):
        self.assertEqual(policy.apply(self.root),0);saved=policy.read(self.path,{})
        self.assertEqual(saved['sha256'],policy.digest(saved['payload']));self.assertEqual(len(saved['payload']['excluded_accounts']),36);self.assertEqual(saved['payload']['custom'],'keep')
        registry=policy.read(self.root/'additional_personal_accounts.json',{})
        self.assertEqual(registry['slots']['fb31'],self.registry['slots']['fb31']);self.assertEqual(registry['batches'],self.registry['batches'])
        for a in policy.ACCOUNTS:
            self.assertFalse(registry['slots'][a]['publishing_ready']);self.assertEqual(registry['slots'][a]['login_status'],'login_abnormal');self.assertFalse(saved['payload']['account_status_overrides'][a]['auto_resume'])
            self.assertEqual(registry['slots'][a]['mapping'],self.registry['slots'][a]['mapping'])
        self.assertEqual(self.sentinel.read_text(),'{"original":"keep"}');self.assertTrue(list((self.root/'backups').glob('login-abnormal-fb32-fb52-*')))
    def test_replay_is_idempotent_and_does_not_add_backup(self):
        policy.apply(self.root);before={p.name:p.read_bytes() for p in [self.path,self.root/'additional_personal_accounts.json']};count=len(list((self.root/'backups').iterdir()))
        policy.apply(self.root);self.assertEqual({p.name:p.read_bytes() for p in [self.path,self.root/'additional_personal_accounts.json']},before);self.assertEqual(len(list((self.root/'backups').iterdir())),count)
    def test_invalid_existing_fingerprint_or_registry_never_changes_other_files(self):
        self.path.write_text(json.dumps(dict(self.old,sha256='bad')));before=(self.root/'additional_personal_accounts.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'校验失败'):policy.apply(self.root)
        self.assertEqual((self.root/'additional_personal_accounts.json').read_bytes(),before)
        policy.save(self.path,self.old);(self.root/'additional_personal_accounts.json').write_text('{"schema":"unknown"}')
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'登记格式'):policy.apply(self.root)
        self.assertEqual(self.path.read_bytes(),before)
    def test_existing_publication_and_allocation_readers_skip_new_accounts(self):
        import publish_eligible60_materials_20261119 as app
        import stage_eligible60_materials_v6 as stage
        policy.apply(self.root)
        self.assertTrue({'fb32','fb52'}<=app.read_live_pauses(self.root))
        with self.assertRaisesRegex(ValueError,'暂停名单已扩大'):stage.check_live_pauses(self.root,[dict(account='fb32',target='personal')])
        upload=app.first.upload;batch=app.first.batch
        with patch.object(upload,'ROOT',self.root),patch.object(batch.preferences,'load',return_value=None):
            for a in policy.ACCOUNTS:self.assertFalse(batch.eligible(self.registry['slots'][a]['mapping'],True,date='2026-11-26'))
            self.assertTrue(batch.eligible(self.registry['slots']['fb31']['mapping'],True,date='2026-11-26'))

if __name__=='__main__':unittest.main()
