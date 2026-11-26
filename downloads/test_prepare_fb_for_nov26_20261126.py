import hashlib,json,os,subprocess,unittest
from pathlib import Path
from unittest.mock import patch
import prepare_fb_for_nov26_20261126 as app
import clean_pre_nov26_materials_20261126 as cleanup
import test_distribute_video_materials as fixture

class PreparationTests(unittest.TestCase):
 def setUp(self):
  self.fx=fixture.DistributionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
  self.enterContext(patch.object(cleanup.workers,'active_workers',return_value=[]));self.enterContext(patch.object(cleanup.recovery,'recover_locks'))
 def file(self,name,data=b'old'):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
 def test_no_pointer_deletes25_preserves26_unknown_profiles_ledgers_and_ig(self):
  old=self.file('videos/fb01/page01/inbox/20261125-1234abcd-eligible60-old.mp4')
  kept=[self.file(n,n.encode()) for n in ['videos/fb01/page01/inbox/20261126-1234abcd-eligible58-new.mp4','videos/fb01/page01/inbox/2026-01-01-camera.mp4','profiles/fb01/Default/Login Data','logs/video_comments.json','Instagram/ins01/20261125-1234abcd-eligible60-clip.mp4']]
  key='a'*64;cleanup.save(self.root/'logs/publish_state.json',{key:dict(video=str(old),status='needs_review',post_intent_at='original',comment_status='lookup_pending')})
  cleanup.execute(self.root);self.assertFalse(old.exists())
  for p in kept:self.assertEqual(p.read_bytes(),str(p.relative_to(self.root)).encode())
  state=cleanup.read(self.root/'logs/publish_state.json')[key];self.assertEqual(state['publication_status_before_user_archive'],'needs_review');self.assertEqual(state['post_intent_at'],'original');self.assertTrue(state['comment_retry_disabled'])
 def distribution(self,day,source):
  p=dict(date=day,source=str(source),assignments=[dict(account='fb01',target='page01',files=[dict(name='clip.mp4',destination_name=day.replace('-','')+'-1234abcd-eligible58-old.mp4',size=3,sha256=hashlib.sha256(b'old').hexdigest())])])
  (self.root/'logs/material-distribution/fixture').mkdir(parents=True,exist_ok=True);cleanup.save(self.root/('logs/material-distribution/fixture/'+day+'-eligible58.json'),dict(payload=p,sha256=cleanup.media.digest(p)))
 def test_signed_external_source_deletes_fb_copy_but_never_instagram(self):
  source=self.root/'IG-AutoUpload/videos/ins01/inbox';source.mkdir(parents=True);(source/'clip.mp4').write_bytes(b'old');self.distribution('2026-11-25',source)
  old=self.file('videos/fb01/page01/inbox/20261125-1234abcd-eligible58-old.mp4');cleanup.execute(self.root);self.assertFalse(old.exists());self.assertTrue((source/'clip.mp4').exists())
 def test_future_signed_hash_protects_same_bytes_and_bad_current_pointer_blocks(self):
  old=self.file('videos/fb01/page01/inbox/20261125-1234abcd-eligible60-old.mp4');self.distribution('2026-11-26',self.root/'future');cleanup.execute(self.root);self.assertTrue(old.exists())
  (self.root/'material-staging').mkdir(exist_ok=True);cleanup.save(self.root/'material-staging/eligible60-20261126-pending-import.json',dict(manifest='missing',sha256='a'*64))
  with self.assertRaises((ValueError,OSError)):cleanup.execute(self.root)
  self.assertTrue(old.exists())
 def test_hardlinked_video_retained(self):
  old=self.file('videos/fb01/page01/inbox/20261125-1234abcd-eligible60-old.mp4');os.link(old,self.root/'another.mp4');cleanup.execute(self.root);self.assertTrue(old.exists())
 def row(self,pid,args):return dict(pid=pid,parent=1,name='python.exe',exe=str(self.root/'.venv/Scripts/python.exe'),command=subprocess.list2cmdline(['python',*args]),created='2026-11-26T01:00:00Z')
 def snapshot(self,extra=(),tasks=()):return dict(processes=[self.row(100,[str(Path(app.__file__)),str(self.root)]),*extra],tasks=list(tasks))
 def test_old_resume_filename26_is_source25_and_ig_is_preserved(self):
  p=self.file('material-staging/tools/old/resume18_target_watchdog_20261126.py',b'fixture');known=[dict(name=p.name,sha256=hashlib.sha256(b'fixture').hexdigest(),material_date='2026-11-25')]
  result=app.plan(self.root,self.snapshot([self.row(101,['-u',str(p),str(self.root)]),self.row(102,['ig.py',str(self.root.parent/'IG-AutoUpload')])]),known,pid=100)
  self.assertEqual([r['pid'] for r in result['stop']],[101]);self.assertIn(102,[r['pid'] for r in result['allowed']])
 def test_unknown_or_current_worker_aborts(self):
  p=self.file('material-staging/tools/new/new.py',b'fixture');r=self.row(101,[str(p),str(self.root)])
  for known in [[],[dict(name=p.name,sha256=hashlib.sha256(b'fixture').hexdigest(),material_date='2026-11-26')]]:
   with self.assertRaisesRegex(ValueError,'101'):app.plan(self.root,self.snapshot([r]),known,pid=100)
 def test_mixed_task_not_disabled(self):
  p=self.file('material-staging/tools/old/queue.ps1',b'fixture');known=[dict(name=p.name,sha256=hashlib.sha256(b'fixture').hexdigest(),material_date='2026-11-25')]
  action=dict(execute='powershell.exe',arguments=subprocess.list2cmdline(['-File',str(p),'-Root',str(self.root)]),working=str(self.root));task=dict(name='old',path='/',actions=[action]);mixed=dict(name='mixed',path='/',actions=[action,dict(execute='cmd.exe',arguments='other',working='')])
  result=app.plan(self.root,self.snapshot(tasks=[task,mixed]),known,pid=100);self.assertEqual([t['name'] for t in result['tasks']],['old']);self.assertEqual([t['name'] for t in result['retained_tasks']],['mixed'])
 def test_frozen_source_day_precedes_execution_day(self):
  p=dict(date='2026-11-26',material_source_date='2026-11-25',jobs=[]);sha=cleanup.media.digest(p);path=self.root/'logs'/('frozen-material-2026-11-26-'+sha[:16]+'.json');cleanup.save(path,dict(payload=p,sha256=sha));self.assertEqual(app.manifest_date(self.root,str(path)),'2026-11-25')
 def test_failed_window_preparation_never_cleans_or_changes_settings(self):
  with patch.object(app,'snapshot',return_value=self.snapshot()),patch.object(app,'plan',return_value={'stop':[],'tasks':[],'retained_tasks':[]}),patch.object(app,'windows_prepare',side_effect=RuntimeError('visible window')),patch.object(app.disabled,'apply') as disable,patch.object(cleanup,'execute') as clean:
   with self.assertRaises(RuntimeError):app.execute(self.root)
   disable.assert_not_called();clean.assert_not_called()


