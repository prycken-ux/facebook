"""Free disk space from old, fingerprint-proven successful archive MP4s only.

No uploader state/config/credentials, inbox, staging, software or backup is
modified. Deletion is explicit (--apply), journaled, and revalidated per file.
"""
import argparse,contextlib,ctypes,hashlib,json,os,re,shutil,stat,sys,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path

VERSION='1.0-confirmed-old-archive-media-only'
MIN_AGE=timedelta(hours=24)
CHUNK=1024*1024


def linked(path):
    info=path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&0x400)


def safe(root,path):
    root=Path(root);path=Path(path)
    if not path.is_absolute():path=root/path
    path.absolute().relative_to(root.absolute())
    for item in (path,*path.parents):
        if item==root.parent:break
        if item.exists() or item.is_symlink():
            if linked(item):raise ValueError('路径包含链接或重解析点，保留。')
    path.resolve().relative_to(root.resolve())
    return path


def walk(root):
    for folder,dirs,files in os.walk(root,followlinks=False):
        current=Path(folder)
        kept=[]
        for name in dirs:
            try:
                if not linked(current/name):kept.append(name)
            except OSError:pass
        dirs[:]=kept
        for name in files:
            path=current/name
            try:
                if not linked(path) and path.is_file():yield path
            except OSError:continue


def read_json(path):
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('JSON存在重复键，保留原文件。')
            value[key]=item
        return value
    with path.open('r',encoding='utf-8-sig') as stream:return json.load(stream,object_pairs_hook=unique)


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def published_before(row,cutoff):
    if not isinstance(row,dict) or row.get('status')!='published':return False
    if not (row.get('confirmation_method') or row.get('success_message')):return False
    if not (row.get('published_at') or row.get('confirmed_at')):return False
    dates=[]
    for name in ('published_at','confirmed_at','archived_at','post_intent_at','created'):
        if row.get(name):
            try:
                value=datetime.fromisoformat(row[name].replace('Z','+00:00'))
                if value.tzinfo is None:return False
                dates.append(value)
            except (ValueError,TypeError,AttributeError):return False
    return bool(dates) and max(dates)<=cutoff


def inventory(root):
    sizes={};count=0
    for path in walk(root):
        try:size=path.stat().st_size
        except OSError:continue
        name=path.relative_to(root).parts[0];sizes[name]=sizes.get(name,0)+size;count+=1
    return dict(bytes_by_top=sizes,files=count,free_bytes=shutil.disk_usage(root).free)


def source_roots(root):
    """Retain any archive folder explicitly chosen as a material source."""
    paths=[root/'material_distribution_settings.json']
    paths+=list((root/'logs/material-distribution').glob('*/*.json'))
    paths+=list((root/'material-staging').glob('*/*/manifest.json'))
    found=[]
    for path in paths:
        if not path.is_file():continue
        safe(root,path);value=read_json(path)
        if not isinstance(value,dict):raise ValueError('素材来源记录格式异常，未删除。')
        candidates=[value.get('source'),value.get('payload',{}).get('source'),value.get('payload',{}).get('distribution',{}).get('payload',{}).get('source')]
        for item in candidates:
            if not isinstance(item,str) or not item:continue
            candidate=Path(item)
            if not candidate.is_absolute():candidate=root/candidate
            found.append(candidate.resolve())
    return found


def archive_pair(root,path):
    safe(root,path);parts=path.relative_to(root).parts
    if (len(parts)<5 or parts[0]!='videos' or not re.fullmatch(r'fb[0-9]{2,}',parts[1])
            or not re.fullmatch(r'personal|page[0-9]{2,}',parts[2]) or parts[3] not in {'completed','archive'} or path.suffix.lower()!='.mp4'):
        raise ValueError('不是账号视频归档文件。')
    return parts[1],parts[2]


