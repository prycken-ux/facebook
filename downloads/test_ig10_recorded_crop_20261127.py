"""Narrow recovery for the pre-Share ratio requirement absent from the demo."""
import unittest
from pathlib import Path
from test_ig10_workflow_20261127 import Fixture
import ig10_common_20261127 as c
import ig10_engine_20261127 as engine

ERROR='未找到原始比例，未擅自裁剪上传视频'

class RecordedCropGateTests(Fixture):
 def prepare(self):
  path,batch=self.plan();job=batch['payload']['jobs'][0];folder=self.root/'logs/diagnostics/ins01-crop'
  c.save(folder/'diagnostic.json',dict(account=job['account'],username=job['username'],key=job['key'],kind='video',error=ERROR,page_url='https://www.instagram.com/'+job['username']+'/',visible_text='裁剪\n继续\n1:1\n9:16'))
  c.update(self.root,job['key'],account=job['account'],username=job['username'],video_sha256=job['video_sha256'],batch_sha256=batch['sha256'],video_status='failed_before_post',error=ERROR,identity=dict(username=job['username']),identity_verified_at=c.stamp(),selected_file=job['video'],selected_video_sha256=job['video_sha256'],browser_selected_name=Path(job['video']).name,browser_selected_size=job['video_size'],browser_file_verified_at=c.stamp(),video_file_transport='local_chrome_cdp_path',diagnostic=str(folder.relative_to(self.root)))
  gate=dict(blocked=True,passed=False,batch_sha256=batch['sha256'],job_key=job['key'],navigation_syntax_repair='old-nav',create_entry_repair='old-create',local_file_repair='old-large');return path,batch,job,gate
 def test_exact_crop_failure_has_one_audit_without_ledger_changes_or_false_success(self):
  _,batch,job,gate=self.prepare();before=(self.root/'logs/ig-publication-state.json').read_bytes();fixed=engine.recover_recorded_crop_gate(self.root,batch,gate);self.assertFalse(fixed['blocked']);self.assertFalse(fixed['passed']);self.assertEqual(fixed['local_file_repair'],'old-large');self.assertEqual(fixed['create_entry_repair'],'old-create');audit=c.checked(self.root/fixed['recorded_crop_repair']);self.assertEqual(audit['payload']['gate_before'],gate);self.assertEqual(audit['payload']['row_before'],c.state(self.root)[job['key']]);self.assertEqual((self.root/'logs/ig-publication-state.json').read_bytes(),before);again=dict(fixed,blocked=True);self.assertEqual(engine.recover_recorded_crop_gate(self.root,batch,again),again)
 def test_any_post_comment_changed_file_or_prior_ratio_selection_prevents_recovery(self):
  _,batch,job,gate=self.prepare();original=c.state(self.root)
  for field,value in [('post_intent_at',c.stamp()),('submit_click_returned_at',c.stamp()),('media_proof',{'code':'ABC'}),('comment_send_intent_at',c.stamp()),('comment_verified_at',c.stamp()),('original_ratio_selected_at',c.stamp()),('selected_video_sha256','0'*64),('browser_selected_size',job['video_size']+1),('browser_selected_name','wrong.mp4'),('identity',dict(username='other')),('video_status','needs_review'),('error','Timeout')]:
   c.update(self.root,job['key'],**{field:value});self.assertEqual(engine.recover_recorded_crop_gate(self.root,batch,gate),gate);c.save(self.root/'logs/ig-publication-state.json',original)
  c.save(self.root/'logs/ig-comment-state.json',{'test':dict(video_job=job['key'])});self.assertEqual(engine.recover_recorded_crop_gate(self.root,batch,gate),gate)
 def test_wrong_diagnostic_or_non_crop_page_keeps_gate(self):
  _,batch,job,gate=self.prepare();file=self.root/c.state(self.root)[job['key']]['diagnostic']/'diagnostic.json';original=c.read(file)
  for change in [dict(username='another'),dict(error='another error'),dict(page_url='https://www.instagram.com/another/'),dict(visible_text='编辑\n继续')]:
   c.save(file,dict(original,**change));self.assertEqual(engine.recover_recorded_crop_gate(self.root,batch,gate),gate)
 def test_refailed_trial_preserves_all_previous_repairs_and_holds_other_nine(self):
  path,batch,job,gate=self.prepare();c.save(self.root/'logs/ig-first-trial-20261127.json',gate);manifest=path.read_bytes();events=[]
  def operation(root,path,job,kind,run,status):events.append((job['account'],kind));c.update(root,job['key'],video_status='failed_before_post',error=ERROR);return 3
  self.assertEqual(engine.coordinator(self.root,path,'first',operation=operation),3);self.assertEqual(events,[('ins01','video')]);current=c.read(self.root/'logs/ig-first-trial-20261127.json');self.assertTrue(current['blocked']);self.assertTrue(current['recorded_crop_repair']);self.assertEqual(current['local_file_repair'],'old-large');engine.coordinator(self.root,path,'again',operation=operation);self.assertEqual(len(events),1);self.assertEqual(path.read_bytes(),manifest)

if __name__=='__main__':unittest.main()
