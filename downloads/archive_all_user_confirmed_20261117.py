"""Archive a fixed snapshot of fb01-fb74 media on explicit user confirmation.

No Facebook requests or inferred platform receipts. Existing comment/AI fields
are retained; locally unregistered owners receive an archive-ledger entry only.
"""
import copy,hashlib,importlib.util,json,os,re,shutil,stat,sys,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parent))
import fb_upload as upload
from add_fb_accounts import locked

VERSION='1.0-all74-media-user-confirmed-archive'
METHOD='user_confirmed_all_existing_account_videos_20261117'
SCHEMA='user-confirmed-all74-video-archive-v1'
JOURNAL='logs/user-confirmed-all74-archive-20261117.json'
LEDGER='logs/user_confirmed_archived_media.json'
EXTENSIONS={'.mp4','.mov','.m4v','.webm','.mkv','.avi'}
ACCOUNTS={f'fb{n:02d}' for n in range(1,75)}


def sibling(name):
    spec=importlib.util.spec_from_file_location('_archive74_'+Path(name).stem,Path(__file__).resolve().with_name(name))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


workers=sibling('material_distribution_worker_check.py')
recovery=sibling('verified_publication_lock_recovery.py')
BOOTSTRAP=re.compile(workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_archive_all_user_confirmed_20261117').replace('verified-first24-material-distribution','verified-user-confirmed-all74-archive'))


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()


def safe(root,path):
    root=Path(root).absolute();path=Path(path)
    if not path.is_absolute():path=root/path
    path.absolute().relative_to(root)
    for item in (path,*path.parents):
        if item==root.parent:break
        if item.exists() or item.is_symlink():
            info=item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('归档路径包含链接，未处理：'+str(item))
    path.resolve().relative_to(root.resolve());return path


def info(root,path,owners=()):
    path=safe(root,path);before=path.stat()
    if not path.is_file():raise ValueError('不是普通素材文件：'+str(path))
    raw=hashlib.sha256();keys={owner:hashlib.sha256((owner+'\0').encode()) for owner in owners}
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):
            raw.update(data)
            for h in keys.values():h.update(data)
    after=path.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('素材正在变化，未移动：'+str(path))
    return dict(size=after.st_size,sha256=raw.hexdigest()),{owner:h.hexdigest() for owner,h in keys.items()}


def pair_ok(account,target):return account in ACCOUNTS and bool(re.fullmatch(r'personal|page[0-9]{2,}',str(target)))


def owner_index(root,state):
    registered={};known={}
    def add(row,configured=False):
        pair=(row.get('account'),row.get('target'))
        if not pair_ok(*pair) or not row.get('url'):return
        try:owner=upload.target_key(row['url'])
        except (ValueError,TypeError,KeyError):return
        known.setdefault(pair,{})[owner]=row['url']
        if configured:registered.setdefault(pair,{}).setdefault(owner,row['url'])
    for name,key in [('upload_config.json','targets'),('account_registry.json','accounts')]:
        value=upload.read_json(safe(root,root/name),{})
        if not isinstance(value,dict) or not isinstance(value.get(key),list):raise ValueError('账号对应表格式异常，未修改：'+name)
        for row in value[key]:
            if not isinstance(row,dict):raise ValueError('账号对应表条目异常。')
            row=dict(row);row.setdefault('target','personal' if row.get('type')=='personal' else 'page01');add(row,True)
    extra=upload.read_json(safe(root,root/'additional_personal_accounts.json'),{})
    for account,slot in extra.get('slots',{}).items():
        row=slot.get('mapping',{})
        if slot.get('state')=='registered' and isinstance(row,dict):add(dict(row,account=account),True)
    for row in state.values():
        if not isinstance(row,dict):raise ValueError('历史发布记录格式异常。')
        add(row)
    return registered,known