class InstallerTests(unittest.TestCase):
 def test_exact_bundle_immutable_install_and_probe(self):
  import tempfile
  import start_prepare_fb_for_nov26_20261126 as installer
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/'FB-AutoUpload';(root/'.venv/Scripts').mkdir(parents=True);(root/'upload_config.json').write_text('{}');(root/'.venv/Scripts/python.exe').write_bytes(b'fixture')
   installed,folder=installer.install(root);self.assertEqual(installed,root)
   for n,b in installer.ADDITIONS.items():self.assertEqual((folder/n).read_bytes(),b);self.assertEqual(b,Path(__file__).with_name(n).read_bytes())
   installer.install(root)
   # Load the complete installed runtime in an isolated process with project stubs.
   (root/'fb_upload.py').write_text('from pathlib import Path\nROOT=Path(__file__).parent\n')
   (root/'add_fb_accounts.py').write_text('from contextlib import nullcontext\nlocked=nullcontext\n')
   import sys
   r=subprocess.run([sys.executable,'-c',installer.VERIFY,str(folder),str(root)],capture_output=True,text=True,timeout=15);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
   (folder/'prepare_fb_windows_20261126.ps1').write_bytes(b'tampered')
   with self.assertRaisesRegex(ValueError,'变化'):installer.install(root)
 def test_linked_cache_refused(self):
  import tempfile
  import start_prepare_fb_for_nov26_20261126 as installer
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/'FB-AutoUpload';(root/'.venv/Scripts').mkdir(parents=True);(root/'upload_config.json').write_text('{}');(root/'.venv/Scripts/python.exe').write_bytes(b'fixture');other=Path(temp)/'other';other.mkdir();(root/'material-staging').symlink_to(other,target_is_directory=True)
   with self.assertRaisesRegex(ValueError,'链接'):installer.install(root)

if __name__=='__main__':unittest.main()
