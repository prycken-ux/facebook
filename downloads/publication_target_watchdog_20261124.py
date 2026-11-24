"""Independent Nov24 watchdog: bounded video and exact-comment target operations."""
import contextlib,copy,hashlib,json,os,re,subprocess,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
# A direct script launch sets sys.path[0] to the immutable tools cache. Add
# the actual project before ANY project import, matching the package probe.
if __name__=='__main__':
    _root=Path(sys.argv[1]).resolve()
    sys.path.insert(0,str(_root));sys.path.insert(0,str(Path(__file__).resolve().parent))
try:
    import publication_file_state_20261124 as files
    import chrome_profile_guard as profiles
    from comment_deadline_windows_job_20261124 import WindowsJobChild
except Exception:
    if __name__=='__main__':
        import traceback
        _run=os.environ.get('FB_NOV24_RUN','')
        if re.fullmatch('[a-f0-9]{32}',_run):
            with (_root/'logs'/('nov24-launch-'+_run+'.log')).open('a',encoding='utf-8') as _out:traceback.print_exc(file=_out)
    raise

DAY='2026-11-24'
VIDEO_SECONDS=600
COMMENT_SECONDS=180
STATUS='logs/eligible60-2026-11-24-status.json'
LOG='logs/eligible60-2026-11-24-run.log'
ENTRY='publication_target_watchdog_20261124.py'
MAX_BYTES=4_000_000

def read(path,default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:return default

def inspect_workers(day,root):
    pattern=re.compile(day.BOOTSTRAP.pattern.replace('start_publish_eligible60_real_20261124','start_publish_guarded_nov24_20261124').replace('verified-real-eligible60-nov24-publication','verified-nov24-guarded-publication'))
    with patch.object(day.app.workers,'BOOTSTRAP',pattern):return day.app.workers.active_workers(root,Path(__file__).resolve())

@contextlib.contextmanager
def mutex(root):
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);ptr=ctypes.c_void_p;u32=ctypes.c_uint32
    kernel.CreateMutexW.argtypes=[ptr,ctypes.c_int,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ptr
    kernel.WaitForSingleObject.argtypes=[ptr,u32];kernel.WaitForSingleObject.restype=u32
    kernel.ReleaseMutex.argtypes=[ptr];kernel.CloseHandle.argtypes=[ptr]
    handle=kernel.CreateMutexW(None,False,'Local\\FBUpload-Nov24-Supervisor-'+hashlib.sha256(str(root).casefold().encode()).hexdigest()[:24]);owned=False
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        code=kernel.WaitForSingleObject(handle,0)
        if code not in {0,0x80}:raise RuntimeError('已有24号发布监控，未再启动第二份。')
        owned=True;yield
    finally:
        if owned:kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)

def progress_new(run,request):
    return dict(schema='nov24-bounded-publication-v1',run_id=run,request_sha256=request,completed=[],skipped_video={},skipped_comments={})

def progress_read(path,run,request):
    p=read(path,{})
    if p.get('schema')!='nov24-bounded-publication-v1' or p.get('run_id')!=run or p.get('request_sha256')!=request:raise ValueError('24号监控进度与原素材授权不符。')
    return p

def operation_valid(day,root,operation,run,attempt,request):
    if not isinstance(operation,dict) or operation.get('run_id')!=run or operation.get('attempt')!=attempt:return False
    if operation.get('kind') not in {'video','comment'}:return False
    name=operation.get('manifest','')
    if not re.fullmatch(r'frozen-material-\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json',name):return False
    value=day.first.archive.checked_json(root/'logs'/name);p=value['payload']
    return (value['sha256']==operation.get('manifest_sha256') and p.get('queue_id')==request and p.get('material_source_date')==DAY
            and any(j['key']==operation.get('key') and (j['account'],j['target'])==(operation.get('account'),operation.get('target')) for j in p['jobs']))

def deadline_reached(operation,now):
    budget=VIDEO_SECONDS if operation.get('kind')=='video' else COMMENT_SECONDS
    start=operation.get('started')
    return operation.get('state')=='started' and type(start) in {int,float} and 0<=start<=now-budget

