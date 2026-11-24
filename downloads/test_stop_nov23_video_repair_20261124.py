import copy,json,os,subprocess,tempfile,unittest
from pathlib import Path
import stop_nov23_video_repair_20261124 as stop

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
SOURCE=Path(__file__).parent
class AuditTests(unittest.TestCase):
    def test_stop_preserves_all_ledgers_and_nov24_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'logs').mkdir()
            status=dict(material_date='2026-11-23',launch_id='a'*32,pid=120,phase='running',extra='keep')
            (root/stop.STATUS).write_text(json.dumps(status))
            preserve={name:b'{"pending":true}' for name in ['publish_state.json','video_comments.json','eligible60-2026-11-24-status.json']}
            for name,data in preserve.items():(root/'logs'/name).write_bytes(data)
            audit=dict(schema='nov23-user-ended-video-repair-v1',material_date='2026-11-23',submission_records_preserved=True,launch_id='a'*32,owner_pid=120,stopped_at='2026-11-24T10:00:00Z',original_status=status)
            stop.finish(root,audit)
            self.assertEqual(json.loads((root/stop.STATUS).read_text())['phase'],'user_stopped')
            self.assertEqual(json.loads((root/stop.MARKER).read_text())['original_status'],status)
            for name,data in preserve.items():self.assertEqual((root/'logs'/name).read_bytes(),data)
    def test_new_launch_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'logs').mkdir();path=root/stop.STATUS
            before=json.dumps(dict(material_date='2026-11-23',launch_id='b'*32,pid=121));path.write_text(before)
            with self.assertRaises(ValueError):stop.finish(root,dict(schema='nov23-user-ended-video-repair-v1',material_date='2026-11-23',submission_records_preserved=True,launch_id='a'*32,owner_pid=120))
            self.assertEqual(path.read_text(),before);self.assertFalse((root/stop.MARKER).exists())

@unittest.skipUnless(PWSH.exists(),'PowerShell required')
class OwnershipTests(unittest.TestCase):
    def run_case(self,case):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'logs').mkdir()
            (root/stop.STATUS).write_text(json.dumps(dict(material_date='2026-11-23',launch_id='a'*32,pid=120,updated_at='2026-11-24T09:00:00Z')))
            script=root/'test.ps1'
            script.write_text(r'''
. $env:STOP_SCRIPT -FunctionsOnly
$script:case=$env:STOP_CASE;$script:killed=@();$script:stage=0
$entry=Join-Path $env:STOP_ROOT 'material-staging\tools\nov23-caption-repair-e6453166086a0db8\repair_nov23_caption_fb09_20261124.py'
$owner=[pscustomobject]@{ProcessId=120;ParentProcessId=1;Name='python.exe';CreationDate=[datetime]'2026-11-24T08:00:00Z';CommandLine=('python "'+$entry+'" "'+$env:STOP_ROOT+'"')}
$child=[pscustomobject]@{ProcessId=121;ParentProcessId=120;Name='chrome.exe';CreationDate=[datetime]'2026-11-24T08:10:00Z';CommandLine='chrome --headless'}
$other=[pscustomobject]@{ProcessId=130;ParentProcessId=1;Name='python.exe';CreationDate=[datetime]'2026-11-24T08:00:00Z';CommandLine='python publication_target_watchdog_20261124.py'}
$manual=[pscustomobject]@{ProcessId=131;ParentProcessId=1;Name='chrome.exe';CreationDate=[datetime]'2026-11-24T08:00:00Z';CommandLine='chrome manual'}
if($script:case -eq 'reused'){$owner.CommandLine=$other.CommandLine}
if($script:case -eq 'wrongroot'){$owner.CommandLine=('python "'+$entry+'" "X:\AnotherProject"')}
if($script:case -eq 'newpid'){$owner.CreationDate=[datetime]'2026-11-24T10:00:00Z'}
if($script:case -eq 'olderchild'){$child.CreationDate=[datetime]'2026-11-24T07:00:00Z'}
$script:rows=@($owner,$child,$other,$manual)
if($script:case -eq 'absent'){$script:rows=@($other,$manual)}
function Get-CimInstance {param($Class,$Filter)
 if($Filter){return $owner}
 $script:rows | Where-Object {$_.ProcessId -notin $script:killed}
}
function Get-SharedHash($Path){if($script:case -eq 'hash'){'bad'}else{'9c79188f0dc75d57f071941be899752d2bc8bcf64f66cdf46075b366155bb8b7'}}
function Get-Process {param($Id,$ErrorAction)
 $row=$script:rows | Where-Object {$_.ProcessId -eq $Id}
 $p=[pscustomobject]@{Id=$Id;StartTime=$row.CreationDate;Handle=1;HasExited=$false}
 $p | Add-Member ScriptMethod Kill {$this.HasExited=$true;$script:killed+=@($this.Id)}
 $p | Add-Member ScriptMethod WaitForExit {param($ms) return $this.HasExited}
 $p | Add-Member ScriptMethod Dispose {}
 return $p
}
try{Stop-Nov23VideoRepair $env:STOP_ROOT (Join-Path $env:STOP_ROOT 'audit.json') | Out-Null;$success=$true}catch{$success=$false}
@{success=$success;killed=@($script:killed)} | ConvertTo-Json -Compress
''',encoding='utf-8-sig')
            env=dict(os.environ,STOP_SCRIPT=str(SOURCE/'stop_nov23_video_repair_20261124.ps1'),STOP_ROOT=str(root),STOP_CASE=case,XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],capture_output=True,text=True,timeout=15,env=env)
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
    def test_only_verified_owner_and_descendant_stop(self):self.assertEqual(self.run_case('valid'),dict(success=True,killed=[120,121]))
    def test_unrelated_reused_pid_is_preserved(self):self.assertEqual(self.run_case('reused'),dict(success=False,killed=[]))
    def test_wrong_root_is_preserved(self):self.assertEqual(self.run_case('wrongroot'),dict(success=False,killed=[]))
    def test_later_creation_is_preserved(self):self.assertEqual(self.run_case('newpid'),dict(success=False,killed=[]))
    def test_wrong_code_is_preserved(self):self.assertEqual(self.run_case('hash'),dict(success=False,killed=[]))
    def test_child_reused_parent_id_is_preserved(self):self.assertEqual(self.run_case('olderchild'),dict(success=True,killed=[120]))
    def test_already_exited_leaves_nov24_and_chrome(self):self.assertEqual(self.run_case('absent'),dict(success=True,killed=[]))

if __name__=='__main__':unittest.main()
