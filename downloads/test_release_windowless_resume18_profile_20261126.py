import hashlib,json,os,re,subprocess,tempfile,unittest
from pathlib import Path

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
SCRIPT=Path(__file__).with_name('release_windowless_resume18_profile_20261126.ps1')
HARNESS=r'''
. $env:TEST_SCRIPT -FunctionsOnly
$global:killed=$false;$global:visibleChecks=0
function Get-CimInstance {param($ClassName,$Filter)
 $born=[datetime]'2026-11-25T08:00:00Z'
 if($Filter -like "Name='python.exe'*"){
  [pscustomobject]@{ProcessId=111;Name='python.exe';CommandLine=('python "'+$env:TEST_ROOT+'/worker.py"');ExecutablePath=($env:TEST_ROOT+'/.venv/Scripts/python.exe');CreationDate=[datetime]'2026-11-26T00:00:00Z'}
  if($env:TEST_CASE -eq 'other_worker'){[pscustomobject]@{ProcessId=999;Name='python.exe';CommandLine=('python "'+$env:TEST_ROOT+'/other.py"');ExecutablePath='python.exe';CreationDate=[datetime]'2026-11-26T00:00:00Z'}}
 }elseif($Filter -like 'ProcessId=*'){
  [pscustomobject]@{ProcessId=111;CreationDate=[datetime]'2026-11-26T00:00:00Z'}
 }else{
  # Another profile remains present throughout and must never be terminated.
  [pscustomobject]@{ProcessId=8888;ParentProcessId=1;Name='chrome.exe';CreationDate=$born;CommandLine=('chrome --user-data-dir="'+$env:TEST_ROOT+'/profiles/fb02"')}
  if(-not $global:killed -and $env:TEST_CASE -ne 'foreign_profile'){
   if($env:TEST_CASE -eq 'new_browser'){$born=[datetime]'2026-11-26T00:10:00Z'}
   [pscustomobject]@{ProcessId=17232;ParentProcessId=1;Name='chrome.exe';CreationDate=$born;CommandLine=('chrome --user-data-dir="'+$env:TEST_ROOT+'/profiles/fb01" --profile-directory=Default')}
  }
 }
}
function Get-Process {param($Id)
 if($Id -ne 17232){throw 'Unexpected process target'}
 $born=[datetime]'2026-11-25T08:00:00Z'
 if($env:TEST_CASE -eq 'pid_reuse'){$born=[datetime]'2026-11-26T00:20:00Z'}
 $p=[pscustomobject]@{Id=17232;Handle=1;HasExited=$false;ProcessName='chrome';MainWindowHandle=0;StartTime=$born}
 $p | Add-Member ScriptMethod Refresh {}
 $p | Add-Member ScriptMethod Dispose {}
 $p | Add-Member ScriptMethod Kill {$global:killed=$true;[IO.File]::WriteAllText($env:TEST_MARKER,'17232')}
 $p | Add-Member ScriptMethod WaitForExit {param($Ms) return $true}
 $p
}
function Test-ProfileVisibleWindow {param($BrowserId)
 $global:visibleChecks++
 if($env:TEST_CASE -eq 'visible'){return $true}
 if($env:TEST_CASE -eq 'late_visible'){return ($global:visibleChecks -ge 2)}
 return $false
}
try{Release-IdleProfile $env:TEST_PACKET;'RESULT=released-or-free'}catch{'RESULT=preserved: '+$_.Exception.Message}
'visibleChecks='+$global:visibleChecks
'''

