"""Reproduce the ins03 allocation stop and verify recursive total-folder handling."""
import hashlib,zipfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_ig10_workflow_20261127 import Fixture
import ig10_common_20261127 as c
import ig10_allocate_20261127 as allocation

class RecursiveAllocationTests(Fixture):
 def move_nested(self):
  child=self.source/'今天素材'/'视频';child.mkdir(parents=True)
  for i in range(3,13):(self.source/f'{i}.mp4').replace(child/f'{i}.mp4')
 def test_two_top_level_clips_plus_nested_surplus_fill_all10(self):
  self.move_nested();before={p:p.read_bytes() for p in self.source.rglob('*.mp4')};path,batch=self.plan();jobs=batch['payload']['jobs']
  self.assertEqual(len(jobs),10);self.assertEqual(jobs[2]['source_name'],'3.mp4');self.assertEqual(len({j['video_sha256'] for j in jobs}),10)
  self.assertTrue(all((self.root/j['video']).is_file() for j in jobs));self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))
  report=c.read(self.root/'logs/ig-material-scan-20261127.json');self.assertEqual(report['eligible_unique'],12)
 def test_precreated_account_folders_do_not_require_every_slot_to_have_own_source(self):
  for a in c.MAPPING:(self.source/a/'inbox').mkdir(parents=True)
  (self.source/'1.mp4').replace(self.source/'ins01/inbox/1.mp4');(self.source/'2.mp4').replace(self.source/'ins02/inbox/2.mp4')
  _,batch=self.plan();jobs=batch['payload']['jobs'];self.assertIn('ins01/inbox',Path(jobs[0]['source_video']).as_posix());self.assertIn('ins02/inbox',Path(jobs[1]['source_video']).as_posix());self.assertEqual(len(jobs),10)
 def test_existing_matching_slot_reserved_before_filling_empty_slots(self):
  slot=self.source/'ins05/inbox';slot.mkdir(parents=True)
  (self.source/'1.mp4').replace(slot/'1.mp4');_,batch=self.plan();jobs=batch['payload']['jobs'];self.assertEqual(jobs[4]['source_name'],'1.mp4');self.assertNotEqual(jobs[0]['source_name'],'1.mp4')
 def test_complete_per_slot_groups_still_preserve_account_mapping(self):
  for i,a in enumerate(c.MAPPING,1):
   p=self.source/a/'inbox';p.mkdir(parents=True);(self.source/f'{i}.mp4').replace(p/f'{i}.mp4')
  _,batch=self.plan();self.assertEqual([j['source_name'] for j in batch['payload']['jobs']],[f'{i}.mp4' for i in range(1,11)])
 def test_failure_counts_duplicates_history_and_format_and_exports_scan_without_copy(self):
  for i in range(3,13):(self.source/f'{i}.mp4').unlink()
  (self.source/'copy.mp4').write_bytes((self.source/'1.mp4').read_bytes());(self.source/'other.mkv').write_bytes(b'unsupported')
  fb=self.base/'FB-AutoUpload';payload=dict(assignments=[dict(files=[dict(name='2.mp4',sha256=hashlib.sha256((self.source/'2.mp4').read_bytes()).hexdigest())])]);c.save(fb/'logs/material-distribution/day/2026-11-26-eligible58.json',dict(payload=payload,sha256=c.digest(payload)))
  with self.assertRaisesRegex(ValueError,'当前 1 条'):self.plan()
  r=c.read(self.root/'logs/ig-material-scan-20261127.json');self.assertEqual(r['eligible_unique'],1);self.assertEqual(r['counts']['duplicate_content'],1);self.assertEqual(r['counts']['previous_fb_allocation'],1);self.assertEqual(r['counts']['unsupported_format'],1)
  self.assertFalse(list((self.root/'videos').rglob('*.mp4')));self.assertFalse((self.root/allocation.POINTER).exists())
  archive=next((self.root/'logs').glob('IG-material-scan-*.zip'))
  with zipfile.ZipFile(archive) as z:self.assertEqual(set(z.namelist()),{'ig-material-scan-20261127.json','ig-material-scan-20261127.txt'})
 def test_ig_workspace_scan_skips_credentials_history_and_links(self):
  for i in range(1,13):(self.source/f'{i}.mp4').replace(self.root/'videos/ins01/inbox'/f'{i}.mp4')
  (self.root/'profiles/ins01/secret.mp4').write_bytes(b'must not scan');(self.root/'videos/ins02/published/old.mp4').write_bytes(b'old')
  foreign=self.base/'private';foreign.mkdir();(foreign/'secret.mp4').write_bytes(b'not selected');(self.root/'videos/shortcut').symlink_to(foreign,target_is_directory=True)
  path,batch=allocation.allocate(self.root,self.root);r=c.read(self.root/'logs/ig-material-scan-20261127.json');self.assertEqual(r['video_files_seen'],12);self.assertTrue((foreign/'secret.mp4').exists());self.assertEqual(len(batch['payload']['jobs']),10)
 def test_prior_frozen_batch_resumes_unchanged_without_scanning_or_reassigning(self):
  path,batch=self.plan();before=path.read_bytes()
  with patch.object(allocation,'scan_source',side_effect=AssertionError('Existing plan must not be rescanned')):again,value=allocation.allocate(self.root)
  self.assertEqual(path,again);self.assertEqual(path.read_bytes(),before);self.assertEqual(batch,value)

if __name__=='__main__':unittest.main()