def protected(root,state):
    result=set()
    for row in state.values():
        if not isinstance(row,dict):raise ValueError('发布状态格式异常。')
        if row.get('status')=='published':continue
        for name in ('video','archived_video','material_archive_video'):
            value=row.get(name)
            if isinstance(value,str) and value:
                path=Path(value);path=path if path.is_absolute() else root/path
                result.add(str(path.resolve()).casefold())
    return result


def fingerprints(stream,owners):
    hashes={owner:hashlib.sha256((owner+'\0').encode()) for owner in owners};raw=hashlib.sha256();size=0
    stream.seek(0)
    for chunk in iter(lambda:stream.read(CHUNK),b''):
        size+=len(chunk);raw.update(chunk)
        for value in hashes.values():value.update(chunk)
    return dict(size=size,sha256=raw.hexdigest()),{owner:value.hexdigest() for owner,value in hashes.items()}


def eligible(root,path,state,cutoff,target_key,stream=None,roots=None):
    pair=archive_pair(root,path);info=path.stat()
    if info.st_nlink!=1 or not info.st_size or info.st_mtime>cutoff.timestamp():raise ValueError('新文件、硬链接或空文件，保留。')
    if str(path.resolve()).casefold() in protected(root,state):raise ValueError('仍被未成功任务引用，保留。')
    for source in roots if roots is not None else source_roots(root):
        if path.resolve()==source or source in path.resolve().parents:raise ValueError('仍是素材来源目录中的文件，保留。')
    owners={}
    for key,row in state.items():
        if (row.get('account'),row.get('target'))!=pair or not published_before(row,cutoff) or not re.fullmatch(r'[a-f0-9]{64}',key):continue
        try:owner=target_key(row['url'])
        except (ValueError,KeyError,TypeError):continue
        owners.setdefault(owner,set()).add(key)
    if not owners:raise ValueError('没有24小时前的已确认成功记录，保留。')
    if stream is None:
        with path.open('rb') as handle:info,keys=fingerprints(handle,owners)
    else:info,keys=fingerprints(stream,owners)
    matches=[key for owner,key in keys.items() if key in owners[owner]]
    if len(matches)!=1:raise ValueError('视频内容未唯一匹配已成功任务指纹，保留。')
    return dict(path=str(path.relative_to(root)),account=pair[0],target=pair[1],key=matches[0],**info)


@contextlib.contextmanager
def deletion_handle(path):
    """Windows denies writes/deletes while hashing, then deletes this exact handle."""
    if os.name!='nt':
        with path.open('rb') as stream:
            before=os.fstat(stream.fileno())
            def remove():
                now=path.lstat()
                if (now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns,now.st_nlink)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,1) or linked(path):raise ValueError('文件核对期间变化，保留。')
                path.unlink()
            yield stream,remove
        return
    import msvcrt
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    kernel.SetFileInformationByHandle.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD];kernel.SetFileInformationByHandle.restype=wintypes.BOOL
    # GENERIC_READ | DELETE, FILE_SHARE_READ, OPEN_EXISTING,
    # FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN.
    handle=kernel.CreateFileW(str(path),0x80010000,1,None,3,0x08200000,None)
    if handle==ctypes.c_void_p(-1).value:raise OSError('文件被占用或不可安全删除，已保留。')
    try:fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
    except BaseException:kernel.CloseHandle(handle);raise
    with os.fdopen(fd,'rb') as stream:
        def remove():
            class Disposition(ctypes.Structure):_fields_=[('DeleteFile',wintypes.BOOL)]
            info=Disposition(True)
            if not kernel.SetFileInformationByHandle(handle,4,ctypes.byref(info),ctypes.sizeof(info)):raise OSError('系统暂不允许删除此归档视频，已保留。')
        yield stream,remove


