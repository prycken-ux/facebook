"""Allocate58 exact registered targets; skip36 unavailable accounts and retain all source originals."""
import contextlib,copy,importlib.util,json,os,shutil,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    sys.path.insert(0,str(Path(__file__).resolve().parent))


def sibling(name):
    spec=importlib.util.spec_from_file_location('_first24_'+Path(name).stem,Path(__file__).resolve().with_name(name))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


stage=sibling('stage_eligible58_materials_v7.py')
workers=sibling('material_distribution_worker_check.py')
recovery=sibling('verified_publication_lock_recovery.py')
VERSION='1.0-nov26-date-bound-eligible58-distribution'
DAY='2026-11-26'
POINTER='material-staging/eligible58-20261126-pending-import.json'
EXPECTED=stage.EXPECTED
UNAVAILABLE=stage.UNAVAILABLE
check_scope=stage.check_scope
BOOTSTRAP=workers.re.compile(workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_distribute_eligible58_materials_20261126').replace('verified-first24-material-distribution','verified-nov26-eligible58-material-distribution'))


def inspect_workers(root):
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑检查任务')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',workers.WORKERS],input=b'{}',capture_output=True,timeout=20,creationflags=0x08000000)
    if result.returncode:raise RuntimeError('无法核对当前项目任务，未导入素材')
    rows=json.loads(result.stdout.decode('utf-8-sig'));filtered=[]
    for row in rows:
        try:args=workers.win_args(row['command'])
        except ValueError:args=[]
        if row['pid']!=os.getpid() and args and workers.win_path(args[-1])==workers.win_path(root.parent/'IG-AutoUpload'):continue
        filtered.append(row)
    with patch.object(workers,'BOOTSTRAP',BOOTSTRAP):live,_=workers.classify_workers(filtered,root,os.getpid(),Path(__file__).resolve())
    return live


def execute(root,source=None):
    root=stage.setup(root)
    live=inspect_workers(root)
    if live:raise RuntimeError('仍有FB项目任务，未另开分配：'+','.join(str(r['pid']) for r in live))
    folder=stage.safe_child(root,root/'material-staging/eligible58-20261126-dispatch');folder.mkdir(parents=True,exist_ok=True)
    with stage.staging_lock(folder):return dispatch(root,source)


