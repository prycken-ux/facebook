import hashlib,json,os,shlex,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import start_open_fb01_original_profile_20261124 as starter

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
SCRIPT=Path(__file__).with_name('open_fb01_original_profile_20261124.ps1')

@unittest.skipUnless(PWSH.exists(),'Requires PowerShell runtime')
class Fb01OwnerGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'logs').mkdir();(self.root/'logs/publish_state.json').write_text('{"old":{"account":"fb01","status":"needs_review"}}')
    def run_ps(self,body):
        harness=self.root/'test.ps1'
        prefix=". $env:FB01_TEST_SCRIPT -FunctionsOnly -Root $env:FB01_TEST_ROOT -StarterPid 100\n"
        harness.write_text(prefix+body,encoding='utf-8-sig')
        environment=dict(os.environ,FB01_TEST_SCRIPT=str(SCRIPT),FB01_TEST_ROOT=str(self.root),XDG_CACHE_HOME=str(self.root/'cache'),XDG_CONFIG_HOME=str(self.root/'config'),XDG_DATA_HOME=str(self.root/'data'))
        result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(harness)],env=environment,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        return result.stdout.strip()
    def action(self,worker_date='2026-11-24T03:00:00Z',browser_date='2026-11-23T10:00:00Z',window=0,headless=True,status='needs_review'):
        state={'old':{'account':'fb01','status':status}}
        (self.root/'logs/publish_state.json').write_text(json.dumps(state))
        worker="function Get-Fb01ProjectWorkers { [pscustomobject]@{ProcessId=28688;CreationDate=[datetime]'"+worker_date+"'} }\n" if worker_date else 'function Get-Fb01ProjectWorkers {}\n'
        body=worker+"$row=[pscustomobject]@{CreationDate=[datetime]'"+browser_date+"';CommandLine='chrome.exe "+('--headless=new' if headless else '--background-mode')+"'}\n"
        body+="$p=[pscustomobject]@{HasExited=$false;MainWindowHandle="+str(window)+"}\ntry { Get-Fb01Action $row $p } catch { 'blocked: '+$_.Exception.Message }\n"
        return self.run_ps(body)
    def test_stale_headless_can_be_replaced_while_newer_other_account_publisher_runs(self):self.assertEqual(self.action(),'close_stale_headless')
    def test_current_publisher_browser_is_not_closed(self):self.assertIn('blocked:',self.action(browser_date='2026-11-24T04:00:00Z'))
    def test_active_fb01_post_is_not_closed(self):self.assertIn('blocked:',self.action(status='posting'))
    def test_active_fb01_prepare_is_not_closed(self):self.assertIn('blocked:',self.action(status='preparing'))
    def test_visible_window_is_restored_even_when_a_publisher_exists(self):self.assertEqual(self.action(window=123),'restore')
    def test_visible_window_restored_without_killing(self):self.assertEqual(self.action(window=123,status='posting'),'restore')
    def test_normal_background_tray_browser_gets_new_window_without_kill(self):self.assertEqual(self.action(headless=False),'new_visible_window')
    def test_orphan_browser_with_no_publisher_can_be_opened_for_manual_review(self):self.assertEqual(self.action(worker_date=None,status='posting'),'close_stale_headless')
    def test_other_account_posting_does_not_block_stale_fb01(self):
        (self.root/'logs/publish_state.json').write_text('{"other":{"account":"fb02","status":"posting"}}')
        result=self.run_ps("function Get-Fb01ProjectWorkers { [pscustomobject]@{ProcessId=28688;CreationDate=[datetime]'2026-11-24T03:00:00Z'} }\n$row=[pscustomobject]@{CreationDate=[datetime]'2026-11-23T10:00:00Z';CommandLine='chrome.exe --headless=new'}\nGet-Fb01Action $row ([pscustomobject]@{HasExited=$false;MainWindowHandle=0})")
        self.assertEqual(result,'close_stale_headless')
    def test_owner_query_only_accepts_exact_fb01_parent(self):
        body=r'''
function Get-CimInstance {
 param($Filter)
 [pscustomobject]@{ProcessId=1;CommandLine=('chrome.exe --user-data-dir='+$fbProfile+' --headless=new')}
 [pscustomobject]@{ProcessId=2;CommandLine=('chrome.exe --user-data-dir='+$fbProfile+'0 --headless=new')}
 [pscustomobject]@{ProcessId=3;CommandLine=('chrome.exe --user-data-dir='+$fbProfile+' --type=renderer')}
 [pscustomobject]@{ProcessId=4;CommandLine=('chrome.exe --user-data-dir="'+(Join-Path $fbRoot 'profiles/fb02')+'" --headless=new')}
}
@(Get-Fb01Owners).ProcessId -join ','
'''
        self.assertEqual(self.run_ps(body),'1')
    def test_helper_venv_parents_are_exempt_but_other_publisher_is_retained(self):
        body=r'''
function Get-CimInstance {
 param($Filter)
 $suffix=' -u -c "same-helper-body" "'+$fbRoot+'"'
 [pscustomobject]@{ProcessId=[long]100;ParentProcessId=[long]99;CommandLine=('"/base/python"'+$suffix);ExecutablePath='/base/python';CreationDate=[datetime]'2026-11-24T03:00:02Z'}
 [pscustomobject]@{ProcessId=[long]99;ParentProcessId=[long]1;CommandLine=('"/venv/python"'+$suffix);ExecutablePath='/venv/python';CreationDate=[datetime]'2026-11-24T03:00:01Z'}
 [pscustomobject]@{ProcessId=[long]101;ParentProcessId=[long]1;CommandLine=('python "'+$fbRoot+'/publish_eligible60_real_20261123.py" "'+$fbRoot+'"');ExecutablePath='/base/python';CreationDate=[datetime]'2026-11-24T02:00:00Z'}
}
@(Get-Fb01ProjectWorkers).ProcessId -join ','
'''
        self.assertEqual(self.run_ps(body),'101')
    def test_recycled_pid_identity_mismatch_is_disposed_and_not_reused(self):
        body=r'''
$global:fbDisposed=$false
function Get-Process {
 param($Id)
 $p=[pscustomobject]@{Handle=123;HasExited=$false;ProcessName='chrome';StartTime=[datetime]'2026-11-24T03:00:00Z'}
 $p | Add-Member ScriptMethod Dispose { $global:fbDisposed=$true }
 return $p
}
try { $p=Get-Fb01PinnedProcess ([pscustomobject]@{ProcessId=11460;CreationDate=[datetime]'2026-11-23T10:00:00Z'});'unsafe' } catch { 'blocked' }
'disposed='+$global:fbDisposed
'''
        result=self.run_ps(body);self.assertIn('blocked',result);self.assertIn('disposed=True',result)

class StarterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'profiles/fb01/Default').mkdir(parents=True);(self.root/'upload_config.json').write_text('{}')
    def test_original_profile_required_and_not_created_if_missing(self):
        (self.root/'profiles/fb01/Default').rmdir()
        with patch.object(starter.sys,'platform','win32'),patch.object(starter.subprocess,'run',side_effect=AssertionError('No process')):
            with self.assertRaisesRegex(ValueError,'原资料缺失'):starter.start(self.root)
    def test_only_verified_fb01_opener_runs_without_writing_profile_or_publication_records(self):
        marker=self.root/'profiles/fb01/Default/marker';marker.write_bytes(b'original-login-placeholder')
        with patch.object(starter.sys,'platform','win32'),patch.object(starter.subprocess,'run',return_value=MagicMock(returncode=0,stdout='fb01 opened'.encode(),stderr=b'')) as run:
            self.assertEqual(starter.start(self.root),0)
        args=run.call_args.args[0];self.assertIn('-StarterPid',args);self.assertEqual(args[0],'powershell.exe')
        self.assertEqual(marker.read_bytes(),b'original-login-placeholder');self.assertFalse((self.root/'logs/publish_state.json').exists())
        self.assertEqual(starter.SCRIPT,SCRIPT.read_bytes());self.assertEqual(starter.SCRIPT_SHA,hashlib.sha256(starter.SCRIPT).hexdigest());self.assertTrue(starter.SCRIPT.startswith(b'\xef\xbb\xbf'))

if __name__=='__main__':unittest.main()
