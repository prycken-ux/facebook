import contextlib,copy,json,os,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import MagicMock,patch
import publish_nov23_videos_only_20261124 as v

class CommentPolicyTests(unittest.TestCase):
    def app(self):
        native=MagicMock(return_value=True)
        app=N(first=N(upload=N(run_entry=native),priority=N(daily=N(backfill=MagicMock()),comment_retry=N(run=MagicMock()))),pending_comments=N(installed=MagicMock()))
        return app,native
    def test_lowest_upload_boundary_disables_immediate_and_deferred_comments(self):
        app,native=self.app();entry=dict(account='fb04',target='personal',_authorized_comment_text='old comment',_immediate_verified_comment=True,caption='unchanged')
        before=copy.deepcopy(entry)
        with v.comments_disabled(app):
            app.first.upload.run_entry(entry,{},Path('state.json'),True,filename='original.mp4',expected_job_key='a'*64,defer_comments=False,retry_before_post=True)
        actual=native.call_args
        self.assertNotIn('_authorized_comment_text',actual.args[0]);self.assertNotIn('_immediate_verified_comment',actual.args[0])
        self.assertEqual(actual.args[0]['caption'],'unchanged');self.assertTrue(actual.kwargs['defer_comments']);self.assertTrue(actual.kwargs['retry_before_post'])
        self.assertEqual(actual.kwargs['expected_job_key'],'a'*64);self.assertEqual(entry,before)
    def test_pending_lookup_backfill_and_retry_never_call_old_implementations(self):
        app,_=self.app();pending=app.pending_comments.installed;backfill=app.first.priority.daily.backfill;retry=app.first.priority.comment_retry.run
        rows=[{'old':'preserved'}]
        with v.comments_disabled(app):
            with app.pending_comments.installed(None,None,None) as seen:self.assertEqual(seen,set())
            self.assertIs(app.first.priority.daily.backfill({},None,rows=rows),rows)
            self.assertEqual(app.first.priority.comment_retry.run('original.json'),[])
        pending.assert_not_called();backfill.assert_not_called();retry.assert_not_called()
        self.assertIs(app.first.priority.daily.backfill,backfill)

class VideoWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'logs').mkdir()
    def fake_app(self):
        req=dict(sha256='r'*64);source=dict(sha256='s'*64);material=dict(payload=dict(assignments=[]));controller=dict(request_sha256=req['sha256'],waves=[dict(manifest='frozen.json',sha256='wave')],modes={},pending={})
        first=N(upload=N(ROOT=self.root,read_json=lambda p,d:copy.deepcopy(controller)),workflow=N(require_versions=MagicMock()),batch=N(excluded_accounts=MagicMock()),locked=lambda:contextlib.nullcontext())
        app=N(first=first,current_workers=MagicMock(return_value=[]),browser=N(staged=N(lock_recovery=N(recover_locks=MagicMock()))),owned=N(reservation=MagicMock()),exclusions=MagicMock(),active_reservation=MagicMock(),
              allocation=MagicMock(return_value=(None,source,None,material)),request=MagicMock(return_value=req),save_availability=MagicMock(),background_policy=N(save_background=MagicMock(),retire_foreground_modes=MagicMock()),
              recover_waves=MagicMock(),registered_ready=MagicMock(return_value=set()),add_wave=MagicMock(),run_phase=MagicMock(),auto_register_pending=MagicMock(),PAUSED={'fb17','fb23'})
        return app
    def test_original_videos_and_safe_retry_continue_without_any_comment_phase(self):
        app=self.fake_app()
        with patch.object(v,'video_report',return_value=3) as report:
            self.assertEqual(v.execute_current(app,self.root,True),3)
        self.assertEqual([call.args[0] for call in app.run_phase.call_args_list],['videos','retry'])
        self.assertTrue(app.browser.staged.lock_recovery.recover_locks.called);self.assertTrue(report.called)
        policy=json.loads((self.root/'logs/nov23-videos-only-policy.json').read_text())
        self.assertFalse(policy['comments_enabled']);self.assertFalse(policy['ai_label']);self.assertEqual(policy['material_date'],'2026-11-23')
    def test_other_live_worker_blocks_before_locks_or_publication(self):
        app=self.fake_app();app.current_workers.return_value=[{'pid':99999}]
        with self.assertRaisesRegex(ValueError,'99999'):v.execute_current(app,self.root,True)
        app.run_phase.assert_not_called();app.browser.staged.lock_recovery.recover_locks.assert_not_called()
    def test_missing_real_confirmation_does_not_start(self):
        app=self.fake_app()
        with self.assertRaises(ValueError):v.execute_current(app,self.root,False)
        app.run_phase.assert_not_called()
    def test_video_complete_does_not_require_comments_or_change_the_ledger(self):
        jobs=[dict(key='a',account='fb01',target='page01'),dict(key='b',account='fb17',target='personal')]
        state={'a':dict(status='published',comment_status='not_started'),'b':dict(status='failed_before_post',comment_status='not_started')};before=copy.deepcopy(state)
        first=N(upload=N(read_json=lambda *a:state,save_json=MagicMock()),archive=N(checked_json=lambda p:dict(payload=dict(jobs=jobs))))
        app=N(first=first,PAUSED={'fb17'});controller=dict(waves=[dict(manifest='frozen.json')],pending={},complete=False)
        material=dict(payload=dict(assignments=[dict(account=j['account'],target=j['target'],files=[dict(destination_name=j['key']+'.mp4')]) for j in jobs]))
        path=self.root/'logs/controller.json'
        self.assertEqual(v.video_report(app,self.root,dict(sha256='request'),material,controller,path),0)
        self.assertEqual(state,before);self.assertFalse(controller['complete']);self.assertTrue(controller['video_only_complete'])
        report=json.loads((self.root/'logs/controller-videos-only.json').read_text());self.assertEqual(report['counts']['published'],1);self.assertEqual(report['counts']['failed_before_post'],0);self.assertFalse(report['comments_enabled'])
    def test_stop_failure_prevents_any_new_video_work(self):
        with patch.object(v.subprocess,'run',return_value=N(returncode=1,stdout=b'guard refused',stderr=b'')):
            with self.assertRaises(RuntimeError):v.stop_comments(self.root)
    def test_current_worker_check_is_bound_to_new_entry_before_authorization_context(self):
        (self.root/'normal_chrome_batch.py').write_text("STARTUP_WAIT_VERSION='1.0-wait-for-endpoint-after-launcher-exit'")
        (self.root/'request.json').write_text('{}')
        policy,_=CommentPolicyTests().app();policy.content_today=N(CONTENT={'sha256':'content'});policy.request=MagicMock();policy.current_workers=MagicMock();policy.execute_current=MagicMock()
        day=N(app=policy,CONTENT_SHA='content',REQUEST='request.json',allocation=MagicMock(return_value=(None,None,None,None)),inspect_workers=MagicMock(side_effect=AssertionError('old worker binding used')))
        @contextlib.contextmanager
        def authorized():
            with patch.object(policy,'current_workers',side_effect=day.inspect_workers):yield
        day.authorized_context=authorized
        policy.execute=MagicMock(side_effect=lambda *args:0 if policy.current_workers(self.root)==[] else 1)
        with patch.object(v,'inspect_workers',return_value=[]) as workers,patch.object(v,'stop_comments') as stop:
            self.assertEqual(v.execute(day,self.root),0)
        day.inspect_workers.assert_not_called();self.assertEqual(workers.call_count,2);stop.assert_called_once_with(self.root)
    def test_source_preflight_failure_never_stops_existing_monitor(self):
        (self.root/'normal_chrome_batch.py').write_text("STARTUP_WAIT_VERSION='1.0-wait-for-endpoint-after-launcher-exit'")
        day=N(app=N(content_today=N(CONTENT={'sha256':'content'})),CONTENT_SHA='content',inspect_workers=MagicMock(),authorized_context=contextlib.nullcontext,allocation=MagicMock(side_effect=ValueError('bad source')))
        with patch.object(v,'stop_comments') as stop:
            with self.assertRaisesRegex(ValueError,'bad source'):v.execute(day,self.root)
        stop.assert_not_called()

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
@unittest.skipUnless(PWSH.exists(),'Requires PowerShell runtime')
class MonitorStopTests(unittest.TestCase):
    def run_case(self,recycled=False,wrong_hash=False,other_script=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir()
            (root/'logs/eligible60-2026-11-23-deadline.json').write_text(json.dumps(dict(pid=27488,run_id='a'*32,material_date='2026-11-23',updated_at='2026-11-24T08:00:00Z')))
            harness=root/'test.ps1';script=Path(__file__).with_name('stop_nov23_comment_monitor_20261124.ps1')
            body=r'''
. $env:TEST_STOPPER -FunctionsOnly
$global:killed=@()
function Get-SharedHash {param($Path) if($env:TEST_HASH -eq '1'){'wrong'}else{'659e4cfbdf5c69216696babaaa1b15993a0a1a8d02a3b8bc41e9617b03c3eb6a'}}
$path=Join-Path $env:TEST_ROOT 'material-staging/tools/comment-deadline-df2c293a153a5f25/resume_nov23_comment_deadline_20261124.py'
if($env:TEST_OTHER -eq '1'){$path=Join-Path $env:TEST_ROOT 'other_task.py'}
$global:owner=[pscustomobject]@{ProcessId=27488;ParentProcessId=1;Name='python.exe';CommandLine=('python "'+$path+'" "'+$env:TEST_ROOT+'"');CreationDate=[datetime]'2026-11-24T07:00:00Z'}
$global:child=[pscustomobject]@{ProcessId=40000;ParentProcessId=27488;Name='python.exe';CreationDate=[datetime]'2026-11-24T07:01:00Z'}
$global:browser=[pscustomobject]@{ProcessId=50000;ParentProcessId=40000;Name='chrome.exe';CreationDate=[datetime]'2026-11-24T07:02:00Z'}
function Get-CimInstance {param($Class,$Filter)
 if($Filter){$global:owner}else{$global:owner;$global:child;$global:browser;[pscustomobject]@{ProcessId=99999;ParentProcessId=1;Name='chrome.exe';CreationDate=[datetime]'2026-11-24T07:03:00Z'}}
}
function Get-Process {param($Id,$ErrorAction)
 $row=if($Id -eq 27488){$global:owner}elseif($Id -eq 40000){$global:child}else{$global:browser}
 $start=if($env:TEST_RECYCLED -eq '1'){$row.CreationDate.AddSeconds(1)}else{$row.CreationDate}
 $p=[pscustomobject]@{Id=$Id;Handle=$Id;StartTime=$start;HasExited=$false}
 $p | Add-Member ScriptMethod Dispose {}
 $p | Add-Member ScriptMethod Kill {$global:killed+=$this.Id;$this.HasExited=$true}
 $p | Add-Member ScriptMethod WaitForExit {param($Timeout) $true}
 $p
}
try{Stop-Nov23CommentMonitor $env:TEST_ROOT;'completed'}catch{'blocked: '+$_.Exception.Message}
'killed='+($global:killed -join ',')
'''
            harness.write_text(body,encoding='utf-8-sig')
            env=dict(os.environ,TEST_STOPPER=str(script),TEST_ROOT=str(root),TEST_RECYCLED=str(int(recycled)),TEST_HASH=str(int(wrong_hash)),TEST_OTHER=str(int(other_script)),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(harness)],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);return result.stdout
    def test_only_pinned_comment_monitor_and_descendants_are_stopped(self):
        out=self.run_case();self.assertIn('completed',out);self.assertIn('killed=27488,40000,50000',out);self.assertNotIn('99999',out)
    def test_recycled_pid_is_never_terminated(self):
        out=self.run_case(recycled=True);self.assertIn('blocked:',out);self.assertIn('killed=\n',out)
    def test_unknown_driver_hash_is_never_terminated(self):
        out=self.run_case(wrong_hash=True);self.assertIn('blocked:',out);self.assertIn('killed=\n',out)
    def test_other_project_task_is_never_terminated(self):
        out=self.run_case(other_script=True);self.assertIn('blocked:',out);self.assertIn('killed=\n',out)

