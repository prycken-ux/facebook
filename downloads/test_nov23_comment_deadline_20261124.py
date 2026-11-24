import contextlib,ctypes,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

import resume_nov23_comment_deadline_20261124 as d

class DeadlineTests(unittest.TestCase):
    def test_exact_three_minute_threshold_and_run_binding(self):
        op=dict(run_id='run',attempt='attempt',state='started',phase='comments',started=10)
        self.assertFalse(d.expired(op,'run','attempt',189.9))
        self.assertTrue(d.expired(op,'run','attempt',190))
        self.assertFalse(d.expired(op,'other','attempt',900))
        self.assertFalse(d.expired(op,'run','old',900))
        self.assertFalse(d.expired(dict(op,state='finished'),'run','attempt',900))
        self.assertFalse(d.expired(dict(op,phase='videos'),'run','attempt',900))
    def test_only_unfinished_comment_begin_identifies_old_stall(self):
        text='待核实视频进入原评论定位： fb10 page03 ；不重新上传。\n只读核对候选 2 / 19\n'
        self.assertEqual(d.stuck_pair(text),('fb10','page03'))
        self.assertIsNone(d.stuck_pair(text+'本次视频评论待定位，先继续其他目标： fb10 page03\n'))
        self.assertIsNone(d.stuck_pair('开始本批原视频： fb01 page01\n'))
        self.assertEqual(d.stuck_pair(text+'给本批已成功视频评论： fb04 personal file.mp4\n'),('fb04','personal'))
    def test_completed_merge_rejects_other_worker(self):
        p=d.fresh_progress('run','sha')
        d.merge_completed(p,dict(run_id='run',attempt='old',completed=['comments:x']),'run','new')
        self.assertEqual(p['completed'],[])
        d.merge_completed(p,dict(run_id='run',attempt='new',completed=['comments:x']),'run','new')
        self.assertEqual(p['completed'],['comments:x'])
    def test_progress_request_and_limit_are_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'progress.json';d.save(path,d.fresh_progress('run','source'))
            self.assertEqual(d.checked_progress(path,'run','source')['limit_seconds'],180)
            with self.assertRaises(ValueError):d.checked_progress(path,'run','other_source')

class PhaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'logs').mkdir()
        self.jobs=[dict(key=k,account=a,target='personal') for k,a in [('a','fb01'),('b','fb02'),('c','fb17')]]
        self.state={j['key']:dict(status='needs_review',comment_status='lookup_pending') for j in self.jobs}
        self.value=dict(sha256='manifest',payload=dict(queue_id='source',jobs=self.jobs))
        self.progress=self.root/'progress.json';self.op=self.root/'operation.json';d.save(self.progress,d.fresh_progress('run','source'))
        self.seen=[];self.retry_claims=[]
        def backfill(value,*args,**kwargs):
            self.seen.append(set(kwargs['only_keys']));return kwargs.get('rows',[])
        def candidates(*args,**kwargs):return [(j,j['key'],'retry') for j in self.jobs],[]
        daily=N(backfill=backfill);retry=N(candidates=candidates)
        first=N(archive=N(checked_json=lambda p:self.value),upload=N(read_json=lambda p,default:self.state),priority=N(daily=daily,comment_retry=retry))
        def native(phase,req,source,journal,material,wave,controller,deferred):
            if phase in {'comments','comment_retry'}:
                if phase=='comment_retry':self.retry_claims.append([j['key'] for j,_,_ in retry.candidates(self.value)[0]])
                daily.backfill(self.value,None,only_keys={j['key'] for j in self.jobs},rows=[])
            else:self.seen.append(phase)
        self.app=N(run_phase=native,first=first,PAUSED={'fb17'})
        self.wave=dict(manifest='frozen.json',sha256='manifest');self.req=dict(sha256='source')
    def invoke(self,phase='comments'):
        with d.bounded_phases(self.app,self.root,'run','attempt',self.progress,self.op):
            self.app.run_phase(phase,self.req,None,None,None,self.wave,{}, {})
    def test_pending_lookup_and_send_are_filtered_to_single_target(self):
        self.invoke();self.assertEqual(self.seen,[{'a'},{'b'}])
        op=d.read(self.op);self.assertEqual(op['state'],'finished');self.assertEqual(op['completed'],['comments:a','comments:b'])
    def test_timed_out_target_is_skipped_before_browser_or_claim(self):
        p=d.read(self.progress);p['skipped']['a']={'reason':'timeout'};d.save(self.progress,p)
        self.invoke();self.assertEqual(self.seen,[{'b'}])
    def test_completed_target_and_successful_comment_are_preserved(self):
        p=d.read(self.progress);p['completed']=['comments:a'];d.save(self.progress,p)
        self.state['b']['comment_status']='sent';self.invoke();self.assertEqual(self.seen,[])
    def test_retry_claims_never_reserved_for_later_targets(self):
        self.invoke('comment_retry');self.assertEqual(self.retry_claims,[['a'],['b']]);self.assertEqual(self.seen,[{'a'},{'b'}])
    def test_publication_and_prepost_retry_keep_original_behavior(self):
        self.invoke('videos');self.invoke('retry');self.assertEqual(self.seen,['videos','retry']);self.assertFalse(self.op.exists())
    def test_crash_does_not_falsely_complete_active_target(self):
        def blocked(*args,**kwargs):raise RuntimeError('browser blocked')
        self.app.run_phase=blocked
        with self.assertRaises(RuntimeError):self.invoke()
        op=d.read(self.op);self.assertEqual(op['state'],'started');self.assertEqual(op['key'],'a');self.assertEqual(op['completed'],[])
    def test_other_request_frozen_manifest_is_rejected(self):
        self.value['payload']['queue_id']='other'
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.seen,[])

