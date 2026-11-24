"""Resume original Nov23 work, with an external 180-second comment watchdog."""
import contextlib,hashlib,json,os,re,subprocess,sys,tempfile,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

VERSION='1.1-shared-log-takeover'
LIMIT=180
DRIVER='resume_nov23_comment_deadline_20261124.py'
STATUS='logs/eligible60-2026-11-23-deadline.json'
DAY='2026-11-23'
BEGIN=re.compile(r'^(?:待核实视频进入原评论定位：|给本批已成功视频评论：)\s*(fb\d+)\s+(personal|page\d+)\b',re.M)

def read(path,default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:return default

def save(path,value):
    path=Path(path)
    if path.is_symlink():raise ValueError('诊断路径是链接，未覆盖。')
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:
        temp=Path(handle.name);handle.write(json.dumps(value,ensure_ascii=False).encode('utf-8'))
    try:
        for attempt in range(20):
            try:temp.replace(path);break
            except PermissionError:
                if attempt==19:raise
                time.sleep(.02)
    finally:temp.unlink(missing_ok=True)

def fresh_progress(run,request):
    return dict(schema='nov23-comment-deadline-v1',run_id=run,request_sha256=request,limit_seconds=LIMIT,completed=[],skipped={})

def checked_progress(path,run,request):
    value=read(path)
    if (not isinstance(value,dict) or value.get('schema')!='nov23-comment-deadline-v1' or value.get('run_id')!=run or value.get('request_sha256')!=request
            or value.get('limit_seconds')!=LIMIT or not isinstance(value.get('completed'),list) or not isinstance(value.get('skipped'),dict)):
        raise ValueError('三分钟续跑进度不符，保留原记录。')
    return value

def expired(operation,run,attempt,now):
    return (isinstance(operation,dict) and operation.get('run_id')==run and operation.get('attempt')==attempt
            and operation.get('state')=='started' and operation.get('phase') in {'comments','comment_retry'}
            and type(operation.get('started')) in {int,float} and 0<=operation['started']<=now-LIMIT)

def merge_completed(progress,operation,run,attempt):
    if isinstance(operation,dict) and operation.get('run_id')==run and operation.get('attempt')==attempt:
        progress['completed']=sorted(set(progress['completed'])|set(operation.get('completed',[])))

@contextlib.contextmanager
def bounded_phases(app,root,run,attempt,progress_path,operation_path):
    """The supervisor owns the deadline; no Playwright callback must return."""
    native=app.run_phase
    completed=set()
    def phase(phase,req,source,journal,material,wave,controller,deferred):
        if phase not in {'comments','comment_retry'}:return native(phase,req,source,journal,material,wave,controller,deferred)
        value=app.first.archive.checked_json(Path(root)/'logs'/wave['manifest'])
        if value['sha256']!=wave['sha256'] or value['payload'].get('queue_id')!=req['sha256']:raise ValueError('原评论批次指纹不符。')
        progress=checked_progress(progress_path,run,req['sha256']);completed.update(progress['completed'])
        for job in value['payload']['jobs']:
            key=job['key'];token=phase+':'+key
            if job['account'] in app.PAUSED or job['account'] in controller.get('manual_skipped',[]):continue
            if key in progress['skipped'] or token in completed:continue
            row=app.first.upload.read_json(Path(root)/'logs/publish_state.json',{}).get(key,{})
            if row.get('comment_status') in {'sent','already_present'}:continue
            if row.get('status') not in {'published','needs_review'}:continue
            operation=dict(run_id=run,attempt=attempt,state='started',phase=phase,key=key,account=job['account'],target=job['target'],
                           manifest=wave['manifest'],manifest_sha256=value['sha256'],started=time.monotonic(),completed=sorted(completed))
            save(operation_path,operation)
            print('三分钟计时开始：',job['account'],job['target'],'；评论定位、发送、核验及关闭均计入180秒。',flush=True)
            backfill=app.first.priority.daily.backfill;candidates=app.first.priority.comment_retry.candidates
            def one_backfill(manifest,*args,**kwargs):
                requested=kwargs.get('only_keys');kwargs['only_keys']={key} if requested is None else set(requested)&{key}
                if not kwargs['only_keys']:return kwargs.get('rows',[])
                return backfill(manifest,*args,**kwargs)
            def one_candidates(*args,**kwargs):
                selected,decisions=candidates(*args,**kwargs)
                # Reserve retry claims only for this target, never for later targets
                # that would otherwise lose their attempt if this worker is killed.
                return [item for item in selected if item[0]['key']==key],decisions
            with patch.object(app.first.priority.daily,'backfill',side_effect=one_backfill),patch.object(app.first.priority.comment_retry,'candidates',side_effect=one_candidates):
                native(phase,req,source,journal,material,wave,controller,deferred)
            completed.add(token);operation.update(state='finished',completed=sorted(completed));save(operation_path,operation)
    with patch.object(app,'run_phase',side_effect=phase):yield

def stuck_pair(log):
    matches=list(BEGIN.finditer(log))
    if not matches:return None
    last=matches[-1]
    tail=log[last.end():]
    if re.search(r'^(?:本次视频评论待定位，先继续其他目标：|本批视频评论：|已定位本次视频，继续原评论：)',tail,re.M):return None
    return last.group(1),last.group(2)

def stop_stalled_original(root,jobs):
    root=Path(root);queue=root/'logs/eligible60-2026-11-23-queue.json';status=read(queue,{})
    if status.get('phase')!='running':return None
    if (status.get('material_date')!=DAY or status.get('runner')!='direct_background' or not re.fullmatch('[a-f0-9]{32}',str(status.get('launch_id','')))
            or type(status.get('pid')) is not int):raise ValueError('当前运行回执不符，未停止任何进程。')
    log=root/'logs/eligible60-2026-11-23-run.log'
    if time.time()-log.stat().st_mtime<LIMIT:raise ValueError('原任务最近三分钟仍有日志变化；未终止仍在推进的任务。')
    raw=log.read_bytes();pair=stuck_pair(raw[-131072:].decode('utf-8',errors='replace'))
    selected=[job for job in jobs if (job['account'],job['target'])==pair]
    if len(selected)!=1:raise ValueError('无法唯一确认卡住的原评论目标，未停止任务。')
    payload=dict(root=str(root),pid=status['pid'],launch_id=status['launch_id'],queue_sha=hashlib.sha256(queue.read_bytes()).hexdigest(),log_sha=hashlib.sha256(raw).hexdigest())
    packet=root/'logs'/('stop-stale-comment-'+uuid.uuid4().hex+'.json');save(packet,payload)
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('stop_stale_nov23_comment_worker_20261124.ps1')),'-InputFile',str(packet)],
                          capture_output=True,stdin=subprocess.DEVNULL,creationflags=0x08000000,timeout=60)
    output=(result.stdout+result.stderr).decode('utf-8-sig',errors='replace').strip()
    if output:print(output,flush=True)
    if result.returncode:raise ValueError('旧进程未通过安全释放检查，未启动第二个发布任务。')
    return selected[0]