def append_event(stream,value):
    stream.write(json.dumps(value,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())


def cleanup(root,target_key,apply=False,now=None):
    root=Path(root).absolute();safe(root,root)
    state_path=safe(root,root/'logs/publish_state.json')
    if not (root/'upload_config.json').is_file():raise ValueError('不是原上传目录。')
    now=now or datetime.now(timezone.utc);cutoff=now-MIN_AGE
    print('正在统计文件夹占用；保留程序、登录资料、配置、日志、文案、全部inbox和暂存素材。',flush=True)
    before=inventory(root)
    for name,size in sorted(before['bytes_by_top'].items(),key=lambda r:r[1],reverse=True)[:10]:print('占用：',name,f'{size/1024**3:.2f} GB',flush=True)
    state=read_json(state_path)
    if not isinstance(state,dict):raise ValueError('发布记录格式异常。')
    sources=source_roots(root);plan=[];skipped=0
    for path in walk(root/'videos'):
        if path.suffix.lower()!='.mp4':continue
        try:plan.append(eligible(root,path,state,cutoff,target_key,roots=sources))
        except (ValueError,OSError):skipped+=1
    print('可清理的旧成功归档视频：',len(plan),'条，约',f'{sum(r["size"] for r in plan)/1024**3:.2f} GB','；其余视频保留。',flush=True)
    if not apply:return dict(planned=plan,deleted=[],skipped=skipped,before=before)
    folder=safe(root,root/'logs/storage-cleanup');folder.mkdir(exist_ok=True)
    ident=now.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8];report=folder/(ident+'.jsonl')
    with report.open('x',encoding='utf-8') as audit:
        append_event(audit,dict(event='plan',version=VERSION,created_at=now.isoformat(),cutoff=cutoff.isoformat(),before=before,files=plan,
                               original_success_records={r['key']:state[r['key']] for r in plan}))
        deleted=[]
        for row in plan:
            path=safe(root,root/row['path'])
            try:
                current=read_json(state_path)
                with deletion_handle(path) as (stream,remove):
                    checked=eligible(root,path,current,cutoff,target_key,stream=stream)
                    if checked!=row:raise ValueError('清理计划后文件或身份变化，保留。')
                    # Check again after hashing; do not overwrite concurrent uploader changes.
                    latest=read_json(state_path);safe(root,path)
                    if (latest.get(row['key'])!=current.get(row['key']) or str(path.resolve()).casefold() in protected(root,latest)):
                        raise ValueError('核对期间任务记录变化，保留。')
                    append_event(audit,dict(event='delete_intent',**row));remove()
                deleted.append(row);append_event(audit,dict(event='deleted',**row))
                print('已清理旧成功视频：',row['account'],row['target'],path.name,flush=True)
            except (OSError,ValueError) as error:
                skipped+=1;append_event(audit,dict(event='retained',path=row['path'],reason=str(error)));print('此文件保留：',path.name,str(error),flush=True)
        after=shutil.disk_usage(root).free
        append_event(audit,dict(event='finished',deleted_files=len(deleted),deleted_bytes=sum(r['size'] for r in deleted),after_free_bytes=after))
    print('清理完成：',len(deleted),'条，文件合计',f'{sum(r["size"] for r in deleted)/1024**3:.2f} GB',flush=True)
    print('磁盘可用：清理前',f'{before["free_bytes"]/1024**3:.2f} GB','；清理后',f'{after/1024**3:.2f} GB','。审计记录：',report,flush=True)
    return dict(planned=plan,deleted=deleted,skipped=skipped,before=before,after_free_bytes=after,report=str(report))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    parser=argparse.ArgumentParser();parser.add_argument('root');parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
        root=Path(args.root).absolute();sys.path.insert(0,str(root));import fb_upload as upload
        if root.resolve()!=upload.ROOT.resolve():raise ValueError('上传目录不匹配。')
        if (root/'logs/upload.lock').exists() or (root/'logs/batch.lock').exists():
            print('检测到上传锁：本工具不操作锁和当前发布队列，只清理24小时前已确认成功的归档视频。',flush=True)
        cleanup(root,upload.target_key,apply=args.apply)
    except KeyboardInterrupt:print('已暂停清理，保留逐文件审计；发布记录和程序未改动。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
