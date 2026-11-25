import contextlib,copy,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import MagicMock,patch
import comment_target_watchdog_20261125 as w

class WatchdogTests(unittest.TestCase):
    def test_comment_and_video_have_independent_hard_budgets(self):
        video=dict(state='started',kind='video',started=10);comment=dict(video,kind='comment')
        self.assertFalse(w.deadline_reached(video,189.9));self.assertTrue(w.deadline_reached(video,190))
        self.assertFalse(w.deadline_reached(comment,189.9));self.assertTrue(w.deadline_reached(comment,190))
        self.assertFalse(w.deadline_reached(dict(comment,state='finished'),1000))
    def test_operation_must_bind_exact_source_request_and_target(self):
        p=dict(queue_id='request',material_source_date=w.DAY,jobs=[dict(key='a',account='fb01',target='page01')])
        day=N(first=N(archive=N(checked_json=lambda path:dict(sha256='sha',payload=p))))
        op=dict(run_id='run',attempt='attempt',kind='video',manifest='frozen-material-2026-11-25-'+('a'*16)+'.json',manifest_sha256='sha',key='a',account='fb01',target='page01')
        self.assertTrue(w.operation_valid(day,Path('/tmp'),op,'run','attempt','request'))
        for changed in [dict(run_id='other'),dict(attempt='old'),dict(key='wrong'),dict(target='personal'),dict(manifest='../other.json')]:
            self.assertFalse(w.operation_valid(day,Path('/tmp'),dict(op,**changed),'run','attempt','request'))
        p['material_source_date']='2026-11-23';self.assertFalse(w.operation_valid(day,Path('/tmp'),op,'run','attempt','request'))

class WorkerGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'logs').mkdir()
        self.progress=self.root/'progress.json';self.operation=self.root/'operation.json';w.files.save(self.progress,w.progress_new('run','request'))
        self.jobs=[dict(key=k,account=a,target='personal',filename=k+'.mp4') for k,a in [('a','fb03'),('b','fb04')]]
        self.value=dict(sha256='sha',payload=dict(queue_id='request',material_source_date=w.DAY,jobs=self.jobs))
        self.events=[];self.rows={j['key']:dict(status='published',comment_status='deferred') for j in self.jobs}
        self.daily=N(backfill=MagicMock(side_effect=lambda value,*a,**kw:self.events.append(('comment',set(kw['only_keys'])))),close_selected_window=MagicMock())
        self.retry=N(candidates=MagicMock(return_value=([(j,j['key'],'retry') for j in self.jobs],[])))
        self.first=N(archive=N(checked_json=lambda p:self.value),upload=N(read_json=lambda p,d:self.rows,wait_for_receipt=MagicMock(return_value='receipt'),run_entry=MagicMock(side_effect=lambda entry,*a,**kw:self.events.append(('video',entry['account'])))),
                     priority=N(daily=self.daily,comment_retry=self.retry),normal=N(launch_normal=MagicMock(return_value='browser'),close_selected_window=MagicMock()),
                     batch=N(validate_job=MagicMock(side_effect=lambda job,**kw:dict(job)),close_selected_window=MagicMock()),close_selected_window=MagicMock())
        def native(phase,req,source,journal,material,wave,controller,deferred):
            if phase in {'videos','retry'}:
                for job in self.jobs:
                    self.first.batch.validate_job(job)
                    self.first.batch.close_selected_window(job['account'])
                    self.first.upload.run_entry(job,{},self.root/'state.json',True,filename=job['filename'],expected_job_key=job['key'])
            else:self.daily.backfill(self.value,None,only_keys={j['key'] for j in self.jobs},rows=[])
        self.app=N(first=self.first,run_phase=native,queued=N(retry=N(decide=MagicMock(return_value=(True,'safe')))),PAUSED=set())
        self.day=N(app=self.app,first=self.first);self.wave=dict(manifest='frozen.json',sha256='sha')
    def phase(self,phase='comments'):
        with w.guarded_worker(self.day,self.root,'run','attempt',self.progress,self.operation):
            self.app.run_phase(phase,dict(sha256='request'),None,None,None,self.wave,{}, {})
    def test_comments_are_one_target_at_a_time_and_complete_tokens_persist(self):
        self.phase();self.assertEqual(self.events,[('comment',{'a'}),('comment',{'b'})]);op=w.read(self.operation);self.assertEqual(op['state'],'finished');self.assertEqual(op['completed'],['comments:a','comments:b'])
    def test_video_timer_covers_preclose_and_upload(self):
        self.phase('videos');self.assertEqual(self.events,[('video','fb03'),('video','fb04')]);op=w.read(self.operation);self.assertEqual(op['kind'],'video');self.assertEqual(op['state'],'finished')
    def test_receipt_shares_video_operation_budget_including_browser_preparation(self):
        captured=[]
        def native(entry,*args,**kwargs):
            self.first.upload.wait_for_receipt('page','button',started_at=999999)
            captured.append(w.read(self.operation)['started'])
        self.first.upload.run_entry.side_effect=native
        self.phase('videos')
        calls=self.first.upload.wait_for_receipt.call_args_list
        self.assertEqual(len(calls),2)
        for call,started in zip(calls,captured):
            self.assertEqual(call.kwargs['started_at'],started)
            self.assertEqual(call.kwargs['timeout_ms'],170000)
    def test_comment_timeout_skip_does_not_suppress_other_targets(self):
        p=w.read(self.progress);p['skipped_comments']['a']={'reason':'timeout'};w.files.save(self.progress,p)
        self.phase();self.assertEqual(self.events,[('comment',{'b'})])
    def test_video_timeout_is_rejected_before_close_or_new_retry_claim(self):
        p=w.read(self.progress);p['skipped_video']['a']={'reason':'timeout'};w.files.save(self.progress,p)
        old=self.app.queued.retry.decide
        with w.guarded_worker(self.day,self.root,'run','attempt',self.progress,self.operation):
            with self.assertRaises(RuntimeError):self.app.run_phase('videos',dict(sha256='request'),None,None,None,self.wave,{}, {})
            self.assertFalse(self.app.queued.retry.decide(self.jobs[0],None,None,None,None)[0])
        self.assertEqual(self.events,[]);old.assert_not_called();self.first.close_selected_window.assert_not_called()
    def test_old_profile_busy_is_rechecked_before_close_retry(self):
        with patch.object(w.profiles,'require_profile_free',side_effect=[RuntimeError('fb03 的 Chrome 资料仍被占用'),None,None]),patch.object(w,'release_idle') as release:self.phase('videos')
        release.assert_called_once_with(self.day,self.root,'fb03');self.assertEqual(len(self.events),2)
        self.first.close_selected_window.assert_not_called()
    def test_busy_normal_window_is_not_closed_or_uploaded_over(self):
        with patch.object(w.profiles,'require_profile_free',side_effect=RuntimeError('fb03 的 Chrome 资料仍被占用')),patch.object(w,'release_idle',side_effect=RuntimeError('normal browser retained')):
            with self.assertRaisesRegex(RuntimeError,'normal browser retained'):self.phase('videos')
        self.first.close_selected_window.assert_not_called();self.assertEqual(self.events,[])
    def test_successful_comments_are_not_resent(self):
        self.rows['a']['comment_status']='sent';self.phase();self.assertEqual(self.events,[('comment',{'b'})])
    def test_wrong_source_stops_before_any_browser_or_comment(self):
        self.value['payload']['material_source_date']='2026-11-23'
        with self.assertRaises(ValueError):self.phase()
        self.assertFalse(self.operation.exists());self.assertEqual(self.events,[])