def scan(root,state):
    registered,known=owner_index(root,state);rows=[];destinations={}
    videos=safe(root,root/'videos')
    if not videos.is_dir():return rows
    for account in sorted(ACCOUNTS):
        account_dir=safe(root,videos/account)
        if not account_dir.is_dir():continue
        for base in sorted(account_dir.iterdir()):
            if not pair_ok(account,base.name):continue
            safe(root,base)
            if not base.is_dir():continue
            pair=(account,base.name);owners=known.get(pair,{})
            for folder,dirs,files in os.walk(base,followlinks=False):
                folder=safe(root,Path(folder))
                for name in dirs:safe(root,folder/name)
                for name in sorted(files):
                    video=folder/name
                    if video.suffix.lower() not in EXTENSIONS:continue
                    fingerprint,keys=info(root,video,owners)
                    ident=digest(dict(account=account,target=base.name,source=str(video.relative_to(root)),**fingerprint))
                    already=video.relative_to(base).parts[0]=='completed'
                    destdir=video.parent if already else base/'completed'/'user-confirmed-20261117'/ident[:20]
                    parts=[]
                    for kind,path in [('caption',video.with_suffix('.txt')),('comment',video.with_suffix('.comment.txt')),('video',video)]:
                        if not path.exists() and not path.is_symlink():continue
                        safe(root,path);meta=fingerprint if kind=='video' else info(root,path)[0]
                        source=str(path.relative_to(root));destination=destinations.setdefault(source,str((destdir/path.name).relative_to(root)))
                        parts.append(dict(kind=kind,source=source,destination=destination,**meta))
                    bindings=[];issues=[]
                    for owner,key in keys.items():
                        existing=state.get(key)
                        if existing is None:continue
                        if (existing.get('account'),existing.get('target'))!=pair or upload.target_key(existing.get('url',''))!=owner:
                            issues.append('原任务指纹存在其他目标映射，未改该记录');continue
                        bindings.append(dict(key=key,url=existing['url']))
                    current=registered.get(pair,{})
                    if not bindings and len(current)==1:
                        owner,url=next(iter(current.items()));key=keys[owner]
                        if key not in state:bindings.append(dict(key=key,url=url))
                    if not rows or len(rows)%10==0:print('已核对视频：',len(rows)+1,'；当前',account+'/'+base.name,name,flush=True)
                    rows.append(dict(id=ident,account=account,target=base.name,filename=name,already_archived=already,
                                     files=parts,bindings=bindings,binding_note='；'.join(issues) or ('' if bindings else '未取得唯一登记身份；仅记录本地用户确认成功，不猜测发布身份')))
    return sorted(rows,key=lambda r:(r['account'],r['target'],next(f['source'] for f in r['files'] if f['kind']=='video')))


def checked_plan(root,path):
    value=upload.read_json(safe(root,path),{});p=value.get('payload',{})
    if value.get('sha256')!=digest(p) or p.get('schema')!=SCHEMA or p.get('confirmation_method')!=METHOD or p.get('user_confirmed') is not True:raise ValueError('原归档清单校验失败，未重新扫描或重排。')
    ids=set()
    for row in p['rows']:
        if row['id'] in ids or not pair_ok(row['account'],row['target']):raise ValueError('归档清单有重复或范围外条目。')
        ids.add(row['id']);prefix=('videos',row['account'],row['target'])
        for f in row['files']:
            source=safe(root,root/f['source']);destination=safe(root,root/f['destination'])
            if source.relative_to(root).parts[:3]!=prefix or destination.relative_to(root).parts[:4]!=(*prefix,'completed'):raise ValueError('原归档路径超出账号完成目录。')
            if not re.fullmatch('[a-f0-9]{64}',f['sha256']) or type(f['size']) is not int:raise ValueError('归档文件指纹异常。')
        for b in row['bindings']:
            if not re.fullmatch('[a-f0-9]{64}',b['key']):raise ValueError('原视频任务指纹异常。')
            upload.target_key(b['url'])
    return value