@contextlib.contextmanager
def supervisor_mutex(root):
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);pointer=ctypes.c_void_p;u32=ctypes.c_uint32
    kernel.CreateMutexW.argtypes=[pointer,ctypes.c_int,ctypes.c_wchar_p];kernel.CreateMutexW.restype=pointer
    kernel.WaitForSingleObject.argtypes=[pointer,u32];kernel.WaitForSingleObject.restype=u32
    kernel.ReleaseMutex.argtypes=[pointer];kernel.CloseHandle.argtypes=[pointer]
    handle=kernel.CreateMutexW(None,False,'Local\\FBUpload-Nov23CommentDeadline-'+hashlib.sha256(str(root).casefold().encode()).hexdigest()[:24]);owned=False
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        result=kernel.WaitForSingleObject(handle,0)
        if result not in {0,0x80}:raise RuntimeError('已有三分钟自动续跑在运行，未启动第二份。')
        owned=True;yield
    finally:
        if owned:kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)

def inspect_workers(day,root):
    pattern=day.BOOTSTRAP.pattern.replace('start_publish_eligible60_real_20261123','start_resume_nov23_deadline_20261124').replace('verified-real-eligible60-nov23-publication','verified-nov23-comment-deadline')
    with patch.object(day.app.workers,'BOOTSTRAP',re.compile(pattern)):
        return day.app.workers.active_workers(root,Path(__file__).resolve())

