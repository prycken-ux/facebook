import copy,hashlib,json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import repair_nov23_caption_fb09_20261124 as r

def submitted(value):
    if isinstance(value,list):return any(submitted(v) for v in value)
    if not isinstance(value,dict):return False
    return value.get('status') in {'published','posting','needs_review'} or any(value.get(k) for k in ('post_intent_at','permalink','success_message')) or any(submitted(v) for v in value.values() if isinstance(v,(dict,list)))

class ScopeTests(unittest.TestCase):
    def test_audited_categories_exclude_login_and_submitted_jobs(self):
        self.assertEqual(r.classification(dict(video_status='failed_before_post',account='fb03',reason='Locator.input_value: '+r.CAPTION_ERROR)),'caption')
        self.assertEqual(r.classification(dict(video_status='not_started',account='fb09')),'profile_busy_before_browser')
        self.assertIsNone(r.classification(dict(video_status='needs_review',account='fb01',reason='publication timeout')))
        self.assertIsNone(r.classification(dict(video_status='failed_before_post',account='fb52',reason='遇到登录或安全验证')))
    def test_all_nested_submission_evidence_is_preserved(self):
        job={'account':'fb03'};old=dict(video_status='failed_before_post',account='fb03',reason='Locator.input_value '+r.CAPTION_ERROR)
        row=dict(status='failed_before_post',error=old['reason'])
        self.assertTrue(r.allowed_live(job,row,old,submitted))
        for protected in [dict(status='needs_review'),dict(post_intent_at='time'),dict(previous={'post_intent_at':'time'}),dict(permalink='https://www.facebook.com/reel/123')]:
            with self.subTest(protected=protected):self.assertFalse(r.allowed_live(job,dict(row,**protected),old,submitted))
        self.assertFalse(r.allowed_live({'account':'fb32'},row,old,submitted))
        self.assertFalse(r.allowed_live(job,dict(row,error='遇到登录或安全验证'),old,submitted))
    def test_changed_failure_is_not_retried(self):
        old=dict(video_status='failed_before_post',account='fb03',reason='Locator.input_value '+r.CAPTION_ERROR)
        self.assertFalse(r.allowed_live({'account':'fb03'},dict(status='failed_before_post',error='unknown failure'),old,submitted))
    def test_missing_record_requires_verified_seed_marker(self):
        old=dict(video_status='not_started',account='fb09')
        self.assertFalse(r.allowed_live({'account':'fb09'},dict(status='failed_before_post'),old,submitted))
        self.assertTrue(r.allowed_live({'account':'fb09'},dict(status='failed_before_post',verified_missing_prepost=r.AUTH),old,submitted))
    def test_baseline_is_archived_before_report_is_updated(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();blob=json.dumps(dict(request_sha256=r.REQUEST_SHA,material_date=r.DAY,comments_enabled=False)).encode();sha=hashlib.sha256(blob).hexdigest()
            original=root/'logs'/r.REPORT;original.write_bytes(blob)
            with patch.object(r,'REPORT_SHA',sha):
                first=r.baseline(root);original.write_text('new report');self.assertEqual(r.baseline(root),first)
            self.assertEqual(next((root/'logs').glob('nov23-repair-baseline-*')).read_bytes(),blob)
    def test_changed_unreviewed_baseline_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();(root/'logs'/r.REPORT).write_text('{}')
            with self.assertRaises(ValueError):r.baseline(root)
    def test_original_consumed_repair_claim_is_not_reset(self):
        import retry_eligible60_prepost_20261119 as extra
        row=dict(status='failed_before_post')
        entry,reason=extra.checked({'key':'key'},{'key':row},{'jobs':{'key':{'phase':'consumed'}}},{})
        self.assertIsNone(entry);self.assertIn('使用本次补发机会',reason)

class MissingProofTests(unittest.TestCase):
    def setUp(self):
        self.job=dict(key='key',account='fb09',target='personal')
        self.value=dict(sha256='source',created_at='2026-11-23T10:00:00+00:00')
        self.attempt=dict(key='key',action='manual_required',started_at='2026-11-23T10:05:00+00:00',error='fb09 的 Chrome 资料仍被占用；本次尚未启动浏览器或选择视频。')
        self.report=dict(manifest='frozen.json',attempts=[self.attempt],rows=[dict(key='key',video_status='not_started')])
        self.retries=[dict(self.attempt)];self.claims=dict(schema='automatic-before-post-retry-claims-v1',jobs={'key':dict(source_manifest='frozen.json',source_sha256='source',original_record=None)})
    def prove(self):return r.missing_proof(self.job,self.value,self.report,self.retries,self.claims,{},submitted)
    def test_two_matching_before_browser_attempts_establish_failure(self):
        self.assertEqual(self.prove()['attempt_count'],2)
    def test_retry_source_and_original_record_must_match(self):
        self.claims['jobs']['key']['source_sha256']='other';self.assertIsNone(self.prove())
        self.claims['jobs']['key']['source_sha256']='source';self.claims['jobs']['key']['original_record']={'status':'published'};self.assertIsNone(self.prove())
    def test_no_retry_attempt_is_not_enough(self):
        self.retries=[];self.assertIsNone(self.prove())
    def test_any_finished_or_submitted_attempt_prevents_reconstruction(self):
        self.retries=[dict(self.attempt,action='finished')];self.assertIsNone(self.prove())
        self.retries=[dict(self.attempt,post_intent_at='time')];self.assertIsNone(self.prove())
    def test_published_result_contradiction_is_preserved(self):
        self.report['rows'][0]['video_status']='published';self.assertIsNone(self.prove())
    def test_non_browser_failure_is_not_reconstructed(self):
        self.retries[0]['error']='fb09 failure after file selection';self.assertIsNone(self.prove())
    def test_comment_ledger_proof_prevents_reconstruction(self):
        ledger={'comment':dict(video_job='key',status='sending')}
        self.assertIsNone(r.missing_proof(self.job,self.value,self.report,self.retries,self.claims,ledger,submitted))

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
@unittest.skipUnless(PWSH.exists(),'Needs PowerShell runtime')
class Fb09ReleaseTests(unittest.TestCase):
    def run_case(self,mode='old',other_worker=False,active=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir()
            (root/'logs/publish_state.json').write_text(json.dumps({'old':dict(account='fb09',status='posting')} if active else {}))
            command='python "'+str(root/'repair.py')+'" "'+str(root)+'"'
            packet=root/'packet.json';packet.write_text(json.dumps(dict(root=str(root),starter_pid=500,allowed=[dict(pid=500,created='2026-11-24T08:00:00.0000000Z',command_sha=hashlib.sha256(command.encode()).hexdigest())])))
            harness=root/'test.ps1';script=Path(__file__).with_name('release_fb09_orphan_20261124.ps1')
            body=r'''
. $env:TEST_SCRIPT -FunctionsOnly
$global:killed=@();$global:ownerQueries=0
$global:helper=[pscustomobject]@{ProcessId=500;CommandLine=$env:TEST_COMMAND;ExecutablePath='python';CreationDate=[datetime]'2026-11-24T08:00:00Z'}
function Get-CimInstance {param($Class,$Filter)
 if($Filter -like "Name='python*OR*"){
  $global:helper
  if($env:TEST_WORKER -eq '1'){[pscustomobject]@{ProcessId=501;CommandLine=$env:TEST_COMMAND;ExecutablePath='python';CreationDate=[datetime]'2026-11-24T07:00:00Z'}}
 }elseif($Filter -like 'ProcessId=*'){$global:helper}else{
  if($global:killed.Count){return}
  $global:ownerQueries++
  $profile=Join-Path $env:TEST_ROOT $(if($env:TEST_MODE -eq 'other_profile'){'profiles/fb10'}else{'profiles/fb09'})
  $pidValue=if($env:TEST_MODE -eq 'changed_owner' -and $global:ownerQueries -gt 1){13209}else{13208}
  $headless=if($env:TEST_MODE -eq 'normal'){''}else{' --headless=new'}
  $created=if($env:TEST_MODE -eq 'new'){[datetime]'2026-11-24T09:00:00Z'}else{[datetime]'2026-11-23T09:00:00Z'}
  [pscustomobject]@{ProcessId=$pidValue;CommandLine=('chrome --user-data-dir="'+$profile+'"'+$headless);CreationDate=$created}
 }
}
function Get-Process {param($Id)
 $start=if($env:TEST_MODE -eq 'recycled'){[datetime]'2026-11-23T09:00:01Z'}else{[datetime]'2026-11-23T09:00:00Z'}
 $handle=if($env:TEST_MODE -eq 'visible'){123}else{0}
 $p=[pscustomobject]@{Handle=$Id;Id=$Id;ProcessName='chrome';StartTime=$start;MainWindowHandle=$handle;HasExited=$false}
 $p | Add-Member ScriptMethod Refresh {}
 $p | Add-Member ScriptMethod Dispose {}
 $p | Add-Member ScriptMethod Kill {$global:killed+=$this.Id;$this.HasExited=$true}
 $p | Add-Member ScriptMethod WaitForExit {param($Timeout) $true}
 $p
}
try{Release-Fb09Orphan $env:TEST_PACKET;'completed'}catch{'blocked: '+$_.Exception.Message}
'killed='+($global:killed -join ',')
'''
            harness.write_text(body,encoding='utf-8-sig')
            env=dict(os.environ,TEST_SCRIPT=str(script),TEST_PACKET=str(packet),TEST_ROOT=str(root),TEST_COMMAND=command,TEST_MODE=mode,TEST_WORKER=str(int(other_worker)),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(harness)],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);return result.stdout
    def test_only_verified_old_headless_fb09_is_closed(self):
        output=self.run_case();self.assertIn('completed',output);self.assertIn('killed=13208',output)
    def test_normal_visible_new_recycled_and_changed_owners_are_preserved(self):
        for mode in ['normal','visible','new','recycled','changed_owner']:
            with self.subTest(mode=mode):
                output=self.run_case(mode);self.assertIn('blocked:',output);self.assertIn('killed=\n',output)
    def test_other_profile_is_untouched(self):
        output=self.run_case('other_profile');self.assertIn('completed',output);self.assertIn('killed=\n',output)
    def test_other_project_worker_is_not_exempt(self):
        output=self.run_case(other_worker=True);self.assertIn('blocked:',output);self.assertIn('killed=\n',output)
    def test_submitting_account_is_not_closed(self):
        output=self.run_case(active=True);self.assertIn('blocked:',output);self.assertIn('killed=\n',output)

class StarterTests(unittest.TestCase):
    def test_repair_runtime_contains_fixed_rich_editor_and_original_video_only_policy(self):
        import start_repair_nov23_caption_fb09_20261124 as starter
        for name,data in starter.ADDITIONS.items():self.assertEqual(data,Path(__file__).with_name(name).read_bytes())
        self.assertIn(b'1.1-contenteditable-caption-audience-recovery',starter.ADDITIONS['reel_audience_dialog_recovery.py'])
        self.assertNotIn(b'.input_value(',starter.ADDITIONS['reel_audience_dialog_recovery.py'])
        manifest={name:hashlib.sha256(data).hexdigest() for name,data in starter.ADDITIONS.items()}
        self.assertEqual(starter.FINGERPRINT,hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest())
    def test_new_launch_ack_is_required_and_state_is_not_modified_by_starter(self):
        import start_repair_nov23_caption_fb09_20261124 as starter
        import start_publish_eligible60_real_20261123 as base
        from types import SimpleNamespace as N
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();(root/'.venv/Scripts').mkdir(parents=True);(root/'.venv/Scripts/python.exe').touch();(root/'upload_config.json').write_text('{}');(root/'material-staging').mkdir()
            r.videos.save(root/'material-staging/eligible60-20261123-pending-import.json',dict(complete=True))
            status=root/r.STATUS;r.videos.save(status,dict(launch_id='old',phase='running',pid=1,message='old'))
            calls=[]
            class Process:
                def __init__(self,args,**kwargs):self.launch=kwargs['env']['FB_NOV23_REPAIR_LAUNCH'];self.calls=0;calls.append(self)
                def poll(self):
                    self.calls+=1;r.videos.save(status,dict(launch_id=self.launch,phase='running',pid=2,message='repair verified'));return None
            with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download_base',return_value=base),patch.object(base,'download',return_value={}),patch.object(starter.subprocess,'run'),patch.object(starter.subprocess,'Popen',Process),patch.object(starter.time,'sleep'):
                self.assertEqual(starter.start(root),0)
            self.assertEqual(calls[0].calls,2);self.assertFalse((root/'logs/publish_state.json').exists())

if __name__=='__main__':unittest.main()
