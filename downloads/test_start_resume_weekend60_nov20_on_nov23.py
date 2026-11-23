import hashlib,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import start_resume_weekend60_nov20_on_nov23 as starter
import resume_weekend60_nov20_on_nov23 as resume

class StarterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'upload_config.json').write_text('{}');(self.root/'logs').mkdir();(self.root/'logs/upload.lock').write_bytes(b'live-task-not-touched')
        folder=self.root/'material-staging/weekend60-20261120-22-1710';folder.mkdir(parents=True);(folder/'manifest.json').write_text('{}')
        self.updates={name:b'# verified fixture module\n' for name in starter.NAMES}
        self.runner=b"import sys\nfrom pathlib import Path\nassert (Path(sys.argv[1])/'logs/upload.lock').read_bytes()==b'live-task-not-touched'\n"
        self.sha=hashlib.sha256(self.runner).hexdigest()
    def test_cache_does_not_replace_live_lock_or_root_programs(self):
        native=subprocess.run
        def run(args,**kwargs):
            if '-c' in args:return subprocess.CompletedProcess(args,0)
            return native(args,**kwargs)
        with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download',return_value=self.updates), \
             patch.object(starter,'RUNNER',self.runner),patch.object(starter,'RUNNER_SHA',self.sha),patch.object(starter.subprocess,'run',side_effect=run):
            self.assertEqual(starter.start(self.root),0)
        self.assertEqual((self.root/'logs/upload.lock').read_bytes(),b'live-task-not-touched')
        self.assertFalse((self.root/'resume_weekend60_nov20_on_nov23.py').exists())
    def test_modified_immutable_cache_is_rejected(self):
        folder=self.root/'material-staging/tools'/self.sha[:16];folder.mkdir(parents=True)
        (folder/'resume_weekend60_nov20_on_nov23.py').write_bytes(b'changed')
        with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download',return_value=self.updates), \
             patch.object(starter,'RUNNER',self.runner),patch.object(starter,'RUNNER_SHA',self.sha),patch.object(starter.subprocess,'run',side_effect=AssertionError('No process')):
            with self.assertRaisesRegex(ValueError,'同指纹'):starter.start(self.root)
    def test_embedded_runner_is_exact_reviewed_source(self):
        expected=Path(resume.__file__).read_bytes()
        self.assertEqual(starter.RUNNER,expected);self.assertEqual(starter.RUNNER_SHA,hashlib.sha256(expected).hexdigest())
    def test_bootstrap_is_exact_and_no_faked_clock(self):
        code="import hashlib,ssl,sys,urllib.request;c=ssl.create_default_context();c.minimum_version=ssl.TLSVersion.TLSv1_2;b=urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/"+'1'*40+"/downloads/start_resume_weekend60_nov20_on_nov23.py',context=c,timeout=30).read(131073);hashlib.sha256(b).hexdigest()=='"+'2'*64+"' or sys.exit('Checksum mismatch; stopped');exec(compile(b,'verified-weekend60-nov20-resume','exec'))"
        self.assertIsNotNone(resume.BOOTSTRAP.fullmatch(code))
        self.assertIsNone(resume.BOOTSTRAP.fullmatch(code+'; other_code()'))

if __name__=='__main__':unittest.main()
