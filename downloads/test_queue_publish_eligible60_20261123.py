import hashlib,json,os,shlex,subprocess,tempfile,time,unittest
from pathlib import Path

PWSH=Path('/tmp/fb-nov23-pwsh/pwsh')
SCRIPT=Path(__file__).with_name('queue_publish_eligible60_20261123.ps1')
HARNESS=r'''
$global:fbCalls=0
function Get-CimInstance {
 param($Filter,$ErrorAction)
 $global:fbCalls++
 if(($env:FB_QUEUE_TEST_MODE -eq 'worker' -and $global:fbCalls -eq 1) -or $env:FB_QUEUE_TEST_MODE -eq 'forever') {
  [pscustomobject]@{ProcessId=999;CommandLine=('python '+$env:FB_QUEUE_TEST_ROOT+'/resume-old20.py');ExecutablePath=('/usr/bin/python')}
 }
}
function Start-Sleep {
 param($Seconds)
 if($env:FB_QUEUE_TEST_MODE -eq 'distribution') {
  '{"complete":true}' | Set-Content -LiteralPath (Join-Path $env:FB_QUEUE_TEST_ROOT 'material-staging/eligible60-20261123-pending-import.json') -Encoding UTF8
 }
 if($env:FB_QUEUE_TEST_MODE -eq 'forever'){[Threading.Thread]::Sleep(100)}
}
& $env:FB_QUEUE_TEST_SCRIPT -Root $env:FB_QUEUE_TEST_ROOT -Entry $env:FB_QUEUE_TEST_ENTRY -EntrySha $env:FB_QUEUE_TEST_SHA
'''

@unittest.skipUnless(PWSH.exists(),'Requires the local PowerShell test runtime')
class QueueControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for folder in ('logs','material-staging','.venv/Scripts','cache'):(self.root/folder).mkdir(parents=True)
        self.entry=self.root/'cache/fixture.py';self.entry.write_text('# reviewed harmless fixture\n')
        self.sha=hashlib.sha256(self.entry.read_bytes()).hexdigest()
        (self.entry.parent/'runtime-sha256.json').write_text(json.dumps({self.entry.name:self.sha}))
        self.marker=self.root/'launched'
        pythonw=self.root/'.venv/Scripts/pythonw.exe'
        pythonw.write_text('#!/bin/sh\nprintf launched > '+shlex.quote(str(self.marker))+"\nprintf 'fixture stderr\\n' >&2\nexit 3\n");pythonw.chmod(0o700)
        self.pointer=self.root/'material-staging/eligible60-20261123-pending-import.json';self.pointer.write_text('{"complete":true}')
        self.harness=self.root/'harness.ps1';self.harness.write_text(HARNESS,encoding='utf-8-sig')
    def env(self,mode):
        return dict(os.environ,XDG_CACHE_HOME=str(self.root/'xdg-cache'),XDG_CONFIG_HOME=str(self.root/'xdg-config'),XDG_DATA_HOME=str(self.root/'xdg-data'),
                    FB_QUEUE_TEST_MODE=mode,FB_QUEUE_TEST_ROOT=str(self.root),FB_QUEUE_TEST_SCRIPT=str(SCRIPT),FB_QUEUE_TEST_ENTRY=str(self.entry),FB_QUEUE_TEST_SHA=self.sha)
    def run_queue(self,mode):
        r=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(self.harness)],env=self.env(mode),capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr)
        return json.loads((self.root/'logs/eligible60-2026-11-23-queue.json').read_text(encoding='utf-8-sig'))
    def test_waits_for_old_workers_then_runs_only_after_they_exit(self):
        status=self.run_queue('worker')
        self.assertEqual(status['phase'],'review_required');self.assertTrue(self.marker.exists())
        log=(self.root/'logs/eligible60-2026-11-23-queue.log').read_text(encoding='utf-8-sig');self.assertIn('PID：999',log)
    def test_waits_for_completed_import_without_a_python_waiter(self):
        self.pointer.write_text('{"complete":false}')
        status=self.run_queue('distribution');self.assertEqual(status['phase'],'review_required');self.assertTrue(self.marker.exists())
        self.assertIn('等待11月23日60条素材',(self.root/'logs/eligible60-2026-11-23-queue.log').read_text(encoding='utf-8-sig'))
    def test_runtime_hash_change_blocks_process_creation(self):
        self.entry.write_text('# modified fixture\n')
        status=self.run_queue('idle');self.assertEqual(status['phase'],'error');self.assertFalse(self.marker.exists())
    def test_duplicate_queue_cannot_launch_a_second_publisher(self):
        args=[str(PWSH),'-NoLogo','-NoProfile','-File',str(self.harness)]
        p=subprocess.Popen(args,env=self.env('forever'),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        try:
            status_path=self.root/'logs/eligible60-2026-11-23-queue.json'
            for _ in range(60):
                if status_path.exists():break
                if p.poll() is not None:self.fail(p.stderr.read())
                time.sleep(.1)
            self.assertTrue(status_path.exists())
            second=subprocess.run(args,env=self.env('idle'),capture_output=True,text=True,timeout=10)
            self.assertEqual(second.returncode,0,second.stderr);self.assertFalse(self.marker.exists())
            status=json.loads(status_path.read_text(encoding='utf-8-sig'));self.assertEqual(status['pid'],p.pid)
        finally:
            p.terminate();p.wait(timeout=5)
            if p.stderr:p.stderr.close()

if __name__=='__main__':unittest.main()