@unittest.skipUnless(PWSH.exists(),'Requires PowerShell')
class WindowlessReleaseTests(unittest.TestCase):
    def run_case(self,case,authorized=True,account='fb01'):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();(root/'logs/publish_state.json').write_text('{}');marker=root/'killed.txt';packet=root/'packet.json'
            command='python "'+str(root)+'/worker.py"'
            value=dict(root=str(root),account=account,starter_pid=111,allowed=[dict(pid=111,created='2026-11-26T00:00:00Z',command_sha=hashlib.sha256(command.encode()).hexdigest())])
            if authorized:value['closed_windows_authorization']='user-closed-selected18-windows-20261126'
            packet.write_text(json.dumps(value));h=root/'harness.ps1';h.write_text(HARNESS,encoding='utf-8-sig')
            env=dict(os.environ,TEST_SCRIPT=str(SCRIPT),TEST_CASE=case,TEST_ROOT=str(root),TEST_PACKET=str(packet),TEST_MARKER=str(marker),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            r=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-NonInteractive','-File',str(h)],env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            killed=marker.read_text() if marker.exists() else None
            self.assertEqual((root/'logs/publish_state.json').read_text(),'{}')
            return killed,r.stdout
    def test_exact_old_windowless_normal_profile_releases_only_that_pid(self):
        killed,out=self.run_case('windowless');self.assertEqual(killed,'17232',out);self.assertIn('RESULT=released-or-free',out);self.assertIn('visibleChecks=2',out)
    def test_visible_window_with_zero_main_handle_is_preserved(self):
        killed,out=self.run_case('visible');self.assertIsNone(killed,out);self.assertIn('RESULT=preserved',out)
    def test_window_appearing_immediately_before_kill_is_preserved(self):
        killed,out=self.run_case('late_visible');self.assertIsNone(killed,out);self.assertIn('RESULT=preserved',out)
    def test_no_authorization_or_outside_selected_scope_is_preserved(self):
        for kwargs in [dict(authorized=False),dict(account='fb32')]:
            killed,out=self.run_case('windowless',**kwargs);self.assertIsNone(killed,out);self.assertIn('RESULT=preserved',out)
    def test_other_task_recycled_pid_and_new_browser_are_preserved(self):
        for case in ['other_worker','pid_reuse','new_browser']:
            killed,out=self.run_case(case);self.assertIsNone(killed,out);self.assertIn('RESULT=preserved',out)
    def test_foreign_profile_is_never_killed(self):
        killed,out=self.run_case('foreign_profile');self.assertIsNone(killed,out);self.assertIn('RESULT=released-or-free',out)
    def test_real_family_enumerator_includes_own_children_but_not_other_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=root/'family.ps1'
            script.write_text(r'''
. $env:TEST_SCRIPT -FunctionsOnly
Add-Type -TypeDefinition 'public static class FBResume18VisibleWindow { public static int[] Seen; public static bool HasVisible(int[] ids) { Seen=ids; return false; } }'
function Get-CimInstance {param($ClassName,$Filter)
 [pscustomobject]@{ProcessId=17233;ParentProcessId=17232;CommandLine='chrome --type=gpu-process'}
 [pscustomobject]@{ProcessId=17234;ParentProcessId=17233;CommandLine='chrome --type=renderer'}
 [pscustomobject]@{ProcessId=30116;ParentProcessId=17232;CommandLine='chrome --user-data-dir=other-profile'}
 [pscustomobject]@{ProcessId=30117;ParentProcessId=30116;CommandLine='chrome --type=renderer'}
}
$answer=Test-ProfileVisibleWindow 17232
'visible='+$answer
'family='+([FBResume18VisibleWindow]::Seen -join ',')
''',encoding='utf-8-sig')
            env=dict(os.environ,TEST_SCRIPT=str(SCRIPT),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            r=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(script)],env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stderr);self.assertIn('visible=False',r.stdout)
            ids=re.search(r'family=([0-9,]+)',r.stdout)[1];self.assertEqual(set(ids.split(',')),{'17232','17233','17234'})
    def test_window_enumerator_csharp_compiles_without_using_windows_api(self):
        code=re.search(r"Add-Type -TypeDefinition @'\n(.*?)\n'@",SCRIPT.read_text(encoding='utf-8-sig'),re.S)[1]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);src=root/'Window.cs';src.write_text(code);script=root/'compile.ps1';script.write_text("Add-Type -Path $env:TEST_SOURCE\n'compiled'\n")
            env=dict(os.environ,TEST_SOURCE=str(src),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            r=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(script)],env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stderr);self.assertIn('compiled',r.stdout)

if __name__=='__main__':unittest.main()
