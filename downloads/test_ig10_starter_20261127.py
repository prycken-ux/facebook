import importlib.util,os,subprocess,sys,unittest
from pathlib import Path
from test_ig10_workflow_20261127 import Fixture
import build_ig10_starter_20261127 as builder

class StarterTests(Fixture):
 def setUp(self):
  super().setUp();self.entry=builder.build();spec=importlib.util.spec_from_file_location('ig_capsule',self.entry);self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
 def test_embedded_bytes_match_all_reviewed_sources_and_cache_is_immutable(self):
  cache=self.module.unpack(self.root)
  for name in builder.NAMES:self.assertEqual((cache/name).read_bytes(),(builder.HERE/name).read_bytes())
  p=cache/'ig10_engine_20261127.py';p.write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'checksum mismatch'):self.module.unpack(self.root)
  self.assertEqual(p.read_bytes(),b'changed')
 def test_fresh_process_probe_validates_existing_mapping_without_allocation_or_browser(self):
  marker=self.root/'profiles/ins01/keep-login';marker.write_bytes(b'keep session');before=(self.root/'instagram_accounts.json').read_bytes()
  result=subprocess.run([sys.executable,str(self.entry),str(self.root)],env=dict(os.environ,IG10_PROBE_ONLY='1'),capture_output=True,text=True,timeout=20)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('IG10 VERIFIED',result.stdout);self.assertFalse(list((self.root/'videos').rglob('*.mp4')));self.assertEqual(marker.read_bytes(),b'keep session');self.assertEqual(before,(self.root/'instagram_accounts.json').read_bytes())
 def test_linked_cache_refused_before_writing_elsewhere(self):
  outside=self.base/'foreign';outside.mkdir()
  if (self.root/'tools').exists():(self.root/'tools').rmdir()
  (self.root/'tools').symlink_to(outside,target_is_directory=True)
  with self.assertRaisesRegex(ValueError,'Linked tool cache'):self.module.unpack(self.root)
  self.assertEqual(list(outside.iterdir()),[])

if __name__=='__main__':unittest.main()
