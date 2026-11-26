import ast,base64,hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import start_publish_guarded_nov26_20261126 as starter
import publish_eligible58_real_20261126 as day

class StarterTests(unittest.TestCase):
 def test_embedded_overlay_matches_sources_and_is_fixed_hash(self):
  for n,b in starter.ADDITIONS.items():self.assertEqual(Path(__file__).with_name(n).read_bytes(),b,n)
  manifest={n:hashlib.sha256(b).hexdigest() for n,b in starter.ADDITIONS.items()};self.assertEqual(hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest(),starter.FINGERPRINT)
  self.assertLessEqual(Path(starter.__file__).stat().st_size,131072)
 def test_live_progress_is_powershell_not_another_fb_python_worker(self):
  with patch.object(starter.subprocess,'Popen') as popen:starter.open_progress(Path(r'E:\FB-AutoUpload'))
  args=popen.call_args.args[0];self.assertEqual(args[0],'powershell.exe');self.assertIn('-EncodedCommand',args)
  command=base64.b64decode(args[-1]).decode('utf-16le');self.assertIn('Get-Content',command);self.assertIn('eligible58-2026-11-26-run.log',command);self.assertIn('-Wait',command);self.assertNotIn('Stop-Process',command)
 def test_today_origin_confirmation_is_required_before_publication(self):
  with patch.object(day,'REAL_CONFIRMED',False),patch.object(day.app,'execute') as execute:
   with self.assertRaisesRegex(ValueError,'实拍'):day.execute(Path('/tmp'))
   execute.assert_not_called()

if __name__=='__main__':unittest.main()