def prepare(root):
    path=safe(root,root/JOURNAL)
    if path.exists():return path,checked_plan(root,path)
    state_path=safe(root,root/'logs/publish_state.json');state=upload.read_json(state_path,{})
    if not isinstance(state,dict):raise ValueError('原发布记录格式异常。')
    print('正在逐文件核对fb01–fb74及公共主页的视频；包含新素材、fb23和暂停使用的账号。',flush=True)
    rows=scan(root,state);stamp=now();payload=dict(schema=SCHEMA,confirmation_method=METHOD,user_confirmed=True,scope='all-existing-media-fb01-through-fb74-and-pages',snapshot_at=stamp,rows=rows)
    value=dict(payload=payload,sha256=digest(payload));backup=root/'backups'/('user-confirmed-all74-'+value['sha256'][:16]);safe(root,backup);backup.mkdir(parents=True,exist_ok=False)
    for relative in ('logs/publish_state.json',LEDGER):
        original=safe(root,root/relative)
        if original.is_file():shutil.copy2(original,backup/original.name)
    upload.save_json(backup/'archive-plan.json',value);value['backup']=str(backup.relative_to(root));upload.save_json(path,value)
    print('已冻结本次范围：',len(rows),'个视频；只处理这份清单，之后新增视频不纳入。备份：',backup,flush=True)
    return path,checked_plan(root,path)


def move_exact(root,f):
    source=safe(root,root/f['source']);destination=safe(root,root/f['destination']);expected={k:f[k] for k in ('size','sha256')}
    if destination.exists():
        if info(root,destination)[0]!=expected:raise ValueError('归档位置已有不同文件，未覆盖。')
        if source!=destination and source.exists():
            if os.path.samefile(source,destination):source.unlink()
            else:raise ValueError('原位置及归档位置同时有文件，保留两份。')
        return
    if not source.is_file() or info(root,source)[0]!=expected:raise ValueError('原文件缺失或已变化，未移动其他内容。')
    destination.parent.mkdir(parents=True,exist_ok=True);safe(root,destination)
    if os.name=='nt':source.rename(destination)
    else:os.link(source,destination);source.unlink()
    if info(root,destination)[0]!=expected:raise ValueError('归档后文件指纹异常。')


def mark_row(root,row,value):
    state_path=safe(root,root/'logs/publish_state.json');state=upload.read_json(state_path,{})
    before=copy.deepcopy(state);stamp=now();video=next(f for f in row['files'] if f['kind']=='video')
    for binding in row['bindings']:
        old=state.get(binding['key']);pair=(row['account'],row['target'])
        if old is not None and ((old.get('account'),old.get('target'))!=pair or upload.target_key(old.get('url',''))!=upload.target_key(binding['url'])):raise ValueError('任务登记身份后来变化，未覆盖该记录。')
        record=state.setdefault(binding['key'],dict(account=pair[0],target=pair[1],url=binding['url'],video=str(root/video['source']),created=stamp))
        if record.get('status')!='published':
            record.update(status_before_user_confirmation=record.get('status','not_started'),error_before_user_confirmation=record.get('error',''),review_reason_before_user_confirmation=record.get('review_reason',''),
                          status='published',confirmation_method=METHOD,confirmed_at=stamp,error='',review_reason='')
        record.setdefault('user_confirmation_archive',dict(method=METHOD,plan_sha256=value['sha256'],confirmed_at=stamp))
        record.update(archived_video=str(root/video['destination']))
        if not row['already_archived']:record.setdefault('archived_at',stamp)
        for f in row['files']:
            if f['kind']=='caption':record['archived_caption']=str(root/f['destination'])
    if upload.read_json(state_path,{})!=before:raise ValueError('标记前发布状态发生变化，原记录未覆盖。')
    if state!=before:upload.save_json(state_path,state)
    ledger_path=safe(root,root/LEDGER);ledger=upload.read_json(ledger_path,dict(schema='user-confirmed-archived-media-v1',rows={}))
    if ledger.get('schema')!='user-confirmed-archived-media-v1' or not isinstance(ledger.get('rows'),dict):raise ValueError('用户确认归档台账异常。')
    ledger['rows'].setdefault(row['id'],dict(account=row['account'],target=row['target'],filename=row['filename'],status='published',confirmation_method=METHOD,confirmed_at=stamp,
        archive_video=video['destination'],video_sha256=video['sha256'],video_size=video['size'],plan_sha256=value['sha256'],state_keys=[b['key'] for b in row['bindings']],binding_note=row['binding_note']))
    upload.save_json(ledger_path,ledger)


def inspect_workers(root):
    with patch.object(workers,'BOOTSTRAP',BOOTSTRAP):return workers.active_workers(root,Path(__file__).resolve())


