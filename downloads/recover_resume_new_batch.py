"""Recover proven abandoned PID locks, then resume only the authorized current batch."""
import argparse,contextlib,copy,ctypes,hashlib,json,os,re,sys,time,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path

BJ=timezone(timedelta(hours=8))
DATE='2026-10-31'


def require_date(date):
    if date!=DATE or datetime.now(timezone.utc).astimezone(BJ).date().isoformat()!=date:
        raise ValueError('此续跑命令仅用于北京时间 2026-10-31，未补跑其他日期')


def pid_alive(pid):
    if sys.platform!='win32':raise RuntimeError('进程存活核验只能在原 Windows 电脑执行')
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.OpenProcess(0x00100000,False,pid)  # SYNCHRONIZE: inspect, never terminate.
    if not handle:
        error=ctypes.get_last_error()
        if error in {87,1168}:return False
        raise RuntimeError('无法确认锁内进程是否退出，保留锁；PID '+str(pid)+'，Windows 错误 '+str(error))
    try:
        status=kernel.WaitForSingleObject(handle,0)
        if status==0x102:return True
        if status==0:return False
        raise RuntimeError('进程状态查询不确定，保留锁：PID '+str(pid))
    finally:kernel.CloseHandle(handle)


@contextlib.contextmanager
def recovery_mutex(root):
    if sys.platform!='win32':raise RuntimeError('恢复操作只能在原 Windows 电脑运行')
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE];kernel.ReleaseMutex.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    name='Local\\FBUploadRecover-'+hashlib.sha256(str(root.resolve()).casefold().encode()).hexdigest()[:24]
    handle=kernel.CreateMutexW(None,False,name)
    if not handle:raise RuntimeError('无法创建恢复互斥锁，未处理任何上传锁')
    owned=False
    try:
        result=kernel.WaitForSingleObject(handle,0)
        if result not in {0,0x80}:raise RuntimeError('另一个恢复程序正在运行，未处理上传锁')
        owned=True;yield
    finally:
        if owned:kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def recover_locks(root,probe=None,mutex=None):
    root=Path(root).resolve();probe=pid_alive if probe is None else probe
    guard=recovery_mutex(root) if mutex is None else mutex
    with guard:
        snapshots=[]
        for name in ['batch.lock','upload.lock']:
            path=root/'logs'/name
            if not path.exists():continue
            if path.is_symlink() or not path.is_file():raise ValueError('未知类型锁，保留不动：'+name)
            stat=path.stat();blob=path.read_bytes()
            if len(blob)>64 or not re.fullmatch(rb'[0-9]+[\r\n]*',blob):raise ValueError('锁内容不是可核验的 PID，保留不动：'+name)
            pid=int(blob)
            if not 0<pid<2**32:raise ValueError('锁内 PID 无效，保留不动：'+name)
            if probe(pid):raise RuntimeError('锁内进程仍在运行，未移走任何锁：'+name+' PID '+str(pid))
            snapshots.append((path,blob,(stat.st_ino,stat.st_size,stat.st_mtime_ns),pid))
        if not snapshots:
            print('没有遗留上传锁，可以继续安装及续跑。',flush=True);return None
        backup=root/'backups'/('stale-lock-recovery-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8])
        backup.mkdir(parents=True)
        audit=[]
        for path,blob,signature,pid in snapshots:
            stat=path.stat()
            if path.is_symlink() or path.read_bytes()!=blob or (stat.st_ino,stat.st_size,stat.st_mtime_ns)!=signature or probe(pid):
                raise RuntimeError('锁或进程状态发生变化，停止恢复：'+path.name)
            destination=backup/path.name
            path.rename(destination)  # Preserve the complete original lock; no process is killed.
            audit.append(dict(lock=path.name,pid=pid,action='archived_after_owner_exit'))
        (backup/'recovery-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
        print('已核实锁内进程退出；原锁已完整保存：',backup,flush=True)
        return backup


def choose_manifest(root,date):
    import fb_upload as upload
    import scheduled_material_batch as batch
    import daily_publish_and_comments as daily
    found=[]
    for path in (Path(root)/'logs').glob('frozen-material-'+date+'-*.json'):
        if not re.fullmatch(r'frozen-material-'+date+r'-[a-f0-9]{16}\.json',path.name):continue
        value=upload.read_json(path,{})
        if value.get('workflow')!='future-video-comments-v1':continue
        payload=value.get('payload',{});digest=batch.digest(payload)
        if (value.get('sha256')!=digest or not path.stem.endswith(digest[:16]) or payload.get('schema')!=batch.SCHEMA
                or payload.get('date')!=date or payload.get('ai_label') is not False or payload.get('include_fb10_pages') is not True
                or set(payload.get('excluded_accounts',[]))!={'fb16','fb18','fb21'} or payload.get('comment_text')!=daily.COMMENT):
            raise ValueError('本批原清单校验失败，未选其他清单代替：'+path.name)
        jobs=payload.get('jobs',[])
        if not jobs or len({j['key'] for j in jobs})!=len(jobs) or any(not batch.eligible(j,True) for j in jobs):raise ValueError('本批任务范围或原素材编号异常')
        found.append((path,value))
    if len(found)>1:raise ValueError('今天存在多份新批次清单，不能猜选；请保留日志核对：'+', '.join(p.name for p,v in found))
    return found[0] if found else (None,None)


def prepare_resume(root,path,value):
    """Caller holds uploader locks. Change only interrupted jobs in this exact manifest."""
    import fb_upload as upload
    import scheduled_material_batch as batch
    state_path=Path(root)/'logs/publish_state.json';state=upload.read_json(state_path,{})
    before=copy.deepcopy(state);jobs=[];changes=[]
    earliest=datetime.fromisoformat(value['created_at']).timestamp()-5
    for job in value['payload']['jobs']:
        old=state.get(job['key'])
        if old is None:jobs.append(copy.deepcopy(job));continue
        if old.get('status')=='failed_before_post' and old.get('resume_prepost_source_sha256')==value['sha256']:
            if not any(old.get(k) for k in ('today_first_retry_used','post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at')):
                jobs.append(copy.deepcopy(job))
            continue
        if old.get('status') not in {'preparing','posting'}:continue
        if ((old.get('account'),old.get('target'))!=(job['account'],job['target']) or upload.target_key(old.get('url',''))!=upload.target_key(job['url'])
                or str(old.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):raise ValueError('中断记录与原批次素材不一致，未修改状态')
        if datetime.fromisoformat(old['created']).timestamp()<earliest:raise ValueError('中断记录早于本次清单，未修改旧批次')
        intent=old.get('post_intent_at') or old.get('status')=='posting'
        proof=any(old.get(k) for k in ('permalink','success_message','confirmation_method','confirmed_at','published_at'))
        old['interrupted_resume_history']=old.get('interrupted_resume_history',[])+[dict(at=datetime.now(timezone.utc).isoformat(),previous_status=old['status'],post_intent_present=bool(intent))]
        if intent or proof:
            old.update(status='posting',error='程序中断时已有提交意图或成功线索；保留待核实，不关闭此账号浏览器、不重复发布，其他账号继续')
        else:
            old.update(status='failed_before_post',error='上次进程中断于 Post 意图写入之前；保留历史，允许一次原素材续跑')
            old['resume_prepost_source_sha256']=value['sha256']
            if not old.get('today_first_retry_used'):
                jobs.append(copy.deepcopy(job))
        changes.append(dict(key=job['key'],status=old['status']))
    if state!=before:
        backup=Path(root)/'backups'/('interrupted-current-batch-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8]);backup.mkdir(parents=True)
        upload.save_json(backup/'publish_state.json',before);upload.save_json(backup/'resume-audit.json',dict(source=path.name,source_sha256=value['sha256'],changes=changes))
        upload.save_json(state_path,state)
    if not jobs:return None
    payload=copy.deepcopy(value['payload']);payload.update(jobs=jobs,run_kind='resume-current-new-batch',source_manifest=path.name,source_sha256=value['sha256'])
    digest=batch.digest(payload);resume_path=Path(root)/'logs'/('resume-current-'+payload['date']+'-'+digest[:16]+'.json')
    manifest=dict(payload=payload,sha256=digest,created_at=datetime.now(timezone.utc).isoformat(),issues=[],workflow='resume-current-new-batch-v1')
    upload.save_json(resume_path,manifest)
    return resume_path


def resume(root,date,output_dir=None):
    require_date(date);sys.path.insert(0,str(Path(root).resolve()))
    import fb_upload as upload
    import scheduled_material_batch as batch
    import daily_publish_and_comments as daily
    import publish_new_with_comments as fresh
    import safe_video_comments as comments
    from add_fb_accounts import locked
    if upload.ROOT.resolve()!=Path(root).resolve() or upload.VERSION!='2.44' or comments.COMMENT_WORKFLOW_VERSION!='1.3-facebook-attribution':raise ValueError('需先安装配套上传核心 2.44 和评论模块 1.3')
    with locked():
        path,value=choose_manifest(root,date)
        retry_path=prepare_resume(root,path,value) if path is not None else None
    if path is None:
        print('上次尚未生成本批清单；按已确认的实拍设置启动本批新视频。',flush=True)
        return fresh.execute(date,True,output_dir)
    print('沿用本批清单续跑：',path.name,'；成功/已提交待核实不重发，排除 fb16/fb18/fb21。',flush=True)
    with daily.keep_awake():
        if retry_path is not None:
            start=datetime.fromisoformat(value['payload']['start'])
            while datetime.now(timezone.utc)<start:time.sleep(1)
            batch.run(retry_path,output_dir,defer_comments=True,retry_before_post=True)
        daily.backfill(value,output_dir,future_only=True)
        previous=upload.read_json(path.with_name(path.stem+'-results.json'),{}).get('attempts',[])
        if retry_path is not None:previous+=upload.read_json(retry_path.with_name(retry_path.stem+'-results.json'),{}).get('attempts',[])
        rows=batch.results(path,value,previous,output_dir,final=True)
    return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser(description='核验进程后备份遗留锁，按本批原清单续跑，防止重复发布')
    parser.add_argument('root',type=Path);parser.add_argument('phase',choices=['recover-locks','resume']);parser.add_argument('--date',required=True);parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    try:
        require_date(args.date)
        if args.phase=='recover-locks':recover_locks(args.root);raise SystemExit(0)
        raise SystemExit(resume(args.root,args.date,args.output_dir))
    except KeyboardInterrupt:print('已停止，保留状态，请勿直接重复提交。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
