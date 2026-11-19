"""Explicitly archive local tasks and delete a fixed snapshot of managed video media."""
import copy
import ctypes
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(1, str(Path(sys.argv[1]).resolve()))

import fb_upload as upload
from add_fb_accounts import locked
import cleanup_confirmed_published_videos as media
import material_distribution_worker_check as workers
import verified_publication_lock_recovery as recovery

VERSION = '1.0-user-archive-delete-all-managed-video-media'
DAY = '2026-11-19'
ARCHIVE_DAY = '2026-11-18'
PLAN = 'logs/user-video-cleanup-20261119.json'
PROGRESS = 'logs/user-video-cleanup-20261119-progress.json'
ARCHIVES = 'logs/user-archived-video-tasks-20261119.json'
AUDIT = 'logs/user-video-cleanup-20261119-audit.jsonl'
POINTERS = ('eligible62-pending-import.json', 'eligible78-pending-import.json', 'first24-pending-import.json')
EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi', '.wmv', '.flv', '.mpeg', '.mpg', '.3gp', '.mts', '.m2ts'}
MANAGED = ('videos', 'material-staging', 'backups', 'logs', 'archive', 'archives', 'completed')
PROTECTED = {'.venv', 'venv', '.git', '__pycache__', 'profiles', 'browser-profile', 'browser-profiles', 'browsers', 'node_modules', 'tools'}
BOOTSTRAP = re.compile(workers.BOOTSTRAP.pattern.replace(
    'start_distribute_first24_materials_20261116', 'start_archive_delete_project_videos_20261119').replace(
    'verified-first24-material-distribution', 'verified-user-archive-delete-project-videos'))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic(path, value):
    atomic_bytes(path,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8'))


def read(path, default=None):
    return media.read_json(path) if path.exists() else copy.deepcopy(default)


def checked(path):
    value = read(path)
    if not isinstance(value, dict) or value.get('sha256') != media.digest(value.get('payload', {})):
        raise ValueError('清单指纹不一致，未删除视频：' + path.name)
    return value


def safe(root, path):
    return media.safe(root, path)


def metadata(path):
    value = path.stat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError('不是普通单链接视频文件，保留。')
    return dict(size=value.st_size, mtime_ns=value.st_mtime_ns, ctime_ns=value.st_ctime_ns,
                device=value.st_dev, inode=value.st_ino)


def roots(root):
    found = [root / name for name in MANAGED if (root / name).is_dir()]
    settings = read(safe(root, root / 'material_distribution_settings.json'), {})
    if isinstance(settings, dict) and isinstance(settings.get('source'), str):
        source = Path(settings['source'])
        source = source if source.is_absolute() else root / source
        try:
            source = safe(root, source)
            parts = {p.casefold() for p in source.relative_to(root).parts}
            if source != root and source.is_dir() and not parts & PROTECTED:
                found.append(source)
        except (ValueError, OSError):
            pass  # External source originals are intentionally outside this authorization.
    return sorted(set(found), key=str)


def inventory(root):
    rows = {}
    skipped = []
    def add(path):
        if path.suffix.lower() not in EXTENSIONS:
            return
        try:
            path = safe(root, path)
            rows[str(path.relative_to(root))] = dict(path=str(path.relative_to(root)), **metadata(path))
        except (ValueError, OSError) as error:
            skipped.append(dict(path=str(path), reason=str(error)))
    for path in root.iterdir():
        if path.is_file():
            add(path)
    for base in roots(root):
        safe(root, base)
        def scan_error(error):
            skipped.append(dict(path=str(error.filename), reason='目录无法扫描：'+str(error)))
        for folder, dirs, files in os.walk(base, followlinks=False, onerror=scan_error):
            current = Path(folder)
            if any((current / marker).is_file() for marker in ('Login Data', 'Local State', 'Preferences')):
                dirs[:] = []
                continue
            kept = []
            for name in dirs:
                if name.casefold() in PROTECTED:
                    continue
                try:
                    safe(root, current / name)
                    kept.append(name)
                except (ValueError, OSError):
                    skipped.append(dict(path=str(current/name), reason='链接或不安全目录，保留'))
            dirs[:] = kept
            for name in files:
                add(current / name)
    return sorted(rows.values(), key=lambda r:r['path']), skipped


def yesterday_jobs(root):
    jobs = {}
    bindings = []
    for path in sorted((root / 'logs').glob('frozen-material-*.json')):
        value = read(safe(root, path), {})
        payload = value.get('payload', {}) if isinstance(value, dict) else {}
        day = payload.get('material_source_date', payload.get('material_date', payload.get('date')))
        if day != ARCHIVE_DAY:
            continue
        value = checked(path)
        bindings.append(dict(manifest=path.name, sha256=value['sha256']))
        for job in payload.get('jobs', []):
            if not re.fullmatch('[a-f0-9]{64}', str(job.get('key', ''))):
                raise ValueError('昨天的冻结任务指纹异常，未清理。')
            old = jobs.get(job['key'])
            if old is not None and old != job:
                raise ValueError('昨天的原任务存在冲突，未清理。')
            jobs[job['key']] = job
    return jobs, bindings


def referenced_paths(root, row):
    paths = set()
    for name in ('video', 'archived_video', 'material_archive_video'):
        item = row.get(name)
        if not isinstance(item, str) or not item:
            continue
        path = Path(item)
        try:
            path = safe(root, path if path.is_absolute() else root/path)
            paths.add(str(path.relative_to(root)))
        except (ValueError, OSError):
            pass
    return paths


def prepare(root):
    plan_path = safe(root, root / PLAN)
    if plan_path.exists():
        value = checked(plan_path)
        if (value['payload'].get('schema') != VERSION or value['payload'].get('root') != str(root)
                or value['payload'].get('archive_material_date') != ARCHIVE_DAY):
            raise ValueError('原清理范围异常，未另建新清单。')
        return value
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat() != DAY:
        raise ValueError('此入口只在11月19日首次冻结清理范围；之后仅可续同一清单。')
    state_path = safe(root, root / 'logs/publish_state.json')
    state = read(state_path, {})
    if not isinstance(state, dict) or any(not isinstance(row, dict) for row in state.values()):
        raise ValueError('原发布状态格式异常，未删除。')
    files, skipped = inventory(root)
    pointers=[]
    pointer_bytes={}
    for name in POINTERS:
        path=safe(root,root/'material-staging'/name)
        if not path.exists():
            continue
        if not isinstance(read(path),dict):
            raise ValueError('旧素材续分配指针格式异常，未清理。')
        data=path.read_bytes()
        pointers.append(dict(path=str(path.relative_to(root)),sha256=hashlib.sha256(data).hexdigest(),**metadata(path)))
        pointer_bytes[name]=data
    jobs, bindings = yesterday_jobs(root)
    selected_paths = {r['path'] for r in files}
    keys = sorted(set(jobs) | {key for key,row in state.items() if referenced_paths(root,row) & selected_paths})
    payload = dict(schema=VERSION, root=str(root), authorized_on=DAY, archive_material_date=ARCHIVE_DAY,
                   created_at=stamp(), scope='all-managed-video-files-regardless-publication-result',
                   files=files, skipped=skipped, retired_pointers=pointers,
                   state_keys=keys, yesterday_jobs=jobs, source_bindings=bindings,
                   original_state_sha256=media.digest(state), no_external_source_deletion=True,
                   no_publication_success_inferred=True)
    value = dict(payload=payload, sha256=media.digest(payload))
    backup = safe(root, root/'backups'/('user-video-cleanup-'+value['sha256'][:16]))
    backup.mkdir(parents=True, exist_ok=True)
    atomic(backup/'publish-state-before.json', state)
    atomic(backup/'cleanup-plan.json', value)
    for name,data in pointer_bytes.items():
        atomic_bytes(safe(root,backup/'retired-pointers'/name),data)
    atomic(plan_path, value)
    return value


def archive_tasks(root, value):
    state_path = safe(root, root/'logs/publish_state.json')
    state = read(state_path, {})
    if not isinstance(state, dict):
        raise ValueError('发布状态异常，停止清理。')
    ledger_path = safe(root, root/ARCHIVES)
    ledger = read(ledger_path, dict(schema='user-archived-local-video-tasks-v1', rows={}))
    if ledger.get('schema') != 'user-archived-local-video-tasks-v1' or not isinstance(ledger.get('rows'),dict):
        raise ValueError('用户归档台账异常，未删除视频。')
    previous = read(safe(root,root/'backups'/('user-video-cleanup-'+value['sha256'][:16])/'publish-state-before.json'))
    if previous is None or media.digest(previous) != value['payload']['original_state_sha256']:
        raise ValueError('原状态备份不符，未删除。')
    for key in value['payload']['state_keys']:
        row = state.get(key)
        old = previous.get(key)
        if row is not None and row.get('user_archive_plan_sha256') != value['sha256']:
            if row != old:
                raise ValueError('冻结后原任务状态发生变化，保留素材，未覆盖。')
            row.setdefault('publication_status_before_user_archive', row.get('status', 'not_started'))
            row.update(status='archived', user_archived_at=stamp(), user_archive_plan_sha256=value['sha256'],
                       archive_method='user_requested_archive_and_delete_video_media', video_retry_disabled=True)
        job = value['payload']['yesterday_jobs'].get(key, {})
        ledger['rows'][key] = dict(archive_status='archived', plan_sha256=value['sha256'],
            material_date=ARCHIVE_DAY if key in value['payload']['yesterday_jobs'] else None,
            publication_status_before_archive=(old or {}).get('status', 'not_started'),
            comment_status_before_archive=(old or {}).get('comment_status', 'not_started'),
            account=(old or {}).get('account',job.get('account')),
            target=(old or {}).get('target',job.get('target')), video_retry_disabled=True)
    atomic(ledger_path, ledger)
    atomic(state_path, state)


class AuditFailure(RuntimeError):
    pass


def event(stream, value):
    try:
        media.append_event(stream, value)
    except OSError as error:
        raise AuditFailure('清理审计无法持久写入，已停止后续删除。') from error


def validate_handle(root, path, stream, row):
    safe(root, path)
    opened = os.fstat(stream.fileno())
    if os.name == 'nt':
        # The Windows handle denies write/delete sharing. Check the locked path
        # with the same stat API used for the plan; CRT fstat timestamps/file IDs
        # can have different precision across supported Windows Python versions.
        current = metadata(path)
        if current != {k:row[k] for k in current} or opened.st_size != row['size']:
            raise ValueError('文件在冻结后变化，保留，不删除新替换视频。')
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        function = kernel.GetFinalPathNameByHandleW
        function.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
        function.restype=wintypes.DWORD
        buffer=ctypes.create_unicode_buffer(32768)
        length=function(msvcrt.get_osfhandle(stream.fileno()),buffer,len(buffer),0)
        if not length or length >= len(buffer):
            raise ValueError('无法核对视频实际路径，保留。')
        actual=buffer.value
        if actual.startswith('\\\\?\\UNC\\'):
            actual='\\\\'+actual[8:]
        elif actual.startswith('\\\\?\\'):
            actual=actual[4:]
        if str(Path(actual).resolve()).casefold() != str(path.resolve()).casefold():
            raise ValueError('打开的视频路径变化，保留。')
    else:
        current = dict(size=opened.st_size, mtime_ns=opened.st_mtime_ns, ctime_ns=opened.st_ctime_ns,
                       device=opened.st_dev, inode=opened.st_ino)
        if current != {k:row[k] for k in current} or opened.st_nlink != 1:
            raise ValueError('文件在冻结后变化，保留，不删除新替换视频。')


def retire_pointers(root,value,progress,progress_path,audit):
    completed=progress.setdefault('retired_pointers',{})
    for row in value['payload'].get('retired_pointers',[]):
        if row['path'] in completed:
            continue
        path=safe(root,root/row['path'])
        backup=safe(root,root/'backups'/('user-video-cleanup-'+value['sha256'][:16])/'retired-pointers'/path.name)
        if not backup.is_file() or hashlib.sha256(backup.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('原素材指针备份不符，未删除媒体。')
        if path.exists():
            with media.deletion_handle(path) as (stream,remove):
                validate_handle(root,path,stream,row)
                if hashlib.sha256(stream.read()).hexdigest()!=row['sha256']:
                    raise ValueError('素材续分配指针已变化，保留新任务，停止本次清理。')
                event(audit,dict(event='retire_pointer_intent',at=stamp(),path=row['path'],backup=str(backup.relative_to(root))))
                remove()
        completed[row['path']]='retired-with-backup'
        event(audit,dict(event='retired_pointer',at=stamp(),path=row['path']))
        atomic(progress_path,progress)


def execute(root, apply=False):
    root=Path(root).resolve()
    if root != upload.ROOT.resolve() or not safe(root,root/'upload_config.json').is_file():
        raise ValueError('请在原上传目录运行，未扫描其他磁盘。')
    with patch.object(workers,'BOOTSTRAP',BOOTSTRAP):
        live=workers.active_workers(root,Path(__file__).resolve())
    if live:
        raise ValueError('仍有发布/分配/登录检查任务，请先等任务退出：'+','.join(str(r['pid']) for r in live))
    recovery.recover_locks(root)
    with locked():
        value=prepare(root)
        rows=value['payload']['files']
        print('固定清理范围：',len(rows),'个视频，约',f'{sum(r["size"] for r in rows)/1024**3:.2f} GB',flush=True)
        print('仅清理程序管理的视频；文案、程序、登录资料、配置、日志和外部素材原件保留。',flush=True)
        if value['payload']['skipped']:
            print('扫描时保留的链接或需检查路径：',len(value['payload']['skipped']),'个，详见原清单。',flush=True)
        if not apply:
            print('仅预览，未归档状态或删除视频。',flush=True)
            return dict(plan=value,deleted=[],skipped=[])
        progress_path=safe(root,root/PROGRESS)
        progress=read(progress_path,dict(plan_sha256=value['sha256'],rows={}))
        if progress.get('plan_sha256') != value['sha256'] or not isinstance(progress.get('rows'),dict):
            raise ValueError('清理进度与原范围不符，未删除。')
        archive_tasks(root,value)
        deleted=[];skipped=[]
        with safe(root,root/AUDIT).open('a',encoding='utf-8') as audit:
            event(audit,dict(event='start',plan_sha256=value['sha256'],at=stamp()))
            retire_pointers(root,value,progress,progress_path,audit)
            for number,row in enumerate(rows,1):
                if progress['rows'].get(row['path'],{}).get('status') in {'deleted','already_missing'}:
                    continue
                path=safe(root,root/row['path'])
                result=dict(path=row['path'],size=row['size'])
                try:
                    if not path.exists():
                        result.update(status='already_missing')
                    else:
                        current_metadata=metadata(path)
                        if current_metadata != {k:row[k] for k in current_metadata}:
                            raise ValueError('文件在冻结后变化，保留新替换内容。')
                        with media.deletion_handle(path) as (stream,remove):
                            validate_handle(root,path,stream,row)
                            content=hashlib.sha256()
                            for block in iter(lambda:stream.read(1024*1024),b''):
                                content.update(block)
                            validate_handle(root,path,stream,row)
                            result['sha256']=content.hexdigest()
                            event(audit,dict(event='delete_intent',at=stamp(),**result))
                            remove()
                        result['status']='deleted'
                        deleted.append(result)
                        print(number,'/',len(rows),'已删除视频：',row['path'],flush=True)
                except (OSError,ValueError) as error:
                    result.update(status='preserved',reason=str(error));skipped.append(result)
                    print('保留需检查：',row['path'],str(error),flush=True)
                event(audit,dict(event='file_result',at=stamp(),**result))
                progress['rows'][row['path']]=result
                atomic(progress_path,progress)
            event(audit,dict(event='finished',at=stamp(),deleted=len(deleted),preserved=len(skipped)))
        done=sum(r.get('status') in {'deleted','already_missing'} for r in progress['rows'].values())
        progress.update(complete=done==len(rows),updated_at=stamp())
        atomic(progress_path,progress)
        print('本次删除',len(deleted),'个视频，约',f'{sum(r["size"] for r in deleted)/1024**3:.2f} GB；保留需检查',len(skipped),'个。',flush=True)
        print('昨天任务已记录为归档；原发布/评论结果留在状态备份及归档台账，不冒充发布成功。',flush=True)
        print('原清理清单完成：',done,'/',len(rows),'；之后新增视频不在这份清单内。',flush=True)
        print('记录：',root/PLAN,'；进度：',progress_path,flush=True)
        return dict(plan=value,deleted=deleted,skipped=skipped,complete=progress['complete'])


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':
            raise ValueError('请在原Windows电脑的PowerShell窗口运行。')
        result=execute(Path(sys.argv[1]),apply=True)
        raise SystemExit(0 if result['complete'] else 3)
    except KeyboardInterrupt:
        print('已暂停清理；原清单和进度保留，重跑只继续这份清单，不纳入之后新增视频。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',str(error) or type(error).__name__,flush=True)
        raise SystemExit(1)
