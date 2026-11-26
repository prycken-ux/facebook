import copy,hashlib,json,subprocess,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import distribute_eligible58_materials_20261126 as app
import test_distribute_video_materials as fixture

class AllocationTests(unittest.TestCase):
 def setUp(self):
  self.fx=fixture.DistributionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root;self.pool=self.fx.pool;self.fx.videos(count=60)
  self.clock=self.enterContext(patch.object(app.stage,'datetime',wraps=datetime));self.clock.now.return_value=datetime(2026,11,26,5,tzinfo=timezone.utc)
  self.enterContext(patch.object(app.recovery,'recover_locks'));self.live=self.enterContext(patch.object(app,'inspect_workers',return_value=[]))
  self.enterContext(patch.object(app.stage.upload,'run_entry',side_effect=AssertionError('Allocation must not publish')))
  self.originals={p:p.read_bytes() for p in self.pool.iterdir()};self.state=(self.root/'logs/publish_state.json').read_bytes()
 def rows(self):
  pointer=app.stage.upload.read_json(self.root/app.POINTER,{});path=self.root/pointer['manifest'];return path,app.stage.upload.read_json(path,{})['payload']['distribution']['payload']['assignments']
 def test_exact58_in38_accounts_skip36_natural_order_preserve_sources_and_ledgers(self):
  (self.pool/'1.txt').write_text('caption');(self.pool/'1.comment.txt').write_text('first comment')
  held=[]
  for account in ['fb32','fb52','fb17']:
   p=self.root/'videos'/account/'personal/inbox/old.mp4';p.parent.mkdir(parents=True);p.write_bytes(b'keep');held.append(p)
  self.assertEqual(app.execute(self.root,self.pool),0);path,rows=self.rows();self.assertEqual(len(rows),58);self.assertEqual(len({r['account'] for r in rows}),38);self.assertEqual({(r['account'],r['target']) for r in rows},app.EXPECTED)
  self.assertEqual([r['video_filename'] for r in rows],[f'{i}.mp4' for i in range(1,59)]);self.assertFalse({r['account'] for r in rows}&app.UNAVAILABLE);self.assertEqual(len(app.UNAVAILABLE),36)
  self.assertEqual(sum(r['target']=='personal' for r in rows),32);self.assertEqual(sum(r['target'].startswith('page') for r in rows),26)
  for r in rows:
   for f in r['files']:self.assertEqual((app.stage.materials.safe_inbox(r['account'],r['target'])/f['destination_name']).read_bytes(),(self.pool/f['name']).read_bytes());self.assertTrue(f['destination_name'].startswith('20261126-'))
  for p,b in self.originals.items():self.assertEqual(p.read_bytes(),b)
  for p in held:self.assertEqual(p.read_bytes(),b'keep')
  self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),self.state);self.assertTrue((path.parent/'分配完成清单.txt').exists())
 def test_old60_manifests_and_pointers_remain_and_renamed_previous_content_is_excluded(self):
  old=app.stage.legacy_stage;pool=self.root/'old';pool.mkdir()
  for i in range(60):(pool/f'{i}.mp4').write_bytes(('prior25 '+str(i)).encode())
  path,value=old.prepare(self.root,pool);pointer=self.root/'material-staging/eligible60-20261125-pending-import.json';old.upload.save_json(pointer,dict(manifest=str(path.relative_to(self.root)),sha256=value['sha256'],complete=True));before={p:p.read_bytes() for p in [path,pointer]}
  (self.pool/'0.mp4').write_bytes((pool/'0.mp4').read_bytes());app.execute(self.root,self.pool);_,rows=self.rows();self.assertNotIn('0.mp4',[r['video_filename'] for r in rows])
  for p,b in before.items():self.assertEqual(p.read_bytes(),b)
 def test_short_source_does_not_poison_next_pick_or_copy_to_accounts(self):
  for i in range(58,61):(self.pool/f'{i}.mp4').unlink()
  with self.assertRaisesRegex(ValueError,'新素材只有57'):app.execute(self.root,self.pool)
  self.assertFalse((self.root/app.POINTER).exists());self.assertFalse(list((self.root/'videos').rglob('*.mp4')))
  (self.pool/'58.mp4').write_bytes(b'new58');self.assertEqual(app.execute(self.root,self.pool),0)
 def test_resume_interrupted_staging_uses_same_manifest_and_never_reshuffles(self):
  native=app.stage.materials.copy_exact
  def interrupt(*a):native(*a);raise OSError('interrupted')
  with patch.object(app.stage.materials,'copy_exact',side_effect=interrupt),self.assertRaises(OSError):app.execute(self.root,self.pool)
  path,_=self.rows();before=path.read_bytes();(self.pool/'0.mp4').write_bytes(b'new arrival');self.clock.now.return_value=datetime(2026,11,27,5,tzinfo=timezone.utc)
  with patch.object(app.stage.materials,'choose_source',side_effect=AssertionError('No new selection')):self.assertEqual(app.execute(self.root),0)
  self.assertEqual(path.read_bytes(),before)
 def test_replay_completed_allocation_does_not_refill_moved_video(self):
  app.execute(self.root,self.pool);_,rows=self.rows();r=rows[0];p=app.stage.materials.safe_inbox(r['account'],r['target'])/r['files'][-1]['destination_name'];p.unlink();app.execute(self.root);self.assertFalse(p.exists())
 def test_today_plan_cannot_be_replaced_by_different_source(self):
  app.execute(self.root,self.pool);path,_=self.rows();before=path.read_bytes()
  with self.assertRaisesRegex(ValueError,'已有分配指针'):app.execute(self.root,self.root/'other')
  self.assertEqual(path.read_bytes(),before)
 def test_late_pause_and_owner_change_block_import(self):
  original_prepare=app.stage.prepare
  def prepare_pause(*a,**k):
   value=original_prepare(*a,**k);p=dict(schema='publication-account-exclusions-v1',excluded_accounts=sorted(app.UNAVAILABLE|{'fb45'}));app.stage.upload.save_json(self.root/'publication_account_exclusions.json',dict(payload=p,sha256=app.stage.materials.digest(p)));return value
  with patch.object(app.stage,'prepare',side_effect=prepare_pause),self.assertRaisesRegex(ValueError,'暂停名单已扩大'):app.execute(self.root,self.pool)
  self.assertFalse(list((self.root/'videos').rglob('*.mp4')))
 def test_new_allocation_requires_today_and_ig_source_is_rejected(self):
  self.clock.now.return_value=datetime(2026,11,27,5,tzinfo=timezone.utc)
  with self.assertRaisesRegex(ValueError,'首次分配'):app.execute(self.root,self.pool)
  self.clock.now.return_value=datetime(2026,11,26,5,tzinfo=timezone.utc);ig=self.root/'IG-AutoUpload/素材';ig.mkdir(parents=True)
  with self.assertRaisesRegex(ValueError,'Instagram'):app.execute(self.root,ig)
 def test_other_project_worker_blocks_before_staging(self):
  self.live.return_value=[dict(pid=444)]
  with self.assertRaisesRegex(RuntimeError,'444'):app.execute(self.root,self.pool)
  self.assertFalse((self.root/app.POINTER).exists())
 def test_venv_bootstrap_chain_exempts_own_launch_but_not_second_launch(self):
  from test_nov16_venv_process_chain import VenvProcessChainTests
  f=VenvProcessChainTests();f.setUp();rows=copy.deepcopy(f.rows)
  body=f.body.replace('start_finish_first24_nov16','start_distribute_eligible58_materials_20261126').replace('verified-nov16-first24-and-nov14-stage','verified-nov26-eligible58-material-distribution')
  for r in rows[2:]:r['command']=subprocess.list2cmdline([f.exe,'-u','-c',body,f.root])
  rows.append(f.row(101,1,f.run_args))
  with patch.object(app.workers,'BOOTSTRAP',app.BOOTSTRAP):live,allowed=app.workers.classify_workers(rows,f.root,100,f.runner)
  self.assertEqual(allowed,[97,98,99,100]);self.assertEqual([r['pid'] for r in live],[101])

if __name__=='__main__':unittest.main()
