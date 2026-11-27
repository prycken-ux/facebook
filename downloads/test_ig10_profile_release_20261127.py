import json,os,subprocess,tempfile,unittest
from pathlib import Path
PWSH=Path('/workspace/.tools/fb-pwsh/pwsh');SCRIPT=Path(__file__).with_name('ig10_profile_release.ps1')
HARNESS=r'''
. $env:IG_SCRIPT -FunctionsOnly
$global:killed=$false
Add-Type -TypeDefinition @'
using System;
public static class IG10Windows {
 public static int Checks=0; public static int Closed=0;
 public static bool Visible(int[] ids){foreach(int id in ids){if(id==8888)throw new Exception("FB profile included");}Checks++;string c=Environment.GetEnvironmentVariable("IG_CASE");return c=="visible"||(c=="late_visible"&&Checks>=2);}
 public static void Close(int[] ids){foreach(int id in ids){if(id==8888)throw new Exception("FB profile included");}Closed++;}
}
'@
function Start-Sleep {param($Milliseconds) Set-Variable -Name until -Value ([datetime]::UtcNow.AddSeconds(-1)) -Scope 1}
function Get-CimInstance {param($ClassName,$Filter)
 $born=[datetime]'2026-11-27T01:00:00Z'
 if($Filter -like "Name='python.exe'*"){
  [pscustomobject]@{ProcessId=111;Name='python.exe';ParentProcessId=1;CommandLine=('python "'+$env:IG_ROOT+'/engine.py" "'+$env:IG_ROOT+'"')}
  if($env:IG_CASE -eq 'other_task'){[pscustomobject]@{ProcessId=999;Name='python.exe';CommandLine=('python '+$env:IG_ROOT+'/other.py')}}
  return
 }
 if($Filter -eq 'ProcessId=111'){[pscustomobject]@{ProcessId=111;ParentProcessId=1;Name='python.exe';CommandLine=('python '+$env:IG_ROOT+'/engine.py')};return}
 if($Filter -eq 'ProcessId=1'){return}
 if($Filter -eq 'ProcessId=17232'){
  if($global:killed){return}
  [pscustomobject]@{ProcessId=17232;ParentProcessId=1;Name='chrome.exe';CreationDate=$born;CommandLine=('chrome --user-data-dir="'+$env:IG_ROOT+'/profiles/ins01" --profile-directory=Default')};return
 }
 if($Filter -eq "Name='chrome.exe'"){
  [pscustomobject]@{ProcessId=8888;ParentProcessId=1;Name='chrome.exe';CreationDate=$born;CommandLine=('chrome --user-data-dir="'+(Split-Path $env:IG_ROOT)+'/FB-AutoUpload/profiles/fb01"')}
  [pscustomobject]@{ProcessId=7777;ParentProcessId=1;Name='chrome.exe';CreationDate=$born;CommandLine=('chrome --user-data-dir="'+$env:IG_ROOT+'/profiles/ins02"')}
  if(-not $global:killed -and $env:IG_CASE -ne 'foreign_only'){
   [pscustomobject]@{ProcessId=17232;ParentProcessId=1;Name='chrome.exe';CreationDate=$born;CommandLine=('chrome --user-data-dir="'+$env:IG_ROOT+'/profiles/ins01" --profile-directory=Default')}
   [pscustomobject]@{ProcessId=17233;ParentProcessId=17232;Name='chrome.exe';CreationDate=$born;CommandLine='chrome --type=gpu-process'}
  }
 }
}
function Get-Process {param($Id)
 if($Id -ne 17232){throw 'Foreign process targeted'}
 $born=[datetime]'2026-11-27T01:00:00Z';if($env:IG_CASE -eq 'pid_reuse'){$born=$born.AddHours(1)}
 $p=[pscustomobject]@{Handle=1;HasExited=$false;ProcessName='chrome';StartTime=$born}
 $p | Add-Member ScriptMethod Dispose {}
 $p | Add-Member ScriptMethod Kill {$global:killed=$true}
 $p | Add-Member ScriptMethod WaitForExit {param($Ms) return $true}
 $p
}
try{ReleaseIgProfiles $env:IG_PACKET;'RESULT=free'}catch{'RESULT=kept '+$_.Exception.Message}
'killed='+$global:killed
'closed='+[IG10Windows]::Closed
'''
@unittest.skipUnless(PWSH.exists(),'PowerShell required')
class ProfileReleaseTests(unittest.TestCase):
 def run_case(self,case,authorization=True):
  with tempfile.TemporaryDirectory() as temp:
   base=Path(temp);root=base/'IG-AutoUpload';root.mkdir();packet=base/'packet.json';packet.write_text(json.dumps(dict(root=str(root),accounts=['ins01'],caller_pid=111,authorization='ig10-publication-normal-close-20261127' if authorization else 'no')));script=base/'test.ps1';script.write_text(HARNESS,encoding='utf-8-sig');env=dict(os.environ,IG_ROOT=str(root),IG_SCRIPT=str(SCRIPT),IG_PACKET=str(packet),IG_CASE=case,XDG_CACHE_HOME=str(base/'cache'),XDG_CONFIG_HOME=str(base/'config'),XDG_DATA_HOME=str(base/'data'))
   result=subprocess.run([str(PWSH),'-NoProfile','-File',str(script)],env=env,capture_output=True,text=True,timeout=20);self.assertEqual(result.returncode,0,result.stdout+result.stderr);return result.stdout
 def test_only_owned_windowless_root_released_after_normal_close(self):
  out=self.run_case('windowless');self.assertIn('RESULT=free',out);self.assertIn('killed=True',out);self.assertIn('closed=1',out)
 def test_modal_late_visible_recycled_pid_and_other_task_kept(self):
  for case in ['visible','late_visible','pid_reuse','other_task']:
   with self.subTest(case=case):
    out=self.run_case(case);self.assertIn('RESULT=kept',out);self.assertIn('killed=False',out)
 def test_fb_and_other_ig_profile_never_closed_or_killed(self):
  out=self.run_case('foreign_only');self.assertIn('RESULT=free',out);self.assertIn('killed=False',out);self.assertIn('closed=0',out)
 def test_missing_authorization_keeps_everything(self):
  out=self.run_case('windowless',False);self.assertIn('RESULT=kept',out);self.assertIn('closed=0',out)

if __name__=='__main__':unittest.main()
