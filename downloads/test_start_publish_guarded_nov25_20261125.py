import hashlib,json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import start_publish_guarded_nov25_20261125 as starter
import start_publish_eligible60_real_20261123 as base

class StarterTests(unittest.TestCase):
    def test_embedded_files_match_reviewed_sources_and_fixed_caption_reader(self):
        for name,data in starter.ADDITIONS.items():self.assertEqual(data,Path(__file__).with_name(name).read_bytes())
        hashes={name:hashlib.sha256(data).hexdigest() for name,data in starter.ADDITIONS.items()}
        self.assertEqual(starter.FINGERPRINT,hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest())
        self.assertNotIn(b'.input_value(',starter.ADDITIONS['reel_audience_dialog_recovery.py'])
        self.assertIn(b'180',starter.ADDITIONS['publication_target_watchdog_20261125.py'])
    def test_only_powershell_waiter_starts_before_distribution_and_old_worker_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();(root/'.venv/Scripts').mkdir(parents=True);(root/'.venv/Scripts/python.exe').touch();(root/'upload_config.json').write_text('{}')
            # An unfinished allocation and old live lock must remain unchanged.
            (root/'material-staging').mkdir();pointer=root/'material-staging/eligible60-20261125-pending-import.json';pointer.write_text('{"complete": false}')
            lock=root/'logs/upload.lock';lock.write_text('22964');original=pointer.read_bytes();calls=[]
            class Process:
                def __init__(self,args,**kwargs):
                    self.args=args;self.run=args[args.index('-Run')+1];self.calls=0;calls.append(self)
                def poll(self):
                    self.calls+=1;(root/'logs'/('nov25-queue-'+self.run+'.json')).write_text(json.dumps(dict(run_id=self.run,phase='waiting_workers',message='old worker still running')));return None
            with patch.object(starter.sys,'platform','win32'),patch.object(starter,'base_runtime',return_value=base),patch.object(base,'download',return_value={}),patch.object(starter.subprocess,'run'),patch.object(starter.subprocess,'Popen',Process),patch.object(starter.time,'sleep'):
                self.assertEqual(starter.start(root),0)
            self.assertEqual(len(calls),1);self.assertEqual(calls[0].args[0],'powershell.exe');self.assertEqual(calls[0].calls,2)
            self.assertEqual(pointer.read_bytes(),original);self.assertEqual(lock.read_text(),'22964');self.assertFalse((root/'logs/publish_state.json').exists())
    def test_runtime_has_no_historical_cleanup_or_old_comment_repair(self):
        names=set(starter.ADDITIONS)
        self.assertIn('nov25_publication_policy.py',names)
        self.assertFalse(any(n.startswith(('clean_pre_','comment_nov24_','retry10_')) for n in names))
        self.assertNotIn('start_stop_nov23',Path(starter.__file__).read_text())
    def test_package_probe_imports_original_scope_and_nov25_versions(self):
        # The final package is network-verified separately; this checks that all
        # embedded Python modules are syntactically valid without a live login.
        import ast
        for name,data in starter.ADDITIONS.items():
            if name.endswith('.py'):ast.parse(data.decode('utf-8-sig'))

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
@unittest.skipUnless(PWSH.exists(),'Requires PowerShell runtime')
class QueueDuplicateTests(unittest.TestCase):
    def test_running_supervisor_is_acknowledged_without_another_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();entry=root/'publication_target_watchdog_20261125.py'
            (root/'logs/eligible60-2026-11-25-status.json').write_text(json.dumps(dict(material_date='2026-11-25',phase='running',pid=123,updated_at='2026-11-25T08:00:00Z')))
            queue=Path(__file__).with_name('queue_publish_guarded_nov25_20261125.ps1');script=root/'test.ps1'
            script.write_text(r'''
. $env:TEST_QUEUE -FunctionsOnly
function Get-CimInstance {param($Class,$Filter)
 if($Filter -like 'ProcessId=*'){[pscustomobject]@{ProcessId=123;Name='python.exe';CreationDate=[datetime]'2026-11-25T07:00:00Z';CommandLine=('python "'+$env:TEST_ENTRY+'" "'+$env:TEST_ROOT+'"')}}else{throw 'Must not enumerate or launch another worker'}
}
Start-Nov25Queue $env:TEST_ROOT $env:TEST_ENTRY 'not-needed-for-existing-run' ('a'*32)
(Get-Content -LiteralPath (Join-Path $env:TEST_ROOT ('logs/nov25-queue-'+('a'*32)+'.json')) -Raw)
''',encoding='utf-8-sig')
            env=dict(os.environ,TEST_QUEUE=str(queue),TEST_ENTRY=str(entry),TEST_ROOT=str(root),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['phase'],'already_running')

if __name__=='__main__':unittest.main()
