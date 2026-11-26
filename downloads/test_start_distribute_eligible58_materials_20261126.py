import contextlib,hashlib,io,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import start_distribute_eligible58_materials_20261126 as app
import distribute_eligible58_materials_20261126 as driver
import test_distribute_video_materials as fixture

class StarterTests(unittest.TestCase):
 def test_embedded_runtime_matches_sources_and_no_cleanup_or_publication_entry(self):
  self.assertEqual(len(app.ADDITIONS),6)
  for n,b in app.ADDITIONS.items():self.assertEqual(Path(__file__).with_name(n).read_bytes(),b)
  self.assertFalse(any('publish_' in n or 'clean_' in n for n in app.ADDITIONS))
 def test_install_and_actual_fresh_config_probe_preserve_live_lock_and_credentials(self):
  fx=fixture.DistributionTests();fx.setUp()
  try:
   root=fx.root;(root/'.venv/Scripts').mkdir(parents=True);(root/'.venv/Scripts/python.exe').write_bytes(b'fixture');(root/'logs/upload.lock').write_text('12345')
   for name in ['fb_upload.py','add_fb_accounts.py']:(root/name).write_bytes(Path(__file__).with_name(name).read_bytes())
   real_root,folder=app.install(root);app.install(root)
   r=subprocess.run([sys.executable,'-c',app.VERIFY,str(folder),str(root)],capture_output=True,text=True,timeout=20);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
   self.assertEqual((root/'logs/upload.lock').read_text(),'12345')
   (folder/'distribute_video_materials.py').write_bytes(b'tampered')
   with self.assertRaisesRegex(ValueError,'缓存已变化'):app.install(root)
  finally:fx.doCleanups()
 def test_linked_cache_refused(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'.venv/Scripts').mkdir(parents=True);(root/'.venv/Scripts/python.exe').write_bytes(b'fixture');(root/'upload_config.json').write_text('{}');other=root/'other';other.mkdir();(root/'material-staging').symlink_to(other,target_is_directory=True)
   with self.assertRaisesRegex(ValueError,'链接'):app.install(root)
 def test_inspector_preserves_ig_process_using_fb_venv_and_blocks_foreign_fb(self):
  root=Path('/tmp/test-fb-root');runner=Path(driver.__file__).resolve()
  def row(pid,args):return dict(pid=pid,parent=1,name='python.exe',exe=str(root/'.venv/Scripts/python.exe'),command=subprocess.list2cmdline(['python',*args]),created='2026-11-26T01:00:00Z')
  rows=[row(111,[str(runner),str(root)]),row(222,['ig.py',str(root.parent/'IG-AutoUpload')]),row(333,['unknown.py',str(root)])]
  import json
  response=subprocess.CompletedProcess([],0,json.dumps(rows).encode(),b'')
  with patch.object(driver.sys,'platform','win32'),patch.object(driver.os,'getpid',return_value=111),patch.object(driver.subprocess,'run',return_value=response):self.assertEqual([r['pid'] for r in driver.inspect_workers(root)],[333])

if __name__=='__main__':unittest.main()
