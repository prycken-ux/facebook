import hashlib,json,os,subprocess,tempfile,unittest
from pathlib import Path

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
@unittest.skipUnless(PWSH.exists(),'Requires PowerShell')
class IdleProfileTests(unittest.TestCase):
    def check(self,mode='old'):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();(root/'logs/publish_state.json').write_text('{}')
            command='python "'+str(root/'publication_target_watchdog_20261124.py')+'" "'+str(root)+'"'
            packet=root/'packet.json';packet.write_text(json.dumps(dict(root=str(root),account='invalid/../fb09' if mode=='invalid' else 'fb03',starter_pid=500,allowed=[dict(pid=500,created='2026-11-24T08:00:00.0000000Z',command_sha=hashlib.sha256(command.encode()).hexdigest())])))
            source=Path(__file__).with_name('release_idle_publication_profile_20261124.ps1');script=root/'test.ps1'
            body=r'''
. $env:TEST_HELPER -FunctionsOnly
$global:killed=@()
$helper=[pscustomobject]@{ProcessId=500;CommandLine=$env:TEST_COMMAND;ExecutablePath='python';CreationDate=[datetime]'2026-11-24T08:00:00Z'}
function Get-CimInstance {param($Class,$Filter)
 if($Filter -like "Name='python*OR*"){$helper}elseif($Filter -like 'ProcessId=*'){$helper}else{
  if($global:killed.Count){return}
  $profile=Join-Path $env:TEST_ROOT $(if($env:TEST_MODE -eq 'other'){'profiles/fb09'}else{'profiles/fb03'})
  [pscustomobject]@{ProcessId=13208;CommandLine=('chrome --user-data-dir="'+$profile+'" --headless=new');CreationDate=[datetime]'2026-11-23T09:00:00Z'}
 }
}
function Get-Process {param($Id)
 $p=[pscustomobject]@{Id=$Id;Handle=$Id;ProcessName='chrome';HasExited=$false;MainWindowHandle=$(if($env:TEST_MODE -eq 'visible'){100}else{0});StartTime=[datetime]'2026-11-23T09:00:00Z'}
 $p | Add-Member ScriptMethod Refresh {}
 $p | Add-Member ScriptMethod Dispose {}
 $p | Add-Member ScriptMethod Kill {$global:killed+=$this.Id;$this.HasExited=$true}
 $p | Add-Member ScriptMethod WaitForExit {param($Timeout) $true}
 $p
}
try{Release-IdleProfile $env:TEST_PACKET;'completed'}catch{'blocked: '+$_.Exception.Message}
'killed='+($global:killed -join ',')
'''
            script.write_text(body,encoding='utf-8-sig');env=dict(os.environ,TEST_HELPER=str(source),TEST_PACKET=str(packet),TEST_ROOT=str(root),TEST_COMMAND=command,TEST_MODE=mode,XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(script)],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);return result.stdout
    def test_exact_authorized_profile_old_headless_owner_is_released(self):
        output=self.check();self.assertIn('completed',output);self.assertIn('killed=13208',output)
    def test_foreign_profile_is_retained(self):
        output=self.check('other');self.assertIn('completed',output);self.assertIn('killed=\n',output)
    def test_visible_window_is_retained(self):
        output=self.check('visible');self.assertIn('blocked:',output);self.assertIn('killed=\n',output)
    def test_account_path_cannot_escape_expected_profile(self):
        output=self.check('invalid');self.assertIn('blocked:',output);self.assertIn('killed=\n',output)

if __name__=='__main__':unittest.main()
