"""Archive only frozen Nov12 bytes; preserve statuses, comments and Nov13 assignments."""
import copy,hashlib,os,re,shutil,sys,uuid
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
from add_fb_accounts import locked

DAY='2026-11-12'
TODAY='2026-11-13'
SCOPE='nov12-current-materials-fb01-to-fb24-v1'
SCHEMA='archive-frozen-nov12-materials-v1'
JOURNAL='archive-nov12-materials-on-20261113.json'
LABELS={'moved':'本次已归档','already':'原已归档','today':'今天素材保留','changed':'同名新素材保留',
        'missing':'原素材未找到','blocked':'记录需核实','error':'归档未完成'}


def checked_json(path):
    value=upload.read_json(path,{})
    if value.get('sha256')!=batch.digest(value.get('payload',{})):raise ValueError('原清单校验失败：'+path.name)
    return value


def safe(path):
    path=Path(path)
    path.resolve().relative_to(upload.ROOT.resolve())
    for part in (path,*path.parents):
        if part==upload.ROOT:break
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):raise ValueError('归档路径包含文件链接，未移动。')
    return path


def info(path):
    path=safe(path);before=path.stat();h=hashlib.sha256()
    with path.open('rb') as reader:
        for chunk in iter(lambda:reader.read(1024*1024),b''):h.update(chunk)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('文件仍在变化，未移动：'+path.name)
    return dict(size=after.st_size,sha256=h.hexdigest())


def pair_ok(account,target):
    return bool(re.fullmatch(r'fb(?:0[1-9]|1[0-9]|2[0-4])',str(account)) and re.fullmatch(r'personal|page[0-9]{2,}',str(target)))


def source():
    control_path=upload.ROOT/'logs/nov12-current-materials-original-accounts.json'
    control=checked_json(control_path);payload=control['payload']
    if payload.get('scope')!=SCOPE or payload.get('date')!=DAY:raise ValueError('没有找到11月12日原批次，未按文件修改日期猜选。')
    records={}
    for record in payload.get('records',[]):
        account,target,filename=record.get('account'),record.get('target'),record.get('filename')
        upload.validate_video_filename(filename)
        if (not pair_ok(account,target) or not re.fullmatch(r'[a-f0-9]{64}',str(record.get('video_sha256','')))
                or not isinstance(record.get('size'),int) or record['size']<=0):raise ValueError('原素材快照条目异常。')
        pair=(account,target,filename)
        if pair in records:raise ValueError('原素材快照有重复条目。')
        records[pair]=copy.deepcopy(record)
    if not records:raise ValueError('原素材快照为空。')
    jobs={};bindings=[]
    for path in sorted((upload.ROOT/'logs').glob('frozen-material-'+DAY+'-*.json')):
        raw=upload.read_json(path,{})
        if raw.get('payload',{}).get('current_material_scope')!=SCOPE:continue
        value=checked_json(path);original=value['payload']
        if (not re.fullmatch('frozen-material-'+DAY+'-'+value['sha256'][:16]+r'\.json',path.name)
                or original.get('date')!=DAY or original.get('current_snapshot_sha256')!=control['sha256']):raise ValueError('原冻结清单与素材快照不一致。')
        bindings.append(dict(manifest=path.name,sha256=value['sha256']))
        for job in original.get('jobs',[]):
            pair=(job['account'],job['target'],job['filename']);record=records.get(pair)
            if (not record or job.get('video_sha256')!=record['video_sha256'] or job.get('video_size')!=record['size']
                    or not re.fullmatch(r'[a-f0-9]{64}',str(job.get('key','')))):raise ValueError('冻结视频不属于原快照。')
            if pair in jobs and jobs[pair]!=job:raise ValueError('原冻结任务出现冲突。')
            jobs[pair]=job
    return records,jobs,dict(controller_sha256=control['sha256'],plans=bindings)


