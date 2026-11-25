import hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import start_distribute_eligible60_materials_20261125 as starter
import start_distribute_eligible60_materials_20261124 as base
import distribute_eligible60_materials_20261125 as driver

class StarterTests(unittest.TestCase):
    def test_immutable_embedded_tools_match_sources_and_have_no_publisher(self):
        for name,data in starter.FILES.items():self.assertEqual(data,Path(__file__).with_name(name).read_bytes())
        hashes={n:hashlib.sha256(b).hexdigest() for n,b in starter.FILES.items()}
        self.assertEqual(starter.FINGERPRINT,hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest())
        self.assertEqual(set(starter.FILES),{'distribute_eligible60_materials_20261125.py','clean_pre_nov25_materials_20261125.py','cleanup_confirmed_published_videos.py','publication_file_state_20261124.py'})
        self.assertLess(len(Path(starter.__file__).read_bytes()),131073)
    def test_starter_executes_only_checker_then_allocation_driver(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'upload_config.json').write_text('{}');(root/'.venv/Scripts').mkdir(parents=True);(root/'.venv/Scripts/python.exe').touch()
            with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download_base',return_value=base),patch.object(base,'download',return_value={}),patch.object(starter.subprocess,'run',return_value=type('Result',(),dict(returncode=0))()) as run:
                self.assertEqual(starter.start(root),0)
            self.assertEqual(run.call_count,2);args=run.call_args.args[0];self.assertTrue(args[2].endswith('distribute_eligible60_materials_20261125.py'));self.assertEqual(args[3],str(root));self.assertFalse((root/'logs/publish_state.json').exists())
    def test_bootstrap_tag_matches_verified_parent_chain_checker(self):
        code="import hashlib,ssl,sys,urllib.request;c=ssl.create_default_context();c.minimum_version=ssl.TLSVersion.TLSv1_2;b=urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/"+'a'*40+"/downloads/start_distribute_eligible60_materials_20261125.py',context=c,timeout=30).read(131073);hashlib.sha256(b).hexdigest()=='"+'b'*64+"' or sys.exit('Checksum mismatch; stopped');exec(compile(b,'verified-nov25-eligible60-material-distribution','exec'))"
        self.assertIsNotNone(driver.BOOTSTRAP.fullmatch(code))

if __name__=='__main__':unittest.main()