def apply(root):
    with locked():
        ledger=upload.read_json(safe(root,root/LEDGER),dict(schema='user-confirmed-archived-media-v1',rows={}))
        if ledger.get('schema')!='user-confirmed-archived-media-v1' or not isinstance(ledger.get('rows'),dict):raise ValueError('用户确认归档台账异常，未移动视频。')
        if not isinstance(upload.read_json(safe(root,root/'logs/publish_state.json'),{}),dict):raise ValueError('原发布状态格式异常。')
        path,value=prepare(root);progress_path=path.with_name(path.stem+'-progress.json');progress=upload.read_json(progress_path,dict(sha256=value['sha256'],rows={}))
        if progress.get('sha256')!=value['sha256'] or not isinstance(progress.get('rows'),dict) or not set(progress['rows'])<={r['id'] for r in value['payload']['rows']}:raise ValueError('原归档进度异常，未重置。')
        for row in value['payload']['rows']:
            if progress['rows'].get(row['id'],{}).get('status')=='completed':continue
            try:
                # Check all files before moving a companion or changing state.
                for f in row['files']:
                    current=root/f['source'] if (root/f['source']).exists() else root/f['destination']
                    if info(root,current)[0]!={k:f[k] for k in ('size','sha256')}:raise ValueError('原素材变化，未标记成功。')
                for f in row['files']:move_exact(root,f)
                mark_row(root,row,value)
                progress['rows'][row['id']]=dict(status='completed',updated_at=now())
                print(row['account']+'/'+row['target'],row['filename'],'已归档，已标记用户确认发布成功',flush=True)
            except Exception as error:
                progress['rows'][row['id']]=dict(status='error',error=str(error) or type(error).__name__,updated_at=now())
                print('本文件保留进度，需检查：',row['account'],row['target'],row['filename'],str(error),flush=True)
            finally:upload.save_json(progress_path,progress)
        completed=sum(r.get('status')=='completed' for r in progress['rows'].values());total=len(value['payload']['rows'])
        progress.update(complete=completed==total,updated_at=now());upload.save_json(progress_path,progress)
        lines=['用户确认视频发布成功并归档：'+str(completed)+'/'+str(total),'确认来源：用户明确要求全部标记为已发布成功；没有生成平台回执或虚构视频链接。','备份：'+str(root/value['backup']),'视频和配套文本保留；评论状态未改动；程序、登录资料和素材总目录未改动。']
        for row in value['payload']['rows']:
            item=progress['rows'].get(row['id'],{});video=next(f for f in row['files'] if f['kind']=='video')
            lines.append(row['account']+'/'+row['target']+' '+row['filename']+' '+item.get('status','not_started')+' -> '+video['destination']+('；'+row['binding_note'] if row['binding_note'] else '')+('；'+item['error'] if item.get('error') else ''))
        report=path.with_suffix('.txt');report.write_text('\n'.join(lines),encoding='utf-8-sig')
        print('本次已归档并标记用户确认成功：',completed,'/',total,'；待处理：',total-completed,'；完整清单：',report,flush=True)
        print('没有上传、打开浏览器或发送评论。原视频及文本均保留在各账号completed目录；原状态已备份。',flush=True)
        return 0 if progress['complete'] else 3


def execute(root):
    root=Path(root).resolve()
    if root!=upload.ROOT.resolve():raise ValueError('请在原Windows上传目录运行。')
    while True:
        live=inspect_workers(root)
        if live:
            print('先等待正在运行的发布、评论或分配任务结束，未改动文件。PID：',','.join(str(r['pid']) for r in live),'；15秒后检查。',flush=True);time.sleep(15);continue
        try:recovery.recover_locks(root);return apply(root)
        except RuntimeError as error:
            if not any(t in str(error) for t in ('仍有上传任务或遗留锁','锁内进程仍在运行')):raise
            print('原任务仍在收尾，15秒后检查；没有结束进程。',flush=True);time.sleep(15)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的新PowerShell窗口运行。')
        raise SystemExit(execute(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停，保留逐文件归档及成功标记进度；重跑同一入口继续，之后新增素材不纳入本次清单。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
