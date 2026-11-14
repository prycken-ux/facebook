import hashlib,io,subprocess,sys,tempfile,unittest,zipfile
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
import start_publish_staged_first24_nov14 as app


class StagedPublishStartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'upload_config.json').write_text('{"targets":[]}');(self.root/'logs').mkdir();(self.root/'logs/upload.lock').write_bytes(b'live-original-publisher')
        self.updates={name:b'# fixture helper\n' for name in app.NAMES}
        self.updates[app.NAMES[0]]=b"import sys\nfrom pathlib import Path\nassert len(sys.argv)==3 and sys.argv[-1]=='--real-footage'\nassert (Path(sys.argv[1])/'logs/upload.lock').read_bytes()==b'live-original-publisher'\n"
    def test_cache_and_child_do_not_acquire_or_replace_live_original_upload_lock(self):
        real_run=subprocess.run
        def run(args,**kwargs):
            if '-c' in args:return subprocess.CompletedProcess(args,0)
            return real_run(args,**kwargs)
        with patch.object(app.sys,'platform','win32'),patch.object(app,'datetime',wraps=datetime) as clock,patch.object(app,'download',return_value=self.updates),patch.object(app.subprocess,'run',side_effect=run):
            clock.now.return_value=datetime(2026,11,14,7,tzinfo=timezone.utc);self.assertEqual(app.start(self.root),0)
        self.assertEqual((self.root/'logs/upload.lock').read_bytes(),b'live-original-publisher')
        self.assertFalse((self.root/app.NAMES[0]).exists())
    def test_wrong_date_refuses_before_download(self):
        with patch.object(app.sys,'platform','win32'),patch.object(app,'datetime',wraps=datetime) as clock,patch.object(app,'download') as download:
            clock.now.return_value=datetime(2026,11,15,7,tzinfo=timezone.utc)
            with self.assertRaises(ValueError):app.start(self.root)
        download.assert_not_called()
    def test_package_accepts_only_three_expected_python_files(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            for name,code in self.updates.items():archive.writestr(name,code)
            archive.writestr('../upload_config.json',b'{}')
        response=MagicMock();response.__enter__.return_value.read.return_value=data.getvalue()
        with patch.object(app,'PACKAGE_SHA',hashlib.sha256(data.getvalue()).hexdigest()),patch.object(app.urllib.request,'urlopen',return_value=response):
            with self.assertRaisesRegex(ValueError,'范围异常'):app.download()
    def test_feature_probe_imports_the_exact_package_in_a_fresh_process(self):
        code=Path(__file__).resolve().parent
        completed=subprocess.run([sys.executable,'-c',app.VERIFY,str(code),str(code)],capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)


if __name__=='__main__':unittest.main()
