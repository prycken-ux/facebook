"""The user's batch-level FB reuse authorization must not weaken IG ledgers."""
import hashlib,unittest
from pathlib import Path
from unittest.mock import patch
from test_ig10_workflow_20261127 import Fixture
import ig10_common_20261127 as c
import ig10_allocate_20261127 as allocation
import ig10_engine_20261127 as engine

class FBReuseTests(Fixture):
 def fb_records(self,valid=True):
  fb=self.base/'FB-AutoUpload';path=fb/'logs/material-distribution/day/2026-11-26-eligible58.json'
  payload=dict(assignments=[dict(files=[dict(name=f'{i}.mp4',sha256=hashlib.sha256((self.source/f'{i}.mp4').read_bytes()).hexdigest()) for i in range(1,11)])])
  c.save(path,dict(payload=payload,sha256=c.digest(payload)));before=path.read_bytes()
  if not valid:path.write_bytes(b'incomplete unrelated FB report')
  return fb,path,path.read_bytes()
 def test_screenshot12_files_including10_fb_history_now_allocate_all10(self):
  fb,p,before=self.fb_records();original=c.checked
  def checked(path):
   self.assertFalse(Path(path).is_relative_to(fb),'FB data should not be read for this allocation');return original(path)
  with patch.object(c,'checked',side_effect=checked):path,batch=self.plan()
  self.assertEqual(len(batch['payload']['jobs']),10);self.assertEqual([j['source_name'] for j in batch['payload']['jobs']],[f'{i}.mp4' for i in range(1,11)]);self.assertEqual(p.read_bytes(),before)
  r=c.read(self.root/'logs/ig-material-scan-20261127.json');self.assertEqual(r['video_files_seen'],12);self.assertEqual(r['eligible_unique'],12);self.assertFalse(r['fb_history_filter_enabled']);self.assertEqual(r['fb_material_reuse_authorization'],allocation.FB_REUSE_AUTH)
  self.assertEqual(batch['payload']['fb_material_reuse'],dict(allowed=True,authorization=allocation.FB_REUSE_AUTH))
 def test_unreadable_or_invalid_fb_history_does_not_block_ig(self):
  fb,p,before=self.fb_records(False);self.plan();self.assertEqual(p.read_bytes(),before)
 def test_ig_allocation_fingerprints_remain_excluded(self):
  sha=hashlib.sha256((self.source/'1.mp4').read_bytes()).hexdigest();payload=dict(jobs=[dict(video_sha256=sha)]);p=self.root/'material-staging/2026-11-26/previous/manifest.json';c.save(p,dict(payload=payload,sha256=c.digest(payload)));before=p.read_bytes()
  self.fb_records();path,batch=self.plan();self.assertEqual([j['source_name'] for j in batch['payload']['jobs']],[f'{i}.mp4' for i in range(2,12)]);self.assertEqual(p.read_bytes(),before)
 def test_ig_submitted_video_and_uncertain_comment_remain_protected(self):
  self.fb_records();sha=hashlib.sha256((self.source/'1.mp4').read_bytes()).hexdigest();key=c.digest(dict(platform='instagram',account='ins01',username=c.MAPPING['ins01'],video_sha256=sha,caption=c.CAPTION))
  c.update(self.root,key,account='ins01',username=c.MAPPING['ins01'],video_sha256=sha,post_intent_at=c.stamp(),submit_click_returned_at=c.stamp(),video_status='needs_review',comment_send_intent_at=c.stamp(),comment_status='needs_review')
  comment_key=c.digest(dict(video_job=key,text=c.COMMENT));c.save(self.root/'logs/ig-comment-state.json',{comment_key:dict(status='sending',video_job=key,send_intent_at=c.stamp())})
  state_before=(self.root/'logs/ig-publication-state.json').read_bytes();comments_before=(self.root/'logs/ig-comment-state.json').read_bytes();path,batch=self.plan();self.assertEqual((self.root/'logs/ig-publication-state.json').read_bytes(),state_before);self.assertEqual((self.root/'logs/ig-comment-state.json').read_bytes(),comments_before)
  first=batch['payload']['jobs'][0];self.assertEqual(first['key'],key);self.assertFalse((self.root/first['video']).exists())
  events=[]
  def operation(root,path,j,kind,run,status):
   events.append((j['account'],kind));self.assertEqual(kind,'comment');self.assertTrue(c.state(root)[key]['comment_send_intent_at']);return 3
  self.assertEqual(engine.coordinator(self.root,path,'reuse-test',operation=operation),3);self.assertEqual(events,[('ins01','comment')]);self.assertEqual((self.root/'logs/ig-comment-state.json').read_bytes(),comments_before)
 def test_old_frozen_manifest_without_reuse_field_remains_valid_and_unmodified(self):
  path,batch=self.plan();batch['payload'].pop('fb_material_reuse');batch['sha256']=c.digest(batch['payload']);c.save(path,batch);pointer=c.read(self.root/allocation.POINTER);pointer['sha256']=batch['sha256'];c.save(self.root/allocation.POINTER,pointer);before=path.read_bytes()
  with patch.object(allocation,'scan_source',side_effect=AssertionError('Frozen source must not be replaced')):again,_=allocation.allocate(self.root)
  self.assertEqual(path,again);self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