def today_files():
    protected=set()
    folder=upload.ROOT/'logs/material-distribution'
    for path in folder.glob('*/*.json'):
        if not re.fullmatch(TODAY+r'(?:-reserved50)?\.json',path.name):continue
        value=checked_json(path);payload=value['payload']
        if payload.get('date')!=TODAY or payload.get('schema')!='one-video-per-target-distribution-v1':raise ValueError('今天素材分配清单异常，未移动视频。')
        for row in payload.get('assignments',[]):
            account,target=row.get('account',''),row.get('target','')
            if not re.fullmatch(r'fb[0-9]+',account) or not re.fullmatch(r'personal|page[0-9]{2,}',target):raise ValueError('今天分配目标格式异常。')
            for file in row.get('files',[]):
                name=file.get('destination_name','')
                if not name or '/' in name or '\\' in name or name in {'.','..'}:raise ValueError('今天分配文件路径异常。')
                protected.add(str(safe(upload.ROOT/'videos'/account/target/'inbox'/name)).casefold())
    return protected


def relative(path):return str(Path(path).relative_to(upload.ROOT))


def prepare(records,jobs,origin,state):
    path=upload.ROOT/'logs'/JOURNAL
    if path.exists():
        value=checked_json(path)
        if (value['payload'].get('schema')!=SCHEMA or value['payload'].get('origin')!=origin
                or value['payload'].get('records_sha256')!=batch.digest(list(records.values()))):raise ValueError('原归档范围变化，未另建或重排。')
        return path,value
    protected=today_files();rows=[]
    for pair,record in sorted(records.items()):
        account,target,filename=pair;job=jobs.get(pair,{})
        row=state.get(job.get('key'),{})
        base=safe(upload.ROOT/'videos'/account/target);video=safe(base/'inbox'/filename)
        ident=batch.digest(record);entry=dict(record,id=ident,key=job.get('key'),url=job.get('url'),status_before=row.get('status','not_started'),files=[])
        if row and ((row.get('account'),row.get('target'))!=(account,target) or upload.target_key(row.get('url',''))!=upload.target_key(job.get('url',''))):
            entry.update(action='blocked',reason='任务身份与原视频不一致')
        elif video.is_file():
            if str(video).casefold() in protected:entry.update(action='today',reason='同路径属于今天的分配清单，保留')
            elif info(video)!=dict(size=record['size'],sha256=record['video_sha256']):entry.update(action='changed',reason='同名文件内容已变化，保留新素材')
            else:
                destination=safe(base/('completed' if row.get('status')=='published' else 'archive')/DAY/ident[:16])
                if destination.exists():destination=destination.with_name(ident[:16]+'-'+uuid.uuid4().hex[:8])
                caption=video.with_suffix('.txt')
                if caption.is_file() and job.get('caption_sha256') and str(caption).casefold() not in protected:
                    text_info=info(caption)
                    if text_info['sha256']==job['caption_sha256']:
                        entry['files'].append(dict(source=relative(caption),destination=relative(destination/caption.name),kind='caption',**text_info))
                entry['files'].append(dict(source=relative(video),destination=relative(destination/video.name),kind='video',size=record['size'],sha256=record['video_sha256']))
                entry['action']='move'
        else:
            found=None
            for folder in (base/'completed',base/'archive'/DAY):
                if not folder.is_dir():continue
                for candidate in sorted(folder.rglob(filename)):
                    if candidate.is_file() and info(candidate)==dict(size=record['size'],sha256=record['video_sha256']):found=candidate;break
                if found:break
            entry.update(action='already' if found else 'missing',existing_archive=relative(found) if found else '',reason='' if found else '原视频已不在inbox，且未找到指纹一致的归档')
        rows.append(entry)
    payload=dict(schema=SCHEMA,date=DAY,origin=origin,records_sha256=batch.digest(list(records.values())),rows=rows)
    value=dict(payload=payload,sha256=batch.digest(payload),created_at=datetime.now(timezone.utc).isoformat())
    backup=upload.ROOT/'backups'/('archive-nov12-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
    state_path=upload.ROOT/'logs/publish_state.json'
    if state_path.is_file():shutil.copy2(state_path,backup/state_path.name)
    upload.save_json(backup/'archive-plan.json',value)
    value['backup']=str(backup);upload.save_json(path,value)
    return path,value


def move_exact(item):
    source=safe(upload.ROOT/item['source']);destination=safe(upload.ROOT/item['destination'])
    expected=dict(size=item['size'],sha256=item['sha256'])
    if destination.exists():
        if info(destination)!=expected:raise ValueError('归档目标已有不同文件，未覆盖。')
        if source.exists():
            if os.path.samefile(source,destination):source.unlink()
            else:raise ValueError('原位置和归档位置同时有文件，保留两份，未覆盖或删除。')
        return
    if not source.is_file() or info(source)!=expected:raise ValueError('原素材缺失或变化，未移动其他文件。')
    destination.parent.mkdir(parents=True,exist_ok=True);safe(destination)
    if os.name=='nt':source.rename(destination)
    else:os.link(source,destination);source.unlink()
    if info(destination)!=expected:raise ValueError('归档后文件校验异常，请检查归档位置。')


def execute():
    with locked():
        records,jobs,origin=source();state_path=upload.ROOT/'logs/publish_state.json'
        path,value=prepare(records,jobs,origin,upload.read_json(state_path,{}))
        progress_path=path.with_name(path.stem+'-progress.json')
        progress=upload.read_json(progress_path,dict(sha256=value['sha256'],rows={}))
        if progress.get('sha256')!=value['sha256'] or not isinstance(progress.get('rows'),dict):raise ValueError('归档进度校验失败，未重置。')
        try:
            for entry in value['payload']['rows']:
                ident=entry['id']
                if progress['rows'].get(ident,{}).get('result')=='moved':continue
                result=dict(account=entry['account'],target=entry['target'],filename=entry['filename'],result=entry['action'],reason=entry.get('reason',''))
                try:
                    if entry['action']=='move':
                        protected=today_files()
                        if any(str(safe(upload.ROOT/i['source'])).casefold() in protected for i in entry['files']):raise ValueError('该路径后来加入今天的分配清单，保留不移动。')
                        for item in entry['files']:move_exact(item)
                        current=upload.read_json(state_path,{})
                        row=current.get(entry.get('key'))
                        if row is not None:
                            if ((row.get('account'),row.get('target'))!=(entry['account'],entry['target'])
                                    or upload.target_key(row.get('url',''))!=upload.target_key(entry['url'])):raise ValueError('归档后任务身份变化，未覆盖状态。')
                            fields={'video':'archived_video' if row.get('status')=='published' else 'material_archive_video',
                                    'caption':'archived_caption' if row.get('status')=='published' else 'material_archive_caption'}
                            for item in entry['files']:row[fields[item['kind']]]=str(upload.ROOT/item['destination'])
                            row['material_archive_date']=DAY
                            upload.save_json(state_path,current)
                        result.update(result='moved',archive_video=next(i['destination'] for i in entry['files'] if i['kind']=='video'))
                    progress['rows'][ident]=result
                    print(entry['account']+'/'+entry['target'],entry['filename'],LABELS.get(result['result'],result['result']),result['reason'],
                          result.get('archive_video') or entry.get('existing_archive',''),flush=True)
                except Exception as error:
                    result.update(result='error',reason=str(error) or type(error).__name__);progress['rows'][ident]=result
                    print('保留记录，归档需检查：',entry['account'],entry['target'],result['reason'],flush=True)
                finally:upload.save_json(progress_path,progress)
        finally:
            counts=Counter(row['result'] for row in progress['rows'].values())
            print('11月12日素材归档结果：', '；'.join(LABELS.get(k,k)+' '+str(v)+'条' for k,v in counts.items()),flush=True)
            print('原状态备份：',value.get('backup','见首次归档记录'),'；逐条清单：',progress_path,flush=True)
            print('发布成功/失败/待核实状态、评论记录及今天分配素材均保留；没有上传或发送评论。',flush=True)
    return 3 if any(counts[k] for k in ('error','missing','blocked','today','changed')) else 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已暂停，保留归档进度；重跑同一指令继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
