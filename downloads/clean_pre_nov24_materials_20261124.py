"""Delete proven pre-Nov24 video material, preserving current/future content and ledgers."""
import copy,hashlib,json,os,re,stat,sys,uuid
from datetime import date,datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parent))
import cleanup_confirmed_published_videos as media
import material_distribution_worker_check as workers
import verified_publication_lock_recovery as recovery
import fb_upload as upload
from add_fb_accounts import locked
from publication_file_state_20261124 import save

DAY='2026-11-24'
CUTOFF='2026-11-23'
EXT={'.mp4','.mov','.m4v','.webm','.mkv','.avi','.wmv','.flv','.mpeg','.mpg','.3gp','.mts','.m2ts'}
PROTECTED={'tools','profiles','browser-profile','browser-profiles','browsers','.venv','venv','.git','__pycache__','node_modules'}
BOOTSTRAP=re.compile(workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_publish_guarded_nov24_20261124').replace('verified-first24-material-distribution','verified-nov24-guarded-publication'))

def day(v):
    try:return date.fromisoformat(v).isoformat() if isinstance(v,str) else None
    except ValueError:return None

def stamp():return datetime.now(timezone.utc).isoformat()
def read(path,default=None):return media.read_json(path) if path.exists() else copy.deepcopy(default)
def checked(path):
    value=media.read_json(path)
    if not isinstance(value,dict) or value.get('sha256')!=media.digest(value.get('payload',{})):raise ValueError('清单指纹异常，未删除：'+str(path))
    return value

def safe_any(path):
    path=Path(path).absolute()
    for p in (path,*path.parents):
        if p.exists() or p.is_symlink():
            if media.linked(p):raise ValueError('链接或重解析点，保留：'+str(path))
    if set(p.casefold() for p in path.parts)&PROTECTED:raise ValueError('程序或浏览器资料目录，保留。')
    return path

def fingerprint(path,stream=None):
    safe_any(path);s=path.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise ValueError('不是普通单链接视频。')
    h=hashlib.sha256()
    if stream is None:
        with path.open('rb') as handle:
            for chunk in iter(lambda:handle.read(1024*1024),b''):h.update(chunk)
    else:
        stream.seek(0)
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return dict(size=s.st_size,sha256=h.hexdigest(),mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns,inode=s.st_ino,device=s.st_dev)

def index(root):
    names={};explicit={};protected_hashes=set();protected_names=set();keys={};frozen={};bindings=[];bound={}
    def item(name,size,sha,d):
        if not isinstance(name,str) or Path(name).name!=name or re.search(r'[\\/:\x00-\x1f]',name):raise ValueError('清单视频文件名异常。')
        if type(size)!=int or size<=0 or not re.fullmatch('[a-f0-9]{64}',str(sha)):raise ValueError('清单视频指纹异常。')
        names.setdefault((name,size,sha),set()).add(d)
        if d>=DAY:protected_hashes.add(sha);protected_names.add(name)
    def distribution(value,folder=None):
        p=value['payload'];d=day(p.get('date'))
        if not d:return
        source=Path(p.get('source',''))
        if not source.is_absolute():source=root/source
        for row in p.get('assignments',[]):
            if not re.fullmatch('fb[0-9]{2,}',str(row.get('account',''))) or not re.fullmatch('personal|page[0-9]{2,}',str(row.get('target',''))):raise ValueError('分配目标异常。')
            for f in row.get('files',[]):
                if Path(f.get('name','')).suffix.lower() not in EXT:continue
                for name in {f.get('name'),f.get('destination_name')}:item(name,f['size'],f['sha256'],d)
                # External deletion is limited to exact files recorded in a
                # signed historical distribution, with the recorded content.
                paths=[source/f['name'],root/'videos'/row['account']/row['target']/'inbox'/f['destination_name']]
                if folder:paths.append(folder/'videos'/row['account']/row['target']/'inbox'/f['name'])
                for path in paths:explicit.setdefault(str(path.absolute()),[]).append(dict(date=d,size=f['size'],sha256=f['sha256']))
    for path in sorted((root/'material-staging').glob('*/*/manifest.json')):
        value=checked(media.safe(root,path));p=value['payload']
        nested=p.get('distribution')
        if nested:
            if nested.get('sha256')!=media.digest(nested.get('payload',{})) or nested['payload'].get('date')!=p.get('date'):raise ValueError('暂存分配批次不符。')
            distribution(nested,path.parent);bindings.append(dict(path=str(path.relative_to(root)),sha256=value['sha256']))
    for path in sorted((root/'logs/material-distribution').glob('*/*.json')):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:-reserved50|-eligible78|-eligible62|-eligible60)?\.json',path.name):continue
        value=checked(media.safe(root,path));distribution(value);bindings.append(dict(path=str(path.relative_to(root)),sha256=value['sha256']))
    for path in sorted((root/'logs').glob('*.json')):
        if not re.fullmatch(r'(?:frozen-material|automatic-retry)-\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json',path.name):continue
        value=checked(media.safe(root,path))
        if not path.stem.endswith(value['sha256'][:16]):raise ValueError('冻结任务名不符。')
        frozen[path.name]=value
    memo={}
    def origin(name,seen=()):
        if name in memo:return memo[name]
        if name in seen:raise ValueError('任务来源循环。')
        p=frozen[name]['payload'];d=day(p.get('material_source_date') or p.get('material_date'))
        if d:found={d}
        else:
            parents=[(b.get('manifest'),b.get('sha256')) for b in p.get('source_bindings',[]) if isinstance(b,dict)]
            if p.get('source_manifest'):parents.append((p['source_manifest'],p.get('source_sha256')))
            found=set()
            for parent,sha in parents:
                if parent not in frozen:continue
                if sha not in (None,frozen[parent]['sha256']):raise ValueError('任务父清单指纹不符。')
                found.update(origin(parent,(*seen,name)))
            if not found and day(p.get('date')):found={p['date']}
        memo[name]=found;return found
    for name,value in frozen.items():
        days=origin(name)
        for job in value['payload'].get('jobs',[]):
            key=job.get('key')
            if not re.fullmatch('[a-f0-9]{64}',str(key)):raise ValueError('任务键异常。')
            keys.setdefault(key,set()).update(days)
            for d in days:
                if job.get('video_sha256'):item(job['filename'],job['video_size'],job['video_sha256'],d)
                else:
                    # Original frozen jobs bind owner+bytes via their job key,
                    # rather than storing a raw SHA256. Verify that key against
                    # the actual candidate instead of guessing a media hash.
                    bound.setdefault((job['filename'],job['video_size']),[]).append(dict(date=d,key=key,url=job.get('url')))
                    if d>=DAY:protected_names.add(job['filename'])
    # The current allocation is mandatory, even when there is no frozen video
    # task yet. Protect its source originals, staging copies and inbox content.
    pointer=read(root/'material-staging/eligible60-20261124-pending-import.json',{})
    if pointer.get('complete') is not True:raise ValueError('24号素材未正式分配完成，未删除任何素材。')
    path=media.safe(root,root/pointer.get('manifest',''));current=checked(path)
    if current['sha256']!=pointer.get('sha256') or current['payload'].get('date')!=DAY:raise ValueError('24号分配指针不符。')
    distribution(current['payload']['distribution'],path.parent)
    return names,explicit,protected_hashes,keys,bindings,protected_names,bound