@unittest.skipUnless(sys.platform!='win32','Uses a Linux process-group adapter for actual hang simulation')
class RealBlockedWorkerTest(unittest.TestCase):
    def test_hung_browser_worker_is_killed_and_next_target_completes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();(root/'request.json').write_text('{}')
            req={'sha256':'source'};jobs=[dict(key=k,account=a,target='personal') for k,a in [('bad','fb10'),('good','fb11')]]
            wave=dict(manifest='frozen.json',sha256='manifest');value=dict(sha256='manifest',payload=dict(queue_id='source',jobs=jobs))
            d.save(root/'logs/eligible60-real-publication-source.json',dict(request_sha256='source',waves=[wave]))
            day=N(LOG='logs/run.log',REQUEST='request.json',authorized_context=contextlib.nullcontext,allocation=lambda p:(None,None,None,None),
                  app=N(request=lambda *args:req),first=N(archive=N(checked_json=lambda p:value),upload=N(read_json=lambda *args:{})))
            children=[]
            class Child:
                def __init__(self,args,env,cwd,output):
                    index=len(children);self.index=index;self.stopped=False
                    code='''import json,os,subprocess,sys,time
from pathlib import Path
r=Path(sys.argv[1]);attempt=os.environ['FB_PUBLISH_LAUNCH_ID'];index=int(sys.argv[2]);run='run'
op=dict(run_id=run,attempt=attempt,state='started',phase='comments',started=time.monotonic(),key='bad',account='fb10',target='personal',completed=[])
if index==0:
 p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);(r/'descendant.pid').write_text(str(p.pid))
else:op.update(key='good',account='fb11',state='finished',completed=['comments:good'])
(r/'logs'/('nov23-comment-operation-'+attempt+'.json')).write_text(json.dumps(op))
if index==0:time.sleep(60)
'''
                    self.p=subprocess.Popen([sys.executable,'-c',code,str(root),str(index)],env=env,stdout=output,stderr=output,start_new_session=True);self.pid=self.p.pid;children.append(self)
                def poll(self):return self.p.poll()
                def stop(self):self.stopped=True;os.killpg(self.pid,signal.SIGKILL);self.p.wait(timeout=3)
                def close(self):
                    if self.poll() is None:self.stop()
            started=time.monotonic()
            with patch.object(d,'LIMIT',.35),patch.object(d,'supervisor_mutex',lambda p:contextlib.nullcontext()),patch.object(d,'inspect_workers',return_value=[]),patch.object(d,'stop_stalled_original',return_value=None):
                result=d.supervise(day,root,'run',child_factory=Child)
            self.assertEqual(result,0);self.assertEqual(len(children),2);self.assertTrue(children[0].stopped);self.assertLess(time.monotonic()-started,4)
            p=d.read(root/'logs/nov23-comment-deadline-run.json');self.assertIn('bad',p['skipped']);self.assertIn('comments:good',p['completed'])
            status=d.read(root/d.STATUS);self.assertEqual(status['phase'],'finished')
            descendant=int((root/'descendant.pid').read_text());proc=Path('/proc')/str(descendant)/'stat'
            self.assertTrue(not proc.exists() or proc.read_text().split()[2]=='Z','Owned browser descendant survived timeout')

