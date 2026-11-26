import contextlib,hashlib,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import nov26_comment_gate as gate
import nov26_publication_preflight as preflight
import safe_video_comments as comments
import test_publication_target_watchdog_20261126 as watchdog_fixture

class GateTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.key='a'*64;self.text='original exact comment';self.link='https://www.facebook.com/reel/123456789/'
  self.item=dict(account='fb01',target='page01',video_job=self.key,text_sha256=comments.text_hash(self.text),status='sent',verification='own_comment_seen_after_reload',verified_at='2026-11-26T01:00:00Z',permalink=self.link)
  self.row=dict(account='fb01',target='page01',comment_status='sent',permalink=self.link)
  self.ledger_key=hashlib.sha256((self.key+'\0'+comments.text_hash(self.text)).encode()).hexdigest()
  def read(path,default):return {self.key:self.row} if Path(path).name=='publish_state.json' else {self.ledger_key:self.item}
  self.first=N(priority=N(daily=N(comments=comments)),upload=N(read_json=read))
 def test_reload_proof_must_bind_job_actor_comment_and_video(self):
  self.assertTrue(gate.verified(self.first,self.root,self.key,self.text))
  for field,changed in [('account','fb02'),('target','personal'),('video_job','b'*64),('verification','clicked_only'),('status','verifying'),('text_sha256','wrong'),('permalink','https://www.facebook.com/reel/99999999/')]:
   old=self.item[field];self.item[field]=changed;self.assertFalse(gate.verified(self.first,self.root,self.key,self.text),field);self.item[field]=old
 def test_failed_first_comment_blocks_later_jobs_in_same_and_retry_phases(self):
  fx=watchdog_fixture.WorkerGuardTests();fx.setUp();self.addCleanup(fx.doCleanups)
  with patch.object(gate,'verified',return_value=False):fx.phase()
  self.assertEqual(fx.events,[('comment',{'a'})]);fx.phase('comment_retry');self.assertEqual(fx.events,[('comment',{'a'})])
  self.assertTrue(watchdog_fixture.w.read(fx.progress)['comment_gate']['blocked'])
 def test_failed_gate_exports_only_scoped_diagnostics_without_changing_video_state(self):
  raw=self.root/'logs/publish_state.json';raw.write_text('{"keep":"all"}')
  with contextlib.redirect_stdout(__import__('io').StringIO()):value=gate.save_result(self.first,self.root,'f'*64,dict(key=self.key,account='fb01',target='page01'),False,'first field missing')
  self.assertTrue(value['blocked']);self.assertEqual(raw.read_text(),'{"keep":"all"}');self.assertTrue(list((self.root/'logs').glob('FB-Nov26-comment-diagnostic-*.zip')))

class PreflightTests(unittest.TestCase):
 def test_occupied_fb_profile_is_reported_before_any_browser_is_opened(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'logs').mkdir();rows=[dict(account='fb01',pid=123,created='2026-11-26T01:00:00Z')]
   response=N(returncode=0,stdout=json.dumps(rows).encode())
   with patch.object(preflight.subprocess,'run',return_value=response),self.assertRaisesRegex(RuntimeError,'fb01 PID 123'):preflight.require_profiles_free(root,{'fb01','fb02'})
   report=json.loads((root/'logs/nov26-profile-preflight.json').read_text());self.assertTrue(report['instagram_untouched']);self.assertEqual(report['occupied'],rows)
 def test_malformed_or_foreign_profile_response_is_not_accepted_as_free(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   for rows in [[dict(account='ins01',pid=1,created='date')],{}]:
    with patch.object(preflight.subprocess,'run',return_value=N(returncode=0,stdout=json.dumps(rows).encode())),self.assertRaises(ValueError):preflight.require_profiles_free(root,{'fb01'})

if __name__=='__main__':unittest.main()
