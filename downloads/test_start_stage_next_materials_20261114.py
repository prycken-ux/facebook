import hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import start_stage_next_materials_20261114 as app


class IndependentStageStartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'upload_config.json').write_text('{"targets":[]}')
        (self.root/'account_registry.json').write_text('{"accounts":[]}')
        (self.root/'logs').mkdir();(self.root/'logs/upload.lock').write_bytes(b'active-publisher')
        self.module=b"import sys\nfrom pathlib import Path\nassert len(sys.argv)==3 and sys.argv[1]=='prepare'\nassert (Path(sys.argv[2])/'logs/upload.lock').read_bytes()==b'active-publisher'\n"
        self.sha=hashlib.sha256(self.module).hexdigest();self.response=MagicMock();self.response.__enter__.return_value.read.return_value=self.module
        context=app.ssl.create_default_context()
        self.enterContext(patch.object(app.ssl,'create_default_context',return_value=context))
    def start(self):
        with patch.object(app.sys,'platform','win32'),patch.object(app,'MODULE_SHA',self.sha),patch.object(app.urllib.request,'urlopen',return_value=self.response):return app.start(self.root)
    def test_real_child_starts_in_a_separate_tree_without_acquiring_or_removing_active_upload_lock(self):
        originals={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.start(),0)
        for p,data in originals.items():self.assertEqual(p.read_bytes(),data)
        code=self.root/'material-staging/tools'/self.sha[:16]/app.MODULE
        self.assertEqual(code.read_bytes(),self.module);self.assertFalse((self.root/app.MODULE).exists())
        self.assertEqual(self.start(),0)
    def test_checksum_mismatch_never_creates_cache_or_touches_publisher(self):
        with patch.object(app.sys,'platform','win32'),patch.object(app.urllib.request,'urlopen',return_value=self.response):
            with self.assertRaisesRegex(ValueError,'Checksum mismatch'):app.start(self.root)
        self.assertFalse((self.root/'material-staging').exists());self.assertEqual((self.root/'logs/upload.lock').read_bytes(),b'active-publisher')
    def test_existing_unknown_cache_is_not_overwritten(self):
        folder=self.root/'material-staging/tools'/self.sha[:16];folder.mkdir(parents=True)
        path=folder/app.MODULE;path.write_bytes(b'unknown contents')
        with self.assertRaisesRegex(ValueError,'缓存内容异常'):self.start()
        self.assertEqual(path.read_bytes(),b'unknown contents')


if __name__=='__main__':unittest.main()
