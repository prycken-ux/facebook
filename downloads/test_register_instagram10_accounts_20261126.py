import contextlib,copy,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import register_instagram10_accounts_20261126 as app
import setup_instagram10_browser_workspace_20261126 as setup

class RegistrationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.root=self.base/'IG-AutoUpload';chrome=self.base/'chrome.exe';chrome.write_bytes(b'fixture');desktop=self.base/'Desktop';desktop.mkdir();self.enterContext(contextlib.redirect_stdout(io.StringIO()))
  setup.prepare(self.root,chrome=chrome,desktop=desktop,writer=lambda *a,**k:None)
  self.keep=[self.root/'profiles/ins01/Default/Login Data',self.root/'videos/ins02/inbox/fresh.mp4',self.root/'common_caption.txt',self.root/'common_comment.txt',self.root/'shortcuts/ins01 Instagram.lnk']
  for p in self.keep:
   p.parent.mkdir(parents=True,exist_ok=True)
   if not p.exists():p.write_bytes(('preserve '+str(p.name)).encode())
  self.before={p:p.read_bytes() for p in self.keep}
 def read(self):return app.read(self.root/'instagram_accounts.json')
 def write(self,v):app.atomic_bytes(self.root/'instagram_accounts.json',app.encoded(v))
 def test_all_ten_exact_mappings_replace_placeholder_without_claiming_identity_or_publishing(self):
  report=app.apply(self.root);actual=self.read();rows={r['account']:r for r in actual['accounts']}
  self.assertEqual({slot:r['expected_username'] for slot,r in rows.items()},app.MAPPING)
  self.assertEqual(rows['ins01']['identity_mapping_history'][0]['expected_username'],'faithdjurner96')
  self.assertFalse(any(r['identity_verified'] or r['publishing_enabled'] for r in rows.values()));self.assertTrue(all(r['user_reported_logged_in'] and r['automatic_first_comment'] for r in rows.values()))
  self.assertFalse(report['browser_identity_checked_by_this_tool']);self.assertFalse(report['publication_started']);self.assertFalse(report['browser_windows_changed']);self.assertTrue(report['facebook_untouched'])
  self.assertTrue((Path(report['backup'])/'instagram_accounts-before.json').exists());self.assertEqual(len(list(self.root.glob('accounts-confirmed-by-user-*.csv'))),1)
  for p,b in self.before.items():self.assertEqual(p.read_bytes(),b)
 def test_rerun_preserves_same_username_verification_unknown_fields_and_does_not_make_new_backup(self):
  app.apply(self.root);v=self.read();v['custom']={'keep':1};v['accounts'][0].update(identity_verified=True,verified_username='ted47868',identity_verified_at='checked',login_state='verified');self.write(v);backup_count=len(list((self.root/'backups').iterdir()))
  app.apply(self.root);self.assertEqual(self.read(),v);self.assertEqual(len(list((self.root/'backups').iterdir())),backup_count)
 def test_malformed_workspace_or_profile_path_stops_before_changes(self):
  for kind in ['paths','duplicates','owner']:
   original=(self.root/'instagram_accounts.json').read_bytes();owner=(self.root/'workspace-owner.json').read_bytes();v=self.read()
   if kind=='paths':v['accounts'][0]['profile_dir']='profiles/ins02';self.write(v)
   if kind=='duplicates':v['accounts'][0]['account']='ins02';self.write(v)
   if kind=='owner':o=app.read(self.root/'workspace-owner.json');o['root']='elsewhere';app.atomic_bytes(self.root/'workspace-owner.json',app.encoded(o))
   before=(self.root/'instagram_accounts.json').read_bytes()
   with self.assertRaises(ValueError):app.apply(self.root)
   self.assertEqual((self.root/'instagram_accounts.json').read_bytes(),before);self.assertFalse((self.root/'backups').exists())
   (self.root/'instagram_accounts.json').write_bytes(original);(self.root/'workspace-owner.json').write_bytes(owner)
 def test_changed_enabled_slot_and_linked_directory_are_preserved(self):
  v=self.read();v['accounts'][0].update(publishing_enabled=True,identity_verified=True,verified_username='faithdjurner96');self.write(v);before=(self.root/'instagram_accounts.json').read_bytes()
  with self.assertRaisesRegex(ValueError,'已启用'):app.apply(self.root)
  self.assertEqual((self.root/'instagram_accounts.json').read_bytes(),before)
  v['accounts'][0]['publishing_enabled']=False;self.write(v);p=self.root/'videos/ins03/failed';p.rmdir();other=self.base/'other';other.mkdir();p.symlink_to(other,target_is_directory=True)
  with self.assertRaisesRegex(ValueError,'链接'):app.apply(self.root)
 def test_wrong_root_or_existing_fb_project_is_never_adopted(self):
  (self.root/'upload_config.json').write_text('{"facebook":"keep"}')
  with self.assertRaisesRegex(ValueError,'未接管'):app.apply(self.root)
  self.assertEqual((self.root/'upload_config.json').read_text(),'{"facebook":"keep"}')

if __name__=='__main__':unittest.main()