def release_idle(day,root,account):
    worker=day.app.workers
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',worker.WORKERS],input=b'{}',capture_output=True,timeout=20,creationflags=0x08000000)
    if result.returncode:raise RuntimeError('无法核对任务归属，保留占用浏览器。')
    rows=json.loads(result.stdout.decode('utf-8-sig'))
    pattern=re.compile(day.BOOTSTRAP.pattern.replace('start_publish_eligible60_real_20261124','start_publish_guarded_nov24_20261124').replace('verified-real-eligible60-nov24-publication','verified-nov24-guarded-publication'))
    with patch.object(worker,'BOOTSTRAP',pattern):live,allowed=worker.classify_workers(rows,root,os.getpid(),Path(__file__).resolve())
    if live:raise RuntimeError('其他项目任务仍在运行，未关闭浏览器。')
    identities=[dict(pid=r['pid'],created=r['created'],command_sha=hashlib.sha256(r['command'].encode()).hexdigest()) for r in rows if r['pid'] in allowed]
    packet=root/'logs'/('nov24-idle-profile-'+uuid.uuid4().hex+'.json');files.save(packet,dict(root=str(root),account=account,starter_pid=os.getpid(),allowed=identities))
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('release_idle_publication_profile_20261124.ps1')),'-InputFile',str(packet)],stdin=subprocess.DEVNULL,capture_output=True,timeout=40,creationflags=0x08000000)
    output=(result.stdout+result.stderr).decode('utf-8-sig',errors='replace').strip()
    if output:print(output,flush=True)
    if result.returncode:raise RuntimeError('原浏览器仍由其他任务或正常窗口占用，先跳过本目标。')

@contextlib.contextmanager
def guarded_worker(day,root,run,attempt,progress_path,operation_path):
    app=day.app;first=day.first;native_phase=app.run_phase;native_upload=first.upload.run_entry;native_decide=app.queued.retry.decide
    native_queue_decide=getattr(app.queued,'decide_queue',None)
    native_normal=first.normal.launch_normal
    native_validate=first.batch.validate_job
    current={};completed=set()
    def begin(kind,phase,job,wave,sha):
        operation=dict(run_id=run,attempt=attempt,state='started',kind=kind,phase=phase,key=job['key'],account=job['account'],target=job['target'],
                       manifest=wave['manifest'],manifest_sha256=sha,started=time.monotonic(),completed=sorted(completed))
        files.save(operation_path,operation);print('独立计时开始：',job['account'],job['target'],kind,'；上限',VIDEO_SECONDS if kind=='video' else COMMENT_SECONDS,'秒。',flush=True)
        return operation
    def finish(operation):
        operation.update(state='finished',completed=sorted(completed));files.save(operation_path,operation)
    def validate(job,*args,**kwargs):
        if current.get('phase') in {'videos','retry','extra'} and job.get('key') in progress_read(progress_path,run,current['request'])['skipped_video']:
            raise RuntimeError('本条已达到视频处理上限，本轮跳过，不重新选择或上传。')
        entry=native_validate(job,*args,**kwargs)
        if job.get('key') in current.get('jobs',{}):current['selected']=job
        return entry
    def close(account):
        job=current.get('selected');own_op=False
        if job and job['account']==account and current.get('phase') in {'videos','retry','extra'} and not current.get('active_op'):
            current['active_op']=begin('video',current['phase'],job,current['wave'],current['sha']);own_op=True
        try:
            if account not in {j['account'] for j in current.get('jobs',{}).values()}:raise ValueError('关闭检查不属于当前24号目标。')
            # Never request CloseMainWindow on a manual browser. Only the idle
            # headless-owner helper may release a preexisting profile owner.
            try:return profiles.require_profile_free(root/'profiles'/account,account)
            except RuntimeError as error:
                if 'Chrome 资料仍被占用' not in str(error):raise
                release_idle(day,root,account);return profiles.require_profile_free(root/'profiles'/account,account)
        except BaseException:
            if own_op:finish(current.pop('active_op'))
            raise
    def upload(entry,*args,**kwargs):
        key=kwargs.get('expected_job_key');job=current.get('jobs',{}).get(key)
        if not job or (job['account'],job['target'])!=(entry.get('account'),entry.get('target')) or kwargs.get('filename')!=job['filename']:raise ValueError('发布目标不属于当前24号原冻结清单。')
        p=progress_read(progress_path,run,current['request'])
        if key in p['skipped_video']:raise RuntimeError('本条视频已超时或中断，本轮保留原记录并跳过。')
        op=current.get('active_op')
        if not op or op['key']!=key:op=begin('video',current['phase'],job,current['wave'],current['sha'])
        current['active_op']=op
        try:return native_upload(entry,*args,**kwargs)
        finally:finish(op);current.pop('active_op',None)
    def decide(job,*args,**kwargs):
        p=progress_read(progress_path,run,current['request'])
        if job['key'] in p['skipped_video']:return False,'本条已超时，本轮不再分配补发机会；原提交记录保留'
        return native_decide(job,*args,**kwargs)
    def queue_decide(job,*args,**kwargs):
        p=progress_read(progress_path,run,current['request'])
        if job['key'] in p['skipped_video']:return False,'本条已超时，本轮保留原状态，不再次补发'
        return native_queue_decide(job,*args,**kwargs)
    def normal(pw,entry):
        if (entry.get('account'),entry.get('target')) not in {(j['account'],j['target']) for j in current.get('jobs',{}).values()}:raise ValueError('浏览器不属于当前发布清单。')
        try:return native_normal(pw,entry)
        except RuntimeError as error:
            if 'Chrome 资料仍被占用' not in str(error):raise
            release_idle(day,root,entry['account']);return native_normal(pw,entry)
    def phase(phase,req,source,journal,material,wave,controller,deferred):
        path=root/'logs'/wave['manifest'];value=first.archive.checked_json(path)
        if value['sha256']!=wave['sha256'] or value['payload'].get('queue_id')!=req['sha256'] or value['payload'].get('material_source_date')!=DAY:raise ValueError('不是本次24号原冻结任务。')
        current.update(request=req['sha256'],phase=phase,wave=wave,sha=value['sha256'],jobs={j['key']:j for j in value['payload']['jobs']})
        if phase not in {'comments','comment_retry'}:
            try:return native_phase(phase,req,source,journal,material,wave,controller,deferred)
            finally:
                if current.get('active_op'):finish(current.pop('active_op'))
        p=progress_read(progress_path,run,req['sha256']);completed.update(p['completed'])
        for job in value['payload']['jobs']:
            key=job['key'];token=phase+':'+key
            if job['account'] in app.PAUSED or key in p['skipped_comments'] or token in completed:continue
            row=first.upload.read_json(root/'logs/publish_state.json',{}).get(key,{})
            if row.get('comment_status') in {'sent','already_present'} or row.get('status') not in {'published','needs_review'}:continue
            op=begin('comment',phase,job,wave,value['sha256']);backfill=first.priority.daily.backfill;candidates=first.priority.comment_retry.candidates
            def one_backfill(manifest,*args,**kwargs):
                requested=kwargs.get('only_keys');kwargs['only_keys']={key} if requested is None else set(requested)&{key}
                return backfill(manifest,*args,**kwargs) if kwargs['only_keys'] else kwargs.get('rows',[])
            def one_candidates(*args,**kwargs):
                chosen,decisions=candidates(*args,**kwargs);return [c for c in chosen if c[0]['key']==key],decisions
            with patch.object(first.priority.daily,'backfill',side_effect=one_backfill),patch.object(first.priority.comment_retry,'candidates',side_effect=one_candidates):native_phase(phase,req,source,journal,material,wave,controller,deferred)
            completed.add(token);finish(op)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(app,'run_phase',side_effect=phase));stack.enter_context(patch.object(first.upload,'run_entry',side_effect=upload))
        stack.enter_context(patch.object(app.queued.retry,'decide',side_effect=decide));stack.enter_context(patch.object(first.normal,'launch_normal',side_effect=normal))
        if native_queue_decide is not None:stack.enter_context(patch.object(app.queued,'decide_queue',side_effect=queue_decide))
        stack.enter_context(patch.object(first.batch,'validate_job',side_effect=validate))
        for module in (first,first.batch,first.priority.daily,first.normal):
            if hasattr(module,'close_selected_window'):stack.enter_context(patch.object(module,'close_selected_window',side_effect=close))
        yield

