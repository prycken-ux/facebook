import contextlib,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import publication_state_io_20261127 as io
import publication_file_state_20261124 as files
import resume_nov26_after_state_error_20261127 as resume
import stage_eligible58_materials_v7 as stage

def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

class StateIOTests(unittest.TestCase):
 def test_transient_permission_is_retried_and_returns_real_data(self):
  seen=[]
  def reader(*a):
   seen.append(1)
   if len(seen)<4:raise PermissionError(13,'denied')
   return b'{"state":"started","started":100}'
  with patch.object(io.time,'sleep'):value=io.read(Path('op'),reader=reader)
  self.assertEqual(value,dict(state='started',started=100));self.assertEqual(len(seen),4)
 def test_persistent_denial_is_not_changed_to_empty_or_success(self):
  with patch.object(io,'shared_bytes',side_effect=PermissionError(13,'denied')),patch.object(io.time,'monotonic',side_effect=[0,2]):
   with self.assertRaises(PermissionError):io.read(Path('op'),default={},timeout=1)
 def test_missing_optional_operation_differs_from_required_ledger(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'absent';self.assertEqual(io.read(p,{}),{})
   with self.assertRaises(FileNotFoundError):io.read(p,required=True)
 def test_atomic_state_save_survives_replace_denial_and_keeps_payload(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'state.json';p.write_text('{"old":1}');native=Path.replace;count=[]
   def replace(source,dest):
    count.append(1)
    if len(count)<4:raise PermissionError(13,'brief share violation')
    return native(source,dest)
   with patch.object(Path,'replace',new=replace),patch.object(files.time,'sleep'):files.save(p,dict(state='finished'))
   self.assertEqual(io.read(p,required=True),dict(state='finished'));self.assertEqual(len(count),4)

class ResumeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'logs').mkdir()
  self.expected=stage.EXPECTED;self.jobs=[dict(account=a,target=t,key=f'{i:064x}',filename='20261126-fixture-'+(resume.KNOWN_SUFFIX if (a,t)==resume.KNOWN_PAIR else str(i)+'.mp4')) for i,(a,t) in enumerate(sorted(self.expected),1)]
  self.p=dict(material_date='2026-11-26',authorization='original',targets=[list(p) for p in sorted(self.expected)],ai_label=False,real_footage_confirmed=True,content_sha256='c'*64,stage_sha256='s'*64,distribution_sha256='d'*64)
  self.req=dict(payload=self.p,sha256=digest(self.p));self.request='logs/request26.json';files.save(self.root/self.request,self.req)
  self.manifest=dict(sha256='f'*64,payload=dict(queue_id=self.req['sha256'],material_source_date='2026-11-26',jobs=self.jobs));files.save(self.root/'logs/frozen.json',self.manifest)
  self.control=dict(request_sha256=self.req['sha256'],waves=[dict(manifest='frozen.json',sha256='f'*64)]);files.save(self.root/'logs'/('eligible58-real-publication-'+self.req['sha256'][:16]+'.json'),self.control)
  self.state={j['key']:dict(account=j['account'],target=j['target'],status='published',post_intent_at='2026-11-26T10:00:00Z') for j in [j for j in self.jobs if (j['account'],j['target'])!=resume.KNOWN_PAIR][:28]};files.save(self.root/'logs/publish_state.json',self.state)
  self.native=[]
  self.first=N(batch=N(digest=digest,validate_job=lambda *a,**k:None),archive=N(checked_json=lambda p:json.loads(p.read_text())),upload=N(run_entry=lambda *a,**k:self.native.append(k)))
  def safe(root,p):p.resolve().relative_to(root.resolve());return p
  self.app=N(EXPECTED=self.expected,stage=N(safe_child=safe),run_phase=lambda *a,**k:None)
  self.day=N(REQUEST=self.request,AUTH='original',CONTENT_SHA='c'*64,first=self.first,app=self.app,allocation=lambda r:(None,dict(sha256='s'*64),None,dict(sha256='d'*64)))
 def test_original28_and_explicit_posted_page09_are_protected_with29_remaining(self):
  proof,_=resume.audit(self.day,self.root,quiet=True);self.assertEqual(len(proof['protected_keys']),29);self.assertEqual(len(proof['remaining_unsubmitted_keys']),29);self.assertIn(proof['known_post_click_key'],proof['protected_keys'])
 def test_missing_or_weakened_ledger_never_becomes_all_not_started(self):
  p=self.root/'logs/publish_state.json';p.unlink()
  with self.assertRaises(FileNotFoundError):resume.audit(self.day,self.root)
  files.save(p,{})
  with self.assertRaisesRegex(ValueError,'28项'):resume.audit(self.day,self.root)
 def test_other_day_or_source_refused_without_creating_new_request(self):
  self.day.allocation=lambda r:(None,dict(sha256='wrong'),None,dict(sha256='d'*64))
  with self.assertRaisesRegex(ValueError,'来源变化'):resume.audit(self.day,self.root)
 def test_upload_guard_prevents_old_published_unknown_and_known_posted_key(self):
  with contextlib.redirect_stdout(__import__('io').StringIO()),resume.installed(self.day,self.root):
   old=next(iter(self.state));known=next(j['key'] for j in self.jobs if (j['account'],j['target'])==resume.KNOWN_PAIR)
   for key in [old,known]:
    with self.assertRaisesRegex(RuntimeError,'禁止再次'):self.first.upload.run_entry({},expected_job_key=key)
   fresh=next(j['key'] for j in self.jobs if j['key'] not in self.state and j['key']!=known);self.first.upload.run_entry({},expected_job_key=fresh)
   self.assertEqual(len(self.native),1)
   state=resume.ledger(self.root);state[fresh]=dict(status='failed_before_post',nested=dict(post_intent_at='just clicked'));files.save(self.root/'logs/publish_state.json',state)
   with self.assertRaises(RuntimeError):self.first.upload.run_entry({},expected_job_key=fresh)
  self.assertEqual(len(self.native),1)



class RealPipelineResumeTests(unittest.TestCase):
 def test_partial_batch_next_day_submits_only29_never_posted_targets(self):
  import test_publish_eligible58_real_20261126 as fixture
  fx=fixture.Nov26PublicationTests();fx.setUp();self.addCleanup(fx.doCleanups);fx.core(unknown=True)
  day=fixture.current;root=fx.root;req=day.first.upload.read_json(root/day.REQUEST,{})
  control_path=root/'logs'/('eligible58-real-publication-'+req['sha256'][:16]+'.json');control=day.first.upload.read_json(control_path,{})
  manifests=[(root/'logs'/w['manifest'],day.first.archive.checked_json(root/'logs'/w['manifest'])) for w in control['waves']];jobs=[j for path,m in manifests for j in m['payload']['jobs']];self.assertEqual(len(jobs),58)
  known=next(j for j in jobs if (j['account'],j['target'])==resume.KNOWN_PAIR)
  kept=[j for j in jobs if j['key']!=known['key']][:28];protected={j['key'] for j in kept}|{known['key']};state_path=root/'logs/publish_state.json';state=day.first.upload.read_json(state_path,{})
  for j in jobs:
   if j['key'] not in protected:state.pop(j['key'],None)
   else:state[j['key']]['comment_status']='deferred'
  state[known['key']].update(status='posting',post_intent_at='2026-11-26T11:13:00+00:00')
  day.first.upload.save_json(state_path,state)
  for manifest_path,manifest in manifests:
   result_path=manifest_path.with_name(manifest_path.stem+'-results.json');result=day.first.upload.read_json(result_path,{})
   result['attempts']=[a for a in result['attempts'] if a['key'] in protected];day.first.upload.save_json(result_path,result)
  fx.runfx.now=__import__('datetime').datetime(2026,11,27,2,tzinfo=__import__('datetime').timezone.utc)
  for clock in fx.runfx.clocks:clock.now.return_value=fx.runfx.now
  proof=dict(protected_keys=sorted(protected));by_key={j['key']:j for j in jobs}
  with patch.object(resume,'audit',return_value=(proof,by_key)),resume.installed(day,root):result,events,_,calls=fx.core(unknown=True)
  posts=[pair for name,pair in events if name=='post'];self.assertEqual(len(posts),29);self.assertEqual(set(posts),{(j['account'],j['target']) for j in jobs if j['key'] not in protected})
  self.assertNotIn(resume.KNOWN_PAIR,posts);self.assertNotIn(resume.KNOWN_PAIR,calls)

if __name__=='__main__':unittest.main()

class WindowsSharingTests(unittest.TestCase):
 def test_win32_reader_requests_read_write_delete_sharing_and_closes_handle(self):
  import ctypes
  from unittest.mock import MagicMock
  kernel=MagicMock();kernel.CreateFileW.return_value=123;calls=[]
  def read(handle,buffer,length,count,overlapped):
   calls.append(1);data=b'{"ok":true}' if len(calls)==1 else b''
   if data:ctypes.memmove(buffer,data,len(data))
   count._obj.value=len(data);return True
  kernel.ReadFile.side_effect=read
  with patch.object(io.sys,'platform','win32'),patch.object(ctypes,'WinDLL',return_value=kernel,create=True):value=io.shared_bytes(Path('state.json'),100)
  self.assertEqual(value,b'{"ok":true}');self.assertEqual(kernel.CreateFileW.call_args.args[2],7);kernel.CloseHandle.assert_called_once_with(123)