PWSH=Path('/workspace/.tools/fb-pwsh/pwsh')
@unittest.skipUnless(PWSH.exists(),'Needs PowerShell parser')
class StopperTests(unittest.TestCase):
    def stopper_case(self,recycled=False,fresh=False,changed_on_recheck=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();packet=root/'input.json'
            d.save(packet,dict(root=str(root),queue_sha='expected',log_sha='expected',pid=28688,launch_id='a'*32))
            d.save(root/'logs/eligible60-2026-11-23-queue.json',dict(phase='running',runner='direct_background',material_date='2026-11-23',launch_id='a'*32,pid=28688,time_beijing='2026-11-24T14:00:00+08:00'))
            script=Path(__file__).with_name('stop_stale_nov23_comment_worker_20261124.ps1');harness=root/'test.ps1'
            body=r'''
. $env:TEST_STOPPER -FunctionsOnly
$global:killed=@();$global:queries=0;$global:logHashes=0
function Get-SharedFileSha256 {param($LiteralPath)
 if($LiteralPath.EndsWith('run.log')){
  $global:logHashes++
  if($env:TEST_LOG_CHANGE -eq '1' -and $global:logHashes -gt 1){return 'changed'}
 }
 if($LiteralPath.EndsWith('.py')){'50b3cb7017669f075904dfe9b1c6eb3501b88368911940dea6c2ef5eddf4c35a'}else{'expected'}
}
function Get-Item {param($LiteralPath) [pscustomobject]@{LastWriteTimeUtc=$(if($env:TEST_FRESH -eq '1'){[datetime]::UtcNow}else{[datetime]::UtcNow.AddHours(-1)})}}
$scriptPath=Join-Path $env:TEST_ROOT 'material-staging/tools/b9876463425ed103/publish_eligible60_real_20261123.py'
$global:owner=[pscustomobject]@{ProcessId=28688;ParentProcessId=1;Name='python.exe';CommandLine=('python.exe "'+$scriptPath+'" "'+$env:TEST_ROOT+'"');CreationDate=[datetime]'2026-11-24T05:00:00Z'}
$global:child=[pscustomobject]@{ProcessId=11460;ParentProcessId=28688;Name='chrome.exe';CommandLine='chrome';CreationDate=[datetime]'2026-11-24T05:10:00Z'}
function Get-CimInstance {param($Class,$Filter)
 $global:queries++
 if($Filter){$global:owner}else{$global:owner;$global:child;[pscustomobject]@{ProcessId=99999;ParentProcessId=1;Name='chrome.exe';CommandLine='chrome';CreationDate=[datetime]'2026-11-24T05:20:00Z'}}
}
function Get-Process {param($Id,$ErrorAction)
 $row=if($Id -eq 28688){$global:owner}else{$global:child}
 $start=if($env:TEST_RECYCLED -eq '1'){$row.CreationDate.AddSeconds(1)}else{$row.CreationDate}
 $p=[pscustomobject]@{Id=$Id;Handle=$Id;HasExited=$false;StartTime=$start}
 $p | Add-Member ScriptMethod Dispose {}
 $p | Add-Member ScriptMethod Kill {$global:killed+= $this.Id;$this.HasExited=$true}
 $p | Add-Member ScriptMethod WaitForExit {param($Timeout) $true}
 $p
}
try{Invoke-StaleCommentStop $env:TEST_PACKET;'completed'}catch{'blocked: '+$_.Exception.Message}
'killed='+($global:killed -join ',')
'queries='+$global:queries
'''
            harness.write_text(body,encoding='utf-8-sig')
            env=dict(os.environ,TEST_STOPPER=str(script),TEST_PACKET=str(packet),TEST_ROOT=str(root),TEST_FRESH=str(int(fresh)),TEST_RECYCLED=str(int(recycled)),TEST_LOG_CHANGE=str(int(changed_on_recheck)),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(harness)],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);return result.stdout
    def test_only_verified_old_root_and_descendant_are_stopped(self):
        output=self.stopper_case();self.assertIn('completed',output);self.assertIn('killed=28688,11460',output);self.assertNotIn('99999',output)
    def test_pid_recycling_prevents_all_termination(self):
        output=self.stopper_case(recycled=True);self.assertIn('blocked:',output);self.assertIn('killed=\n',output)
    def test_fresh_logs_prevent_process_queries_and_termination(self):
        output=self.stopper_case(fresh=True);self.assertIn('日志未停滞三分钟',output);self.assertIn('queries=0',output);self.assertIn('killed=\n',output)
    def test_log_change_after_process_pinning_still_prevents_termination(self):
        output=self.stopper_case(changed_on_recheck=True);self.assertIn('日志已有新进度',output);self.assertIn('killed=\n',output)
    def test_script_parses_and_rejects_changed_logs_before_process_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);packet=root/'input.json';d.save(packet,dict(root=str(root),queue_sha='expected',log_sha='expected',pid=28688,launch_id='x'))
            script=Path(__file__).with_name('stop_stale_nov23_comment_worker_20261124.ps1')
            harness=root/'test.ps1'
            harness.write_text(". $env:TEST_STOPPER -FunctionsOnly\nfunction Get-SharedFileSha256 {param($LiteralPath) 'changed'}\nfunction Get-CimInstance {throw 'MUST NOT QUERY PROCESS'}\ntry {Invoke-StaleCommentStop $env:TEST_PACKET;'unsafe'}catch{$_.Exception.Message}\n",encoding='utf-8-sig')
            env=dict(os.environ,TEST_STOPPER=str(script),TEST_PACKET=str(packet),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(harness)],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('队列记录已经变化',result.stdout);self.assertNotIn('unsafe',result.stdout)

    def run_shared_reader(self,body):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=Path(__file__).with_name('stop_stale_nov23_comment_worker_20261124.ps1');harness=root/'test.ps1'
            harness.write_text('. $env:TEST_STOPPER -FunctionsOnly\n'+body,encoding='utf-8-sig')
            env=dict(os.environ,TEST_STOPPER=str(script),TEST_ROOT=str(root),XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            result=subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(harness)],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);return result.stdout
    def test_real_shared_hash_with_open_writer_preserves_content_and_writer(self):
        import hashlib
        body=r'''
function Get-FileHash {throw 'Default file sharing must not be used'}
$path=Join-Path $env:TEST_ROOT 'writer.log'
$writer=[IO.File]::Open($path,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::Read)
try{
 $bytes=[Text.Encoding]::UTF8.GetBytes('原日志：fb10/page03')
 $writer.Write($bytes,0,$bytes.Length);$writer.Flush()
 'first='+(Get-SharedFileSha256 $path)
 'position='+$writer.Position
 $writer.WriteByte(10);$writer.Flush()
 'second='+(Get-SharedFileSha256 $path)
 $writer.WriteByte(88);$writer.Flush()
 'writer-still-open=True'
}finally{$writer.Dispose()}
'final='+([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)))
'''
        output=self.run_shared_reader(body);raw='原日志：fb10/page03'.encode()
        self.assertIn('first='+hashlib.sha256(raw).hexdigest(),output)
        self.assertIn('second='+hashlib.sha256(raw+b'\n').hexdigest(),output)
        self.assertIn('position='+str(len(raw)),output);self.assertIn('writer-still-open=True',output)
        import base64
        self.assertIn('final='+base64.b64encode(raw+b'\nX').decode(),output)
    def test_shared_reader_never_creates_a_missing_log(self):
        output=self.run_shared_reader("$path=Join-Path $env:TEST_ROOT 'missing.log'\ntry{Get-SharedFileSha256 $path;'unsafe'}catch{'blocked'}\n'exists='+(Test-Path -LiteralPath $path)\n")
        self.assertIn('blocked',output);self.assertIn('exists=False',output);self.assertNotIn('unsafe',output)