def run_worker(day,root,run):
    attempt=os.environ['FB_PUBLISH_LAUNCH_ID'];progress=root/'logs'/('nov23-comment-deadline-'+run+'.json')
    operation=root/'logs'/('nov23-comment-operation-'+attempt+'.json')
    day._BACKGROUND_GUARD=day.isolate_background_interrupts()
    with bounded_phases(day.app,root,run,attempt,progress,operation),patch.object(day,'inspect_workers',side_effect=lambda path:inspect_workers(day,path)):
        return day.main(root)

def supervise(day,root,run,child_factory=None):
    from comment_deadline_windows_job_20261124 import WindowsJobChild
    child_factory=WindowsJobChild if child_factory is None else child_factory
    status_path=root/STATUS;log=root/day.LOG
    def status(phase,message,**more):
        save(status_path,dict(phase=phase,message=message,run_id=run,pid=os.getpid(),material_date=DAY,limit_seconds=LIMIT,updated_at=datetime.now(timezone.utc).isoformat(),**more))
    def emit(message):
        with log.open('a',encoding='utf-8') as handle:handle.write(message+'\n');handle.flush()
        print(message,flush=True)
    with supervisor_mutex(root):
        status('preparing','正在核验23号原清单与卡住的评论任务。')
        try:
            with day.authorized_context():
                _,source,journal,material=day.allocation(root)
                if not (root/day.REQUEST).is_file():raise ValueError('原23号发布授权缺失，未新建其他批次。')
                req=day.app.request(root,source,journal,material)
                control_path=root/'logs'/('eligible60-real-publication-'+req['sha256'][:16]+'.json')
                controller=read(control_path,{})
                if controller.get('request_sha256')!=req['sha256'] or not isinstance(controller.get('waves'),list):raise ValueError('原60目标进度缺失或不符。')
                jobs=[]
                for wave in controller['waves']:
                    if Path(wave['manifest']).name!=wave['manifest']:raise ValueError('原清单路径异常。')
                    value=day.first.archive.checked_json(root/'logs'/wave['manifest'])
                    if value['sha256']!=wave['sha256'] or value['payload'].get('queue_id')!=req['sha256']:raise ValueError('原批次指纹不符。')
                    jobs.extend(value['payload']['jobs'])
                if len({job['key'] for job in jobs})!=len(jobs):raise ValueError('原任务重复，未猜选。')
            progress=fresh_progress(run,req['sha256']);progress_path=root/'logs'/('nov23-comment-deadline-'+run+'.json')
            # The old pending-lookup loop had already attempted these unresolved
            # targets. Preserve that work so takeover proceeds past the stall.
            previous_log=log.read_text(encoding='utf-8-sig',errors='replace') if log.is_file() else ''
            previous_log=previous_log.rsplit('Nov23 run started:',1)[-1]
            attempted=set(re.findall(r'^本次视频评论待定位，先继续其他目标：\s*(fb\d+)\s+(personal|page\d+)\b',previous_log,re.M))
            state=day.first.upload.read_json(root/'logs/publish_state.json',{})
            progress['completed']=['comments:'+job['key'] for job in jobs if (job['account'],job['target']) in attempted and state.get(job['key'],{}).get('status')=='needs_review']
            stuck=stop_stalled_original(root,jobs)
            if stuck:
                progress['skipped'][stuck['key']]=dict(account=stuck['account'],target=stuck['target'],reason='接管前原评论进程已停滞超过180秒；本轮跳过，原视频及评论提交记录保留。')
                emit('已跳过原卡住目标：'+stuck['account']+'/'+stuck['target']+'；继续下一个评论目标，不重新上传此视频。')
            # Only proven abandoned PID locks are archived by the original recovery.
            for _ in range(30):
                live=inspect_workers(day,root)
                if not live:break
                time.sleep(.1)
            if live:raise ValueError('另有项目任务在运行，未开始第二份：'+','.join(str(r['pid']) for r in live))
            save(progress_path,progress)
            keys={job['key'] for job in jobs};attempts=0
            while True:
                attempts+=1
                if attempts>len(keys)+1:raise RuntimeError('已达到本轮最大续跑次数，原记录保留。')
                attempt=uuid.uuid4().hex;operation_path=root/'logs'/('nov23-comment-operation-'+attempt+'.json')
                output_path=root/'logs'/('nov23-comment-worker-'+attempt+'.log')
                environment=dict(os.environ,FB_DEADLINE_ROLE='worker',FB_PUBLISH_LAUNCH_ID=attempt,FB_PUBLISH_ISOLATED_BACKGROUND='1',FB_PUBLISH_FILE_LOG_ONLY='1',PYTHONIOENCODING='utf-8')
                timed_out=None;last_notice=time.monotonic()
                with output_path.open('ab') as output:
                    child=child_factory([str(root/'.venv/Scripts/python.exe'),'-u',str(Path(__file__).resolve()),str(root)],environment,root,output)
                    try:
                        status('running','三分钟评论保护已启用；原23号批次后台续跑。',worker_pid=child.pid,progress=str(progress_path))
                        while True:
                            operation=read(operation_path,{})
                            merge_completed(progress,operation,run,attempt)
                            now=time.monotonic();code=child.poll()
                            if code is not None:break
                            if expired(operation,run,attempt,now):
                                if operation.get('key') not in keys:raise RuntimeError('计时目标不属于原清单，已停止本轮。')
                                timed_out=operation;child.stop();break
                            if now-last_notice>=15:
                                active=operation.get('state')=='started' and operation.get('attempt')==attempt
                                name=(operation.get('account','')+'/'+operation.get('target','')) if active else '原视频发布/安全补发阶段'
                                elapsed=max(0,int(now-operation['started'])) if active else 0
                                emit('独立超时监控：'+name+('；本目标已用'+str(elapsed)+'/180秒。' if active else '；评论阶段每目标最多180秒。'))
                                status('running','后台运行；单目标评论硬超时180秒。',worker_pid=child.pid,active=operation if active else None,progress=str(progress_path))
                                last_notice=now
                            time.sleep(.25)
                    finally:child.close()
                if timed_out:
                    key=timed_out['key']
                    progress['skipped'][key]=dict(account=timed_out['account'],target=timed_out['target'],phase=timed_out['phase'],reason='评论目标处理超过180秒；本轮跳过，原视频及评论提交记录保留。')
                    save(progress_path,progress)
                    emit('评论处理已超过3分钟，自动切换下一个：'+timed_out['account']+'/'+timed_out['target']+'；已释放本轮子进程，原提交记录保留，不重复发送待核实评论。')
                    continue
                save(progress_path,progress)
                if code not in {0,3}:raise RuntimeError('后台工作进程退出码'+str(code)+'；未自动循环重启。诊断：'+str(output_path))
                status('finished' if code==0 else 'review_required','本轮处理已结束；超时目标保留待处理，实际成功数查看发布报告。',progress=str(progress_path),skipped=progress['skipped'])
                return code
        except Exception as error:
            status('failed',str(error) or type(error).__name__);raise

def main(root):
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
    run=os.environ.get('FB_DEADLINE_RUN','')
    if not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('独立计时任务标识缺失。')
    root=Path(root).resolve();sys.path.insert(0,str(root));sys.path.insert(0,str(Path(__file__).resolve().parent))
    import publish_eligible60_real_20261123 as day
    if root!=day.first.upload.ROOT.resolve():raise ValueError('不是原上传目录。')
    if os.environ.get('FB_DEADLINE_ROLE')=='worker':return run_worker(day,root,run)
    if os.environ.get('FB_DEADLINE_ROLE')!='supervisor':raise ValueError('请使用校验过的启动入口。')
    day.isolate_background_interrupts()
    return supervise(day,root,run)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(main(Path(sys.argv[1])))
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
