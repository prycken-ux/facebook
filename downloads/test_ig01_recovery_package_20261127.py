import os,subprocess,tempfile,time,unittest,zipfile
from pathlib import Path
PWSH=Path('/workspace/.tools/fb-pwsh/pwsh');SCRIPT=Path(__file__).with_name('recover_ig01_demo_package_20261127.ps1')
@unittest.skipUnless(PWSH.exists(),'PowerShell needed')
class RecoveryTests(unittest.TestCase):
 def run_script(self,root,desktop):
  env=dict(os.environ,XDG_CACHE_HOME=str(root.parent/'cache'),XDG_CONFIG_HOME=str(root.parent/'config'),XDG_DATA_HOME=str(root.parent/'data'));r=subprocess.run([str(PWSH),'-NoProfile','-File',str(SCRIPT),'-Root',str(root),'-Desktop',str(desktop)],env=env,capture_output=True,text=True,timeout=20);return r
 def test_latest_session_packaged_without_video_or_changes_to_originals(self):
  with tempfile.TemporaryDirectory() as t:
   b=Path(t);root=b/'IG-AutoUpload';base=root/'logs/demo-recordings';old=base/('a'*32);new=base/('b'*32);old.mkdir(parents=True);new.mkdir();(old/'old.json').write_text('{}');(new/'recording.json').write_text('{"events":[]}');(new/'001.png').write_bytes(b'fixture image');(new/'movie.mp4').write_bytes(b'video');protected=root/'logs/ig-publication-state.json';protected.write_bytes(b'preserve');os.utime(old,(time.time()-60,time.time()-60));desktop=b/'ActualDesktop';desktop.mkdir();before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
   r=self.run_script(root,desktop);self.assertEqual(r.returncode,0,r.stdout+r.stderr);archive=next(desktop.glob('IG-demo-recovered-*.zip'))
   with zipfile.ZipFile(archive) as z:self.assertEqual(set(z.namelist()),{'recording.json','001.png'})
   for p,v in before.items():self.assertEqual(p.read_bytes(),v)
 def test_raw_steps_can_be_recovered_when_final_metadata_was_not_written(self):
  with tempfile.TemporaryDirectory() as t:
   b=Path(t);root=b/'IG-AutoUpload';session=root/'logs/demo-recordings'/('a'*32);session.mkdir(parents=True);(session/'001.json').write_text('{}');(session/'001.png').write_bytes(b'raw step');desktop=b/'Desktop';desktop.mkdir();r=self.run_script(root,desktop);self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('False',r.stdout)
   with zipfile.ZipFile(next(desktop.glob('*.zip'))) as z:self.assertEqual(set(z.namelist()),{'001.json','001.png'})
 def test_linked_recording_base_is_refused(self):
  with tempfile.TemporaryDirectory() as t:
   b=Path(t);root=b/'IG-AutoUpload';(root/'logs').mkdir(parents=True);foreign=b/'other';foreign.mkdir();(root/'logs/demo-recordings').symlink_to(foreign,target_is_directory=True);desktop=b/'Desktop';desktop.mkdir();r=self.run_script(root,desktop);self.assertNotEqual(r.returncode,0);self.assertEqual(list(desktop.iterdir()),[])
if __name__=='__main__':unittest.main()