class WindowsContainmentContractTests(unittest.TestCase):
    def fake_runtime(self,assign=True):
        calls=[]
        class Function:
            def __init__(self,name,callback):self.name=name;self.callback=callback
            def __call__(self,*args):calls.append((self.name,args));return self.callback(*args)
        results=dict(CreateJobObjectW=lambda *a:101,SetInformationJobObject=lambda *a:1,AssignProcessToJobObject=lambda *a:int(assign),ResumeThread=lambda *a:1,CloseHandle=lambda *a:1,TerminateJobObject=lambda *a:1,TerminateProcess=lambda *a:1,GetExitCodeProcess=lambda *a:1,QueryInformationJobObject=lambda *a:1)
        kernel=N(**{name:Function(name,f) for name,f in results.items()})
        def create(*args):calls.append(('CreateProcess',args));return 301,302,303,304
        modules={'_winapi':N(CreateProcess=create),'msvcrt':N(get_osfhandle=lambda f:f)}
        stack=contextlib.ExitStack()
        stack.enter_context(patch.dict(sys.modules,modules));stack.enter_context(patch.object(ctypes,'WinDLL',return_value=kernel,create=True))
        stack.enter_context(patch.object(ctypes,'get_last_error',return_value=5,create=True));stack.enter_context(patch.object(ctypes,'WinError',side_effect=lambda e:OSError(e,'Windows mock'),create=True))
        stack.enter_context(patch.object(os,'get_handle_inheritable',return_value=False,create=True));stack.enter_context(patch.object(os,'set_handle_inheritable',create=True))
        stack.enter_context(patch.object(subprocess,'STARTUPINFO',side_effect=lambda:N(dwFlags=0),create=True));stack.enter_context(patch.object(subprocess,'STARTF_USESTDHANDLES',256,create=True))
        return stack,calls
    def test_suspended_venv_child_assigned_before_thread_resumes(self):
        from comment_deadline_windows_job_20261124 import WindowsJobChild
        stack,calls=self.fake_runtime()
        with stack,tempfile.TemporaryFile() as output:
            child=WindowsJobChild(['python','worker.py'],{},'.',output);child.close()
        names=[name for name,_ in calls]
        self.assertLess(names.index('CreateProcess'),names.index('AssignProcessToJobObject'))
        self.assertLess(names.index('AssignProcessToJobObject'),names.index('ResumeThread'))
        create=next(args for name,args in calls if name=='CreateProcess');self.assertTrue(create[5]&4)
        limits=next(args for name,args in calls if name=='SetInformationJobObject')[2]._obj
        self.assertEqual(limits.Basic.Flags,0x2000)
    def test_failed_job_assignment_never_executes_the_child(self):
        from comment_deadline_windows_job_20261124 import WindowsJobChild
        stack,calls=self.fake_runtime(assign=False)
        with stack,tempfile.TemporaryFile() as output:
            with self.assertRaises(OSError):WindowsJobChild(['python','worker.py'],{},'.',output)
        names=[name for name,_ in calls];self.assertNotIn('ResumeThread',names);self.assertIn('TerminateProcess',names)