def dispatch(root,source=None):
    upload=stage.upload
    actual=stage.datetime.now(timezone.utc).astimezone(stage.materials.BJ).date().isoformat()
    if not (root/POINTER).exists() and actual!=DAY:raise ValueError('首次分配仅用于11月26日；不重用旧日期或错选素材。')
    rows,_=stage.target_snapshot(root,scope='eligible58');check_scope(rows)
    print('当前分配范围：',len({r['account'] for r in rows}),'个FB账号，',len(rows),'个目标；停用36账号含fb32、fb52。',flush=True)
    pointer=stage.safe_child(root,root/POINTER)
    saved=upload.read_json(pointer,{})
    pending=None
    if saved and source is None:
        original=stage.safe_child(root,root/saved['manifest'])
        if not original.exists():
            if saved.get('sha256') is not None:raise ValueError('原58条分配清单缺失，保留指针，不猜选或重新分配。')
            pointer.replace(pointer.with_name(pointer.name+'.unplanned-'+stage.uuid.uuid4().hex[:8]+'.bak'))
            saved={}
    if saved and source is None:
        pending=stage.safe_child(root,root/saved['manifest'])
        if not pending.exists():
            pending,value=stage.prepare(root,Path(saved['source']),scope='eligible58')
        else:
            _,existing=stage.validate_stage(root,pending)
            pending,value=stage.prepare(root,Path(existing['payload']['source']),scope='eligible58',resume_manifest=pending)
        if saved.get('sha256') is not None and saved.get('sha256')!=value['sha256']:raise ValueError('待导入清单指纹异常。')
        if value['payload']['date']!=DAY:raise ValueError('今天的分配指针指向其他日期，保留原文件。')
        if value['payload']['distribution']['payload'].get('target_scope')!='eligible58':raise ValueError('待导入清单不是本次58个目标范围。')
        check_scope(value['payload']['distribution']['payload']['assignments'])
        print('继续上次已准备的58条素材；保留原分配，不重新选择或重排。',flush=True)
    else:
        if saved:raise ValueError('今天已有分配指针，请重跑同一入口续跑，不更换来源或重排。')
        if actual!=DAY:raise ValueError('新分配仅用于11月26日；已有完整暂存可续跑，不在其他日期选择新素材。')
        # Persist the source-specific manifest before copying so interrupted
        # staging also resumes the original allocation across midnight.
        chosen=stage.materials.validate_source(Path(source or stage.materials.choose_source()).resolve())
        source_id=stage.hashlib.sha256(str(chosen).casefold().encode()).hexdigest()[:16]
        day=stage.datetime.now(timezone.utc).astimezone(stage.materials.BJ).date().isoformat()
        proposed=root/'material-staging'/day/(source_id+'-eligible58')/'manifest.json'
        upload.save_json(pointer,dict(manifest=str(proposed.relative_to(root)),source=str(chosen),complete=False))
        try:
            pending,value=stage.prepare(root,chosen,scope='eligible58');check_scope(value['payload']['distribution']['payload']['assignments'])
        except BaseException:
            # No immutable plan exists yet: retain a diagnostic copy, but permit
            # selecting a corrected folder on the next launch. A planned copy
            # interruption keeps its original pointer and exact assignment.
            if not proposed.exists() and pointer.exists():
                backup=pointer.with_name(pointer.name+'.unplanned-'+stage.uuid.uuid4().hex[:8]+'.bak')
                pointer.replace(backup)
            raise
    upload.save_json(pointer,dict(manifest=str(pending.relative_to(root)),sha256=value['sha256'],complete=False))
    # Override the old manual import hint: this wrapper carries the correctly
    # verified venv process-chain checker through the final import as well.
    command='& '+' '.join("'"+a.replace("'","''")+"'" for a in (sys.executable,'-u',str(Path(__file__).resolve()),str(root)))
    (pending.parent/'导入指令.txt').write_text(command+'\n',encoding='utf-8-sig')
    print('58条分配已准备：跳过完整36个暂停账号，包含fb23。原件保留，不发布视频。',flush=True)
    print('接下来自动等待当前视频、评论及登录检查退出后导入正式inbox；请保留此窗口。中断后重跑同一入口可继续。',flush=True)
    wait_started=time.monotonic()
    while True:
        if time.monotonic()-wait_started>=120:raise RuntimeError('等待其他任务已达120秒，今天暂存保留；重跑同一入口继续，不会重复分配。')
        live=inspect_workers(root)
        if live:
            print('素材已准备，等待原任务结束后自动导入。运行任务PID：',','.join(str(r['pid']) for r in live),'；15秒后检查。',flush=True)
            time.sleep(15);continue
        try:
            settings=upload.read_json(root/stage.materials.SETTINGS,{})
            if settings.get('allocation_date','')>DAY:raise ValueError('已有更新日期的正式分配，未覆盖；今天暂存原件保留。')
            recovery.recover_locks(root)
            with patch.object(stage,'active_workers',side_effect=inspect_workers):stage.import_stage(root,pending)
            break
        except RuntimeError as error:
            if not any(word in str(error) for word in ('仍有上传任务或遗留锁','仍有任务进程运行','锁内进程仍在运行')):raise
            print('原任务仍在收尾，素材保留；15秒后继续检查。',flush=True);time.sleep(15)
    upload.save_json(pointer,dict(manifest=str(pending.relative_to(root)),sha256=value['sha256'],complete=True))
    publish_current_pointer(root,upload.read_json(pointer,{}))
    summary=['11月26日已正式分配58个目标，每个目标1条视频；原素材保留，没有发布视频。','暂停账号不分配：'+','.join(sorted(UNAVAILABLE)),'所有暂停账号现有目录保持原样。','多余未分配素材数量：'+str(value['payload']['distribution']['payload']['leftover_count'])]
    for row in value['payload']['distribution']['payload']['assignments']:
        path=stage.materials.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name']
        summary.append(row['account']+'/'+row['target']+' <- '+row['video_filename']+' -> '+str(path))
    (pending.parent/'分配完成清单.txt').write_text('\n'.join(summary),encoding='utf-8-sig')
    print('正式分配完成：58个目标；清单：',pending.parent/'分配完成清单.txt',flush=True)
    return 0


def publish_current_pointer(root,value):
    from add_fb_accounts import locked
    path=stage.safe_child(root,root/'material-staging/eligible58-pending-import.json')
    with locked():
        _,manifest=stage.validate_stage(root,root/value['manifest'])
        if manifest['payload']['date']!=DAY or value.get('sha256')!=manifest['sha256'] or value.get('complete') is not True:raise ValueError('今天的正式分配尚未完成，不更新发布指针。')
        existing=stage.upload.read_json(path,None)
        if existing==value:return
        if existing is not None:
            backup=root/'backups'/('nov26-distribution-pointer-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
            shutil.copy2(path,backup/path.name)
        stage.upload.save_json(path,value)


class Tee:
    def __init__(self,*streams):self.streams=streams
    def write(self,text):
        for stream in self.streams:stream.write(text);stream.flush()
        return len(text)
    def flush(self):
        for stream in self.streams:stream.flush()

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的另一个PowerShell窗口运行。')
        root=Path(sys.argv[1]).resolve()
        with (root/'logs/eligible58-2026-11-26-distribution-run.log').open('a',encoding='utf-8') as output,contextlib.redirect_stdout(Tee(sys.stdout,output)):
            raise SystemExit(execute(root))
    except KeyboardInterrupt:print('已暂停素材分配；原发布任务、原素材、暂存及导入进度均保留，重跑本入口继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