def candidates(root):
    names,explicit,protected,keys,bindings,protected_names,bound=index(root);paths={Path(p) for p in explicit};retained=[]
    for base in [root/n for n in ('videos','material-staging','backups','archive','archives','completed') if (root/n).is_dir()]:
        for folder,dirs,files in os.walk(base,followlinks=False):
            current=Path(folder)
            if any((current/n).is_file() for n in ('Login Data','Local State','Preferences')):dirs[:]=[];continue
            dirs[:]=[n for n in dirs if n.casefold() not in PROTECTED and not media.linked(current/n)]
            for n in files:
                if Path(n).suffix.lower() in EXT:paths.add(current/n)
    rows=[]
    for path in sorted(paths,key=str):
        if not path.exists() and not path.is_symlink():continue
        if path.suffix.lower() not in EXT:continue
        try:
            fp=fingerprint(path)
            if fp['sha256'] in protected:continue
            proofs=set(names.get((path.name,fp['size'],fp['sha256']),set()))
            for binding in bound.get((path.name,fp['size']),[]):
                if binding['url'] and upload.job_key(dict(url=binding['url']),path)==binding['key']:proofs.add(binding['date'])
            proofs.update(r['date'] for r in explicit.get(str(path.absolute()),[]) if (r['size'],r['sha256'])==(fp['size'],fp['sha256']))
            # Only uploader-generated prefixes encode a material batch. Raw
            # camera filename dates and filesystem timestamps never qualify.
            prefix=re.match(r'^(\d{8})-[a-f0-9]{8}-(?:eligible60|eligible62|eligible78|weekend60)-',path.name)
            if prefix:
                token=prefix[1];d=day(token[:4]+'-'+token[4:6]+'-'+token[6:]);proofs.update([d] if d else [])
            try:
                rel=path.relative_to(root/'material-staging');d=day(rel.parts[0])
                if d:proofs.add(d)
            except ValueError:pass
            try:
                rel=path.relative_to(root/'videos');parts=rel.parts
                if len(parts)>3 and parts[2]=='scheduled' and day(parts[3]):proofs.add(parts[3])
            except ValueError:pass
            if not proofs or any(d>=DAY for d in proofs):
                retained.append(dict(path=str(path),reason='来源不明或属于24号及以后'));continue
            rows.append(dict(path=str(path.absolute()),origin_dates=sorted(proofs),**fp))
        except (OSError,ValueError) as error:retained.append(dict(path=str(path),reason=str(error)))
    return rows,retained,keys,bindings,protected_names