def supervisor(day,root,run,child_factory=WindowsJobChild):
    status_path=root/STATUS;log_path=root/LOG
    def status(phase,message,**more):files.save(status_path,dict(phase=phase,message=message,run_id=run,pid=os.getpid(),material_date=DAY,comments_enabled=True,video_seconds=VIDEO_SECONDS,comment_seconds=COMMENT_SECONDS,updated_at=datetime.now(timezone.utc).isoformat(),**more))
    def emit(message):
        with log_path.open('a',encoding='utf-8') as handle:handle.write(message+'\n')
    with mutex(root):
        try:
            status('preparing','24号监控已建立，正在核对原素材及其他任务。')
            with patch.object(day,'inspect_workers',side_effect=lambda p:inspect_workers(day,p)),day.authorized_context():
                if inspect_workers(day,root):raise ValueError('仍有其他发布/分配任务，未停止原任务或并发发布。')
                _,source,journal,material=day.allocation(root)
                day.app.browser.staged.lock_recovery.recover_locks(root)
                with day.first.locked():req=day.app.request(root,source,journal,material)
            progress=progress_new(run,req['sha256']);progress_path=root/'logs'/('nov24-progress-'+run+'.json');files.save(progress_path,progress)
            for iteration in range(121):
                attempt=uuid.uuid4().hex;operation_path=root/'logs'/('nov24-operation-'+attempt+'.json');output_path=root/'logs'/('nov24-worker-'+attempt+'.log')
                env=dict(os.environ,FB_NOV24_ROLE='worker',FB_NOV24_RUN=run,FB_NOV24_BOOT_ATTEMPT=attempt,FB_PUBLISH_LAUNCH_ID=attempt,FB_PUBLISH_ISOLATED_BACKGROUND='1',FB_PUBLISH_FILE_LOG_ONLY='1',PYTHONIOENCODING='utf-8')
                failure=None;last_notice=time.monotonic()
                with output_path.open('ab') as output:
                    child=child_factory([str(root/'.venv/Scripts/python.exe'),'-u',str(Path(__file__).resolve()),str(root)],env,root,output)
                    try:
                        status('running','24号发布、评论及安全补发已启动；卡住目标会限时跳过。',worker_pid=child.pid,progress=str(progress_path))
                        while True:
                            operation=read(operation_path,{})
                            if operation.get('run_id')==run and operation.get('attempt')==attempt:progress['completed']=sorted(set(progress['completed'])|set(operation.get('completed',[])))
                            code=child.poll();now=time.monotonic()
                            active=operation.get('state')=='started'
                            if code is not None:
                                if code not in {0,3} and active and operation_valid(day,root,operation,run,attempt,req['sha256']):failure=dict(operation,reason='工作进程中断，保留原记录并继续其他目标')
                                break
                            if active and deadline_reached(operation,now):
                                if not operation_valid(day,root,operation,run,attempt,req['sha256']):raise ValueError('超时目标不属于24号原素材，已停止本轮。')
                                failure=dict(operation,reason='本目标处理已达到独立时间上限');child.stop();break
                            if now-last_notice>=15:
                                message='24号后台运行'
                                if active:message+='：'+operation.get('account','')+'/'+operation.get('target','')+' '+operation.get('kind','')+' 已用'+str(max(0,int(now-operation['started'])))+'秒'
                                emit(message);status('running',message,worker_pid=child.pid,active=operation if active else None,progress=str(progress_path));last_notice=now
                            time.sleep(.25)
                    finally:child.close()
                if failure:
                    slot='skipped_video' if failure['kind']=='video' else 'skipped_comments';key=failure['key']
                    if key in progress[slot]:raise RuntimeError('同一目标重复进入已跳过阶段，停止而不循环补发。')
                    progress[slot][key]=failure;files.save(progress_path,progress)
                    emit('独立监控已切换下一个：'+failure['account']+'/'+failure['target']+'；'+failure['reason']+'；原视频/评论提交记录保留。');continue
                files.save(progress_path,progress)
                if code not in {0,3}:raise RuntimeError('后台进程启动或批次校验失败，未循环重启。诊断：'+str(output_path))
                status('finished' if code==0 else 'review_required','24号本轮处理结束；实际视频、评论成功数见发布报告。',progress=str(progress_path));return code
            raise RuntimeError('达到本轮最大续跑次数，原进度保留。')
        except Exception as error:status('failed',str(error) or type(error).__name__);raise

