import hashlib,json,os,re,subprocess,tempfile,unittest
from pathlib import Path
PWSH=Path('/workspace/.tools/fb-pwsh/pwsh');SCRIPT=Path(__file__).with_name('prepare_fb_windows_20261126.ps1')
HARNESS=r'''
. $env:TEST_SCRIPT -FunctionsOnly
$global:killed=@();$global:checks=0
$born=[datetime]'2026-11-25T08:00:00Z'
function BrowserRow {[pscustomobject]@{ProcessId=501;Name='chrome.exe';CreationDate=$born;CommandLine='chrome --user-data-dir=fb01'}}
function ProfileOwners {param($Root) if(501 -notin $global:killed){[pscustomobject]@{account='fb01';row=(BrowserRow)}}}
function Get-CimInstance {param($ClassName,$Filter)
 if($Filter -eq 'ProcessId=501'){if(501 -notin $global:killed){BrowserRow};return}
 if($Filter -eq 'ProcessId=601'){
  if(601 -notin $global:killed){$d=$born;if($env:TEST_CASE -eq 'recycled_worker'){$d=$born.AddMinutes(1)};[pscustomobject]@{ProcessId=601;Name='python.exe';CreationDate=$d;CommandLine='old worker'}};return
 }
 if($env:TEST_CASE -eq 'new_worker'){[pscustomobject]@{ProcessId=999;Name='python.exe';ExecutablePath=($env:TEST_ROOT+'/.venv/Scripts/python.exe');CommandLine='new worker';CreationDate=$born}}
 # IG can use the FB venv and must still survive.
 [pscustomobject]@{ProcessId=701;Name='python.exe';ExecutablePath=($env:TEST_ROOT+'/.venv/Scripts/python.exe');CommandLine=('python ig.py "'+(Join-Path (Split-Path -Parent $env:TEST_ROOT) 'IG-AutoUpload')+'"');CreationDate=$born}
}
function Get-Process {param($Id)
 if($Id -notin @(501,601)){throw 'Unexpected kill target'}
 $d=$born;if($env:TEST_CASE -eq 'recycled_browser' -and $Id -eq 501){$d=$born.AddMinutes(1)}
 $p=[pscustomobject]@{Id=$Id;Handle=1;HasExited=$false;ProcessName=$(if($Id -eq 501){'chrome'}else{'python'});StartTime=$d}
 $p | Add-Member ScriptMethod Dispose {}
 $p | Add-Member ScriptMethod Kill {$global:killed+=([int]$this.Id)}
 $p | Add-Member ScriptMethod WaitForExit {param($Ms) return $true}
 $p
}
function CloseVisible {param($BrowserId) return 1}
function HasVisible {param($BrowserId) $global:checks++;return ($env:TEST_CASE -eq 'visible_modal' -and $global:checks -ge 2)}
try{InvokeFbPrepare $env:TEST_PLAN $env:TEST_AUDIT;'RESULT=completed'}catch{'RESULT=blocked: '+$_.Exception.Message}
'killed='+($global:killed -join ',')
'''
@unittest.skipUnless(PWSH.exists(),'requires PowerShell')
class WindowsTests(unittest.TestCase):
 def run_script(self,source,case='',extra=None):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);h=root/'test.ps1';h.write_text(source,encoding='utf-8-sig');audit=root/'audit.json';plan=root/'plan.json'
   packet=dict(schema='fb-old-materials-preparation-v1',root=str(root),cutoff='2026-11-25',keep_from='2026-11-26',allowed=[],tasks=[],stop=[dict(pid=601,name='python.exe',created='2026-11-25T08:00:00Z',command_sha=hashlib.sha256(b'old worker').hexdigest())]);plan.write_text(json.dumps(packet))
   env=dict(os.environ,TEST_SCRIPT=str(SCRIPT),TEST_ROOT=str(root),TEST_CASE=case,TEST_PLAN=str(plan),TEST_AUDIT=str(audit),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
   if extra:env.update(extra)
   r=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-NonInteractive','-File',str(h)],env=env,capture_output=True,text=True,timeout=25);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
   return r.stdout,json.loads(audit.read_text()) if audit.exists() else None
 def test_old_process_and_windowless_fb_released_ig_untouched(self):
  out,a=self.run_script(HARNESS);self.assertIn('RESULT=completed',out);self.assertIn('killed=601,501',out);self.assertTrue(a['completed']);self.assertTrue(a['instagram_untouched'])
 def test_recycled_old_worker_blocks_before_any_kill(self):
  out,a=self.run_script(HARNESS,'recycled_worker');self.assertIn('RESULT=blocked',out);self.assertEqual(a['stopped'],[]);self.assertFalse(a['completed'])
 def test_visible_modal_new_worker_or_recycled_browser_prevents_forced_browser_kill(self):
  for case in ['visible_modal','new_worker','recycled_browser']:
   out,a=self.run_script(HARNESS,case);self.assertIn('RESULT=blocked',out);self.assertNotIn('601,501',out);self.assertFalse(a['completed'])
 def test_real_profile_parser_selects_exact_fb_root_and_excludes_ig_and_children(self):
  out,_=self.run_script(r'''
. $env:TEST_SCRIPT -FunctionsOnly
function Get-CimInstance {param($ClassName,$Filter)
 foreach($x in @(@(501,'profiles/fb01',''),@(502,'profiles/fb01',' --type=renderer'),@(701,'IG-AutoUpload/profiles/ins01',''),@(801,'profiles/fb01-extra',''))){[pscustomobject]@{ProcessId=$x[0];CommandLine=('chrome --user-data-dir="'+$env:TEST_ROOT+'/'+$x[1]+'"'+$x[2])}}
}
'owners='+(@(ProfileOwners $env:TEST_ROOT).row.ProcessId -join ',')
LoadWindowApi
'compiled'
''');self.assertIn('owners=501',out);self.assertIn('compiled',out)

if __name__=='__main__':unittest.main()