def execute(root):
    root=Path(root).resolve()
    if root!=upload.ROOT.resolve():raise ValueError('不是原发布目录。')
    with patch.object(workers,'BOOTSTRAP',BOOTSTRAP):live=workers.active_workers(root,Path(__file__).resolve())
    if live:raise ValueError('仍有项目任务运行，未删除素材：'+','.join(str(r['pid']) for r in live))
    recovery.recover_locks(root)
    with locked():
        rows,retained,keys,bindings,protected_names=candidates(root)
        state_path=media.safe(root,root/'logs/publish_state.json');state=read(state_path,{})
        if not isinstance(state,dict):raise ValueError('发布状态异常。')
        run=uuid.uuid4().hex;backup=media.safe(root,root/'backups'/('pre-nov24-media-cleanup-'+run));backup.mkdir(parents=True)
        save(backup/'publish-state-before.json',state)
        plan=dict(schema='user-delete-materials-through-nov23-v1',authorized_cutoff=CUTOFF,keep_from=DAY,created_at=stamp(),files=rows,retained=retained,bindings=bindings)
        save(backup/'cleanup-plan.json',plan)
        chosen={str(Path(r['path']).absolute()).casefold() for r in rows};changes=[]
        for key,row in state.items():
            if not isinstance(row,dict):raise ValueError('发布记录异常。')
            dates=keys.get(key,set())
            if any(Path(str(row.get(n,''))).name in protected_names for n in ('video','archived_video','material_archive_video')):continue
            if any(d>=DAY for d in dates):continue
            refs={str(Path(v).absolute()).casefold() for n in ('video','archived_video','material_archive_video') if isinstance((v:=row.get(n)),str) and v}
            if not (dates and all(d<=CUTOFF for d in dates)) and not refs&chosen:continue
            row.setdefault('publication_status_before_user_archive',row.get('status','not_started'))
            row.update(status='archived',user_archived_at=stamp(),video_retry_disabled=True,comment_retry_disabled=True,user_archive_method='user-ended-materials-through-nov23',user_archive_audit=str(backup.relative_to(root)))
            changes.append(key)
        save(backup/'archived-keys.json',changes);save(state_path,state)
        report=root/'logs'/('pre-nov24-media-cleanup-'+run+'.jsonl');deleted=0;total=0
        with report.open('x',encoding='utf-8') as audit:
            media.append_event(audit,dict(event='plan',plan=str(backup/'cleanup-plan.json'),count=len(rows),archived_jobs=len(changes)))
            for row in rows:
                path=Path(row['path'])
                try:
                    with media.deletion_handle(safe_any(path)) as (stream,remove):
                        actual=fingerprint(path,stream)
                        if actual!={k:row[k] for k in actual}:raise ValueError('文件在计划后变化，保留。')
                        media.append_event(audit,dict(event='delete_intent',**row));remove()
                    deleted+=1;total+=row['size'];media.append_event(audit,dict(event='deleted',path=str(path),size=row['size']))
                except (OSError,ValueError) as error:media.append_event(audit,dict(event='retained',path=str(path),reason=str(error)))
            media.append_event(audit,dict(event='finished',deleted=deleted,bytes=total,retained=len(rows)-deleted+len(retained)))
        save(root/'logs/pre-nov24-materials-ended.json',dict(cutoff=CUTOFF,at=stamp(),archived_jobs=len(changes),deleted_files=deleted,deleted_bytes=total,retained_for_review=len(rows)-deleted+len(retained),report=str(report),original_status_backup=str(backup/'publish-state-before.json')))
        print('23号及以前素材清理完成：删除',deleted,'个视频，释放',round(total/1024**3,3),'GB；结束旧任务',len(changes),'条。',flush=True)
        print('24号及以后素材、程序、登录资料、文案和提交凭据保留。未知来源/被占用视频保留数量：',len(rows)-deleted+len(retained),'；明细：',report,flush=True)
    return 0

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(execute(Path(sys.argv[1])))
    except Exception as error:print('STOP：'+str(error),flush=True);raise SystemExit(1)