@unittest.skipIf(sys.platform=='win32','Uses Linux process groups to simulate actual blocked worker cleanup')
class ActualBlockedWorkerTests(unittest.TestCase):
    def test_real_blocked_worker_switches_to_next_video_and_comment_target(self):
        for kind in ['video','comment']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'logs').mkdir();jobs=[dict(key='bad',account='fb03',target='personal')]
                value=dict(sha256='a'*64,payload=dict(queue_id='request',material_source_date=w.DAY,jobs=jobs))
                req=dict(sha256='request');day=N(allocation=lambda p:(None,None,None,None),authorized_context=contextlib.nullcontext,inspect_workers=MagicMock(),
                    app=N(request=lambda *a:req,browser=N(staged=N(lock_recovery=N(recover_locks=lambda p:None)))),
                    first=N(locked=contextlib.nullcontext,archive=N(checked_json=lambda p:value)))
                children=[]
                class Child:
                    def __init__(self,args,env,cwd,output):
                        index=len(children)
                        code='''import json,os,sys,time,subprocess
from pathlib import Path
r=Path(sys.argv[1]);i=int(sys.argv[2]);attempt=os.environ['FB_PUBLISH_LAUNCH_ID']
op=dict(run_id='run',attempt=attempt,state='started' if i==0 else 'finished',kind=sys.argv[3],started=time.monotonic(),key='bad',account='fb03',target='personal',manifest='frozen-material-2026-11-25-'+'a'*16+'.json',manifest_sha256='a'*64,completed=[])
if i==0:
 p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);(r/'descendant.pid').write_text(str(p.pid))
(r/'logs'/('nov25-comments-operation-'+attempt+'.json')).write_text(json.dumps(op))
if i==0:time.sleep(60)
'''
                        self.p=subprocess.Popen([sys.executable,'-c',code,str(root),str(index),kind],env=env,stdout=output,stderr=output,start_new_session=True);self.pid=self.p.pid;self.stopped=False;children.append(self)
                    def poll(self):return self.p.poll()
                    def stop(self):self.stopped=True;os.killpg(self.pid,signal.SIGKILL);self.p.wait(timeout=3)
                    def close(self):
                        if self.poll() is None:self.stop()
                with patch.object(w,'mutex',lambda p:contextlib.nullcontext()),patch.object(w,'inspect_workers',return_value=[]),patch.object(w,'VIDEO_SECONDS',.35),patch.object(w,'COMMENT_SECONDS',.35):
                    self.assertEqual(w.supervisor(day,root,'run',child_factory=Child),0)
                self.assertEqual(len(children),2);self.assertTrue(children[0].stopped)
                progress=w.read(root/'logs/nov25-comments-progress-run.json');slot='skipped_video' if kind=='video' else 'skipped_comments';self.assertIn('bad',progress[slot])
                descendant=int((root/'descendant.pid').read_text());stat=Path('/proc')/str(descendant)/'stat';self.assertTrue(not stat.exists() or stat.read_text().split()[2]=='Z')

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
@unittest.skipUnless(PWSH.exists(),'Needs PowerShell runtime')
class QueueTests(unittest.TestCase):
    def test_waits_for_workers_or_distribution_without_launching_python(self):
        for busy in [True,False]:
            with self.subTest(busy=busy),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'logs').mkdir();queue=Path(__file__).with_name('queue_comment_nov25_20261125.ps1');harness=root/'test.ps1'
                body=r'''
. $env:TEST_QUEUE -FunctionsOnly
function Get-CimInstance {param($Class,$Filter) if($env:TEST_BUSY -eq '1'){[pscustomobject]@{ProcessId=22964;CommandLine=('python '+$env:TEST_ROOT+'/repair.py');ExecutablePath='python'}}}
function Start-Sleep {param($Seconds,$Milliseconds)
 $path=Join-Path $env:TEST_ROOT ('logs/nov25-comments-queue-'+('a'*32)+'.json')
 $global:observed=(Get-Content -LiteralPath $path -Raw | ConvertFrom-Json).phase
 throw 'test ends after first wait'
}
Start-Nov25Queue $env:TEST_ROOT 'not-a-publisher.py' 'invalid-hash-no-start-allowed' ('a'*32)
'observed='+$global:observed
'''
                harness.write_text(body,encoding='utf-8-sig');env=dict(os.environ,TEST_QUEUE=str(queue),TEST_ROOT=str(root),TEST_BUSY=str(int(busy)),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
                result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-NonInteractive','-File',str(harness)],env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr);self.assertIn('observed='+('waiting_workers' if busy else 'waiting_distribution'),result.stdout)
                self.assertFalse((root/'logs/eligible60-2026-11-25-comments-repair-status.json').exists())

if __name__=='__main__':unittest.main()