class StarterTests(unittest.TestCase):
    def test_verified_embedded_runtime_matches_source(self):
        import hashlib
        import start_publish_nov23_videos_only_20261124 as starter
        for name,data in starter.ADDITIONS.items():self.assertEqual(data,Path(__file__).with_name(name).read_bytes())
        manifest={name:hashlib.sha256(data).hexdigest() for name,data in starter.ADDITIONS.items()}
        self.assertEqual(starter.FINGERPRINT,hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest())
    def test_acknowledgment_matches_new_video_only_launch(self):
        import start_publish_nov23_videos_only_20261124 as starter
        import start_publish_eligible60_real_20261123 as base
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();(root/'.venv/Scripts').mkdir(parents=True);(root/'.venv/Scripts/python.exe').touch();(root/'upload_config.json').write_text('{}');(root/'material-staging').mkdir()
            v.save(root/'material-staging/eligible60-20261123-pending-import.json',dict(complete=True))
            status=root/'logs/eligible60-2026-11-23-videos-only-status.json';v.save(status,dict(launch_id='old',phase='running',pid=1,message='old'))
            calls=[]
            class Process:
                def __init__(self,args,**kwargs):
                    self.launch=kwargs['env']['FB_NOV23_VIDEO_LAUNCH'];self.calls=0;calls.append(self)
                    self.args=args
                def poll(self):
                    self.calls+=1;v.save(status,dict(launch_id=self.launch,phase='running',pid=2,message='videos only'));return None
            with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download_base',return_value=base),patch.object(base,'download',return_value={}),patch.object(starter.subprocess,'run'),patch.object(starter.subprocess,'Popen',Process),patch.object(starter.time,'sleep'):
                self.assertEqual(starter.start(root),0)
            self.assertEqual(calls[0].calls,2);self.assertIn('publish_nov23_videos_only_20261124.py',calls[0].args[2]);self.assertFalse((root/'logs/publish_state.json').exists())

if __name__=='__main__':unittest.main()