def main(root):
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
    root=Path(root).resolve();run=os.environ.get('FB_NOV24_RUN','')
    if not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('24号任务标识缺失。')
    sys.path.insert(0,str(root));sys.path.insert(0,str(Path(__file__).resolve().parent))
    import publish_eligible60_real_20261124 as day
    day._BACKGROUND_GUARD=day.isolate_background_interrupts()
    if os.environ.get('FB_NOV24_ROLE')=='worker':
        attempt=os.environ['FB_PUBLISH_LAUNCH_ID']
        with guarded_worker(day,root,run,attempt,root/'logs'/('nov24-progress-'+run+'.json'),root/'logs'/('nov24-operation-'+attempt+'.json')),patch.object(day,'inspect_workers',side_effect=lambda p:inspect_workers(day,p)):return day.main(root)
    if os.environ.get('FB_NOV24_ROLE')!='supervisor':raise ValueError('请使用校验过的启动入口。')
    return supervisor(day,root,run)

if __name__=='__main__':
    # Use a normal file before imports/preflight; no pipe EOF and no console
    # handle is required by the PowerShell handoff.
    root=Path(sys.argv[1]);run=os.environ.get('FB_NOV24_RUN','')
    if not re.fullmatch('[a-f0-9]{32}',run):raise SystemExit('Invalid launch identifier')
    attempt=os.environ.get('FB_NOV24_BOOT_ATTEMPT','')
    name='nov24-worker-'+attempt+'.log' if re.fullmatch('[a-f0-9]{32}',attempt) else 'nov24-launch-'+run+'.log'
    with (root/'logs'/name).open('a',encoding='utf-8') as output,contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
        try:raise SystemExit(main(root))
        except Exception:
            import traceback
            traceback.print_exc();raise SystemExit(1)