class StarterTests(unittest.TestCase):
    def test_embedded_files_match_reviewed_source(self):
        import hashlib
        import start_resume_nov23_deadline_20261124 as starter
        for name,data in starter.ADDITIONS.items():self.assertEqual(data,Path(__file__).with_name(name).read_bytes())
        manifest={name:hashlib.sha256(data).hexdigest() for name,data in starter.ADDITIONS.items()}
        self.assertEqual(starter.FINGERPRINT,hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest())
    def test_verified_runtime_ack_is_bound_to_this_supervisor_run(self):
        import start_resume_nov23_deadline_20261124 as starter
        import start_publish_eligible60_real_20261123 as base
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();(root/'.venv/Scripts').mkdir(parents=True);(root/'.venv/Scripts/python.exe').write_bytes(b'python-marker')
            (root/'upload_config.json').write_text('{}');(root/'material-staging').mkdir()
            d.save(root/'material-staging/eligible60-20261123-pending-import.json',{'complete':True})
            original=root/'publish_eligible60_real_20261123.py';original.write_bytes(b'original-marker')
            status=root/'logs/eligible60-2026-11-23-deadline.json';d.save(status,dict(run_id='old',phase='running',pid=1,message='stale ack'))
            calls=[]
            class Process:
                def __init__(self,args,**kwargs):self.run=kwargs['env']['FB_DEADLINE_RUN'];self.calls=0;calls.append(self)
                def poll(self):
                    self.calls+=1;d.save(status,dict(run_id=self.run,phase='running',pid=123,message='new supervisor ack'));return None
            with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download_base',return_value=base),patch.object(base,'download',return_value={}),patch.object(starter.subprocess,'run') as checked,patch.object(starter.subprocess,'Popen',Process),patch.object(starter.time,'sleep'):
                self.assertEqual(starter.start(root),0)
            self.assertEqual(calls[0].calls,2);self.assertTrue(checked.called);self.assertEqual(original.read_bytes(),b'original-marker')
            self.assertFalse((root/'logs/publish_state.json').exists())
    def test_missing_original_distribution_never_starts_process(self):
        import start_resume_nov23_deadline_20261124 as starter
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'.venv/Scripts').mkdir(parents=True);(root/'.venv/Scripts/python.exe').touch();(root/'upload_config.json').write_text('{}')
            with patch.object(starter.sys,'platform','win32'),patch.object(starter.subprocess,'Popen') as popen:
                with self.assertRaises(FileNotFoundError):starter.start(root)
            popen.assert_not_called()

if __name__=='__main__':unittest.main()
