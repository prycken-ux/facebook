"""Archive proven historical account media through Nov19; protect current/future material."""
import copy,os,re,shutil,sys,uuid
from datetime import datetime,date,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parent))
import archive_all_user_confirmed_20261117 as base

VERSION='1.0-historical-through-nov19-protect-nov20-onward'
CUTOFF='2026-11-19'
TODAY='2026-11-20'
SCHEMA='historical-video-archive-through-nov19-v1'
JOURNAL='logs/historical-video-archive-through-20261119.json'
METHOD='user_confirmed_nov19_success_archive_history_20261120'
BJ=timezone(timedelta(hours=8))
BOOTSTRAP=re.compile(base.workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_archive_history_through_20261119').replace('verified-first24-material-distribution','verified-historical-archive-through-nov19'))


def file_name(value):return str(value or '').replace(chr(92),'/').rsplit('/',1)[-1]


def day(value):
    try:
        if not isinstance(value,str):return None
        return date.fromisoformat(value).isoformat()
    except ValueError:return None


def documents(root):
    result={}
    for path in (root/'logs').glob('*.json'):
        if not re.fullmatch(r'(?:frozen-material|automatic-retry)-\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json',path.name):continue
        value=base.upload.read_json(base.safe(root,path),{});p=value.get('payload',{})
        if value.get('sha256')!=base.digest(p) or not path.stem.endswith(value['sha256'][:16]):raise ValueError('原发布清单指纹异常，未归档：'+path.name)
        result[path.name]=value
    return result


def provenance(root,state):
    docs=documents(root);memo={}
    def origin(name,seen=()):
        if name in memo:return memo[name]
        if name in seen:raise ValueError('原清单来源循环，未归档。')
        p=docs.get(name,{}).get('payload',{});explicit=day(p.get('material_source_date') or p.get('material_date'))
        if explicit:found={explicit}
        else:
            parents=[b.get('manifest') for b in p.get('source_bindings',[]) if isinstance(b,dict)]
            if p.get('source_manifest'):parents.append(p['source_manifest'])
            for binding in p.get('source_bindings',[]):
                if isinstance(binding,dict) and binding.get('manifest') in docs and binding.get('sha256') not in (None,docs[binding['manifest']]['sha256']):raise ValueError('原归档来源父清单指纹不符。')
            if p.get('source_manifest') in docs and p.get('source_sha256') not in (None,docs[p['source_manifest']]['sha256']):raise ValueError('自动补发父清单指纹不符。')
            found=set().union(*(origin(n,(*seen,name)) for n in parents if n in docs)) if parents else set()
            if not found and day(p.get('date')):found={p['date']}
        memo[name]=found;return found
    indexed={};protected=set()
    for name,value in docs.items():
        days=origin(name)
        for job in value['payload'].get('jobs',[]):
            pair=job.get('account'),job.get('target');key=job.get('key');filename=job.get('filename')
            if not base.pair_ok(*pair) or not re.fullmatch('[a-f0-9]{64}',str(key)) or not filename or Path(filename).name!=filename:continue
            try:owner=base.upload.target_key(job['url'])
            except (ValueError,KeyError,TypeError):continue
            indexed.setdefault((*pair,filename,key),[]).extend(dict(date=d,owner=owner,source=name) for d in sorted(days))
            if any(d>CUTOFF for d in days):
                for p in (root/'videos'/pair[0]/pair[1]/'inbox'/filename,root/'videos'/pair[0]/pair[1]/'scheduled'/min(days)/'inbox'/filename):protected.add(str(p).casefold())
    for path in (root/'logs/material-distribution').glob('*/*.json'):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:-reserved50|-eligible78|-eligible62|-eligible60)?\.json',path.name):continue
        value=base.upload.read_json(base.safe(root,path),{});p=value.get('payload',{})
        if value.get('sha256')!=base.digest(p):raise ValueError('原素材分配指纹异常，未归档。')
        if day(p.get('date')):
            for row in p.get('assignments',[]):
                if not base.pair_ok(row.get('account'),row.get('target')) or not row.get('files'):continue
                video=row['files'][-1]
                if re.fullmatch('[a-f0-9]{64}',str(video.get('sha256',''))):
                    for name in {video.get('name'),video.get('destination_name')}:
                        if name and Path(name).name==name:indexed.setdefault((row['account'],row['target'],name,'sha:'+video['sha256']),[]).append(dict(date=p['date'],owner=None,source='verified_distribution:'+path.name))
        if day(p.get('date')) and p['date']>CUTOFF:
            for row in p.get('assignments',[]):
                if not base.pair_ok(row.get('account'),row.get('target')):continue
                for f in row.get('files',[]):
                    name=f.get('destination_name','')
                    if name and Path(name).name==name:protected.add(str(root/'videos'/row['account']/row['target']/'inbox'/name).casefold())
    return indexed,protected


def scheduled_date(base_dir,path):
    parts=path.relative_to(base_dir).parts
    return day(parts[1]) if len(parts)>1 and parts[0]=='scheduled' else None


def scan(root,state):
    _,known=base.owner_index(root,state);indexed,protected=provenance(root,state);rows=[];review=[]
    videos=base.safe(root,root/'videos')
    if not videos.is_dir():return rows,review
    for account_dir in sorted(videos.iterdir()):
        if account_dir.name not in base.ACCOUNTS:continue
        base.safe(root,account_dir)
        if not account_dir.is_dir():continue
        for target_dir in sorted(account_dir.iterdir()):
            pair=account_dir.name,target_dir.name
            if not base.pair_ok(*pair):continue
            base.safe(root,target_dir)
            if not target_dir.is_dir():continue
            owners=known.get(pair,{})
            for folder,dirs,files in os.walk(target_dir,followlinks=False):
                folder=base.safe(root,Path(folder));planned=scheduled_date(target_dir,folder)
                if planned and planned>CUTOFF:dirs[:]=[];continue
                for name in list(dirs):
                    candidate=folder/name
                    # Future scheduled trees are protected even without a publication manifest.
                    d=scheduled_date(target_dir,candidate)
                    if d and d>CUTOFF:dirs.remove(name);continue
                    base.safe(root,candidate)
                for name in sorted(files):
                    video=folder/name
                    if video.suffix.lower() not in base.EXTENSIONS:continue
                    if str(video).casefold() in protected:continue
                    prefix=re.match(r'^(\d{8})-[a-f0-9]{8}-(?:eligible60|weekend60)-',name)
                    if prefix and prefix[1]>CUTOFF.replace('-',''):continue
                    fingerprint,keys=base.info(root,video,owners)
                    evidence=list(indexed.get((*pair,name,'sha:'+fingerprint['sha256']),[]));bindings=[]
                    for owner,key in keys.items():
                        for proof in indexed.get((*pair,name,key),[]):
                            if proof['owner']==owner:evidence.append(proof)
                        record=state.get(key)
                        if record and (record.get('account'),record.get('target'))==pair and base.upload.target_key(record.get('url',''))==owner:
                            names=[file_name(record.get('video') or record.get('archived_video'))]
                            if name in names:
                                bindings.append(dict(key=key,url=record['url']))
                                try:stamp=datetime.fromisoformat(record.get('created','')).astimezone(BJ).date().isoformat()
                                except (TypeError,ValueError):stamp=None
                                if stamp and stamp<=CUTOFF:evidence.append(dict(date=stamp,owner=owner,source='historical_record_created_only'))
                    dates={e['date'] for e in evidence if e['date']<=CUTOFF}
                    if planned and planned<=CUTOFF:dates.add(planned)
                    already=video.relative_to(target_dir).parts[0] in {'completed','archive'}
                    if not dates:
                        if not already:review.append(dict(account=pair[0],target=pair[1],filename=name,reason='没有11月19日及以前的可靠来源，保留不猜选'))
                        continue
                    # A later record for the same path wins over historical provenance.
                    if any(e['date']>CUTOFF for e in evidence):continue
                    confirmed19=any(e['date']==CUTOFF and e['source']!='historical_record_created_only' for e in evidence) or planned==CUTOFF
                    ident=base.digest(dict(account=pair[0],target=pair[1],source=str(video.relative_to(root)),**fingerprint))
                    destdir=video.parent if already else target_dir/'completed'/'history-through-20261119'/ident[:20]
                    parts=[]
                    for kind,path in [('caption',video.with_suffix('.txt')),('comment',video.with_suffix('.comment.txt')),('video',video)]:
                        if not path.exists() and not path.is_symlink():continue
                        if str(path).casefold() in protected:continue
                        meta=fingerprint if kind=='video' else base.info(root,path)[0]
                        parts.append(dict(kind=kind,source=str(path.relative_to(root)),destination=str((destdir/path.name).relative_to(root)),**meta))
                    rows.append(dict(id=ident,account=pair[0],target=pair[1],filename=name,already_archived=already,user_confirmed_nov19=confirmed19,origin_dates=sorted(dates),files=parts,bindings=bindings))
    return rows,review


def validate(root,path):
    value=base.upload.read_json(base.safe(root,path),{});p=value.get('payload',{})
    if value.get('sha256')!=base.digest(p) or p.get('schema')!=SCHEMA or p.get('cutoff')!=CUTOFF or p.get('user_confirmed_nov19') is not True:raise ValueError('原历史归档清单异常。')
    ids=set()
    for row in p['rows']:
        if row['id'] in ids or not base.pair_ok(row['account'],row['target']) or not row['origin_dates'] or any(d>CUTOFF for d in row['origin_dates']):raise ValueError('归档清单包含重复或今天/未来素材。')
        ids.add(row['id']);prefix=('videos',row['account'],row['target'])
        for f in row['files']:
            source=base.safe(root,root/f['source']);dest=base.safe(root,root/f['destination'])
            if source.relative_to(root).parts[:3]!=prefix or dest.relative_to(root).parts[:3]!=prefix:raise ValueError('归档路径超出原账号。')
            planned=scheduled_date(root.joinpath(*prefix),source)
            if planned and planned>CUTOFF:raise ValueError('未来待发目录不得归档。')
            if source!=dest and dest.relative_to(root).parts[3]!='completed':raise ValueError('归档目标不是原账号completed。')
    return value


def prepare(root):
    path=base.safe(root,root/JOURNAL)
    if path.exists():return path,validate(root,path)
    state=base.upload.read_json(base.safe(root,root/'logs/publish_state.json'),{})
    rows,review=scan(root,state);p=dict(schema=SCHEMA,cutoff=CUTOFF,user_confirmed_nov19=True,created_at=base.now(),rows=rows,retained_for_review=review)
    value=dict(payload=p,sha256=base.digest(p));backup=base.safe(root,root/'backups'/('archive-history-through-nov19-'+value['sha256'][:16]));backup.mkdir(parents=True,exist_ok=False)
    for relative in ('logs/publish_state.json','logs/user_confirmed_archived_media.json'):
        source=base.safe(root,root/relative)
        if source.is_file():shutil.copy2(source,backup/source.name)
    base.upload.save_json(backup/'archive-plan.json',value);value['backup']=str(backup.relative_to(root));base.upload.save_json(path,value)
    print('已冻结11月19日及以前',len(rows),'份历史视频；来源不明保留',len(review),'份；今天及未来素材不纳入。',flush=True)
    return path,validate(root,path)


def mark(root,row,value):
    path=base.safe(root,root/'logs/publish_state.json');state=base.upload.read_json(path,{});before=copy.deepcopy(state);stamp=base.now();video=next(f for f in row['files'] if f['kind']=='video')
    for binding in row['bindings']:
        record=state.get(binding['key'])
        if not record or (record.get('account'),record.get('target'))!=(row['account'],row['target']) or base.upload.target_key(record.get('url',''))!=base.upload.target_key(binding['url']) or file_name(record.get('video') or record.get('archived_video'))!=row['filename']:raise ValueError('原任务归属或素材后来变化，未标记。')
        record.setdefault('publication_status_before_user_archive',record.get('status','unknown'))
        if row['user_confirmed_nov19'] and record.get('status')!='published':
            record.update(status_before_user_confirmation=record.get('status'),error_before_user_confirmation=record.get('error',''),status='published',confirmation_method=METHOD,confirmed_at=stamp,error='',review_reason_before_user_confirmation=record.get('review_reason',''),review_reason='')
        elif not row['user_confirmed_nov19'] and record.get('status')!='published':record['status']='archived'
        record.update(archive_status='archived',archived_video=str(root/video['destination']),archive_cutoff=CUTOFF)
        record.setdefault('archived_at',stamp)
        for f in row['files']:
            if f['kind']=='caption':record['archived_caption']=str(root/f['destination'])
    if base.upload.read_json(path,{})!=before:raise ValueError('归档登记期间状态变化，未覆盖。')
    if state!=before:base.upload.save_json(path,state)


def apply(root):
    with base.locked():
        path,value=prepare(root);progress_path=path.with_name(path.stem+'-progress.json');progress=base.upload.read_json(progress_path,dict(sha256=value['sha256'],rows={}))
        if progress.get('sha256')!=value['sha256'] or not isinstance(progress.get('rows'),dict) or not set(progress['rows'])<={r['id'] for r in value['payload']['rows']}:raise ValueError('历史归档进度异常。')
        for row in value['payload']['rows']:
            if progress['rows'].get(row['id'],{}).get('status')=='completed':continue
            try:
                for f in row['files']:
                    current=root/f['source'] if (root/f['source']).exists() else root/f['destination']
                    if base.info(root,current)[0]!={k:f[k] for k in ('size','sha256')}:raise ValueError('原视频或配套文本变化，保留不移动。')
                # Re-check newly frozen current/future path bindings before every move.
                state=base.upload.read_json(root/'logs/publish_state.json',{});_,protected=provenance(root,state)
                if any(str(root/f['source']).casefold() in protected for f in row['files']):raise ValueError('此路径后来属于今天/未来素材，保留不归档。')
                for f in row['files']:base.move_exact(root,f)
                mark(root,row,value);progress['rows'][row['id']]=dict(status='completed',updated_at=base.now())
                print(row['account']+'/'+row['target'],row['filename'],'已归档；'+('用户确认11月19日已发布成功' if row['user_confirmed_nov19'] else '保留原发布结果，旧任务已归档'),flush=True)
            except KeyboardInterrupt:raise
            except Exception as error:
                progress['rows'][row['id']]=dict(status='error',error=str(error),updated_at=base.now());print('此历史文件保留待处理：',row['account'],row['filename'],str(error),flush=True)
            finally:base.upload.save_json(progress_path,progress)
        completed=sum(r.get('status')=='completed' for r in progress['rows'].values());total=len(value['payload']['rows'])
        progress.update(complete=completed==total,updated_at=base.now());base.upload.save_json(progress_path,progress)
        report=path.with_suffix('.txt');report.write_text('\n'.join(['11月19日及以前历史视频归档：'+str(completed)+'/'+str(total),'原视频及配套文本保留；今天和周末素材、程序、登录资料、评论结果不改动。','原状态备份：'+str(root/value['backup'])]+[r['account']+'/'+r['target']+' '+r['filename']+' 来源待核对，保留原位' for r in value['payload']['retained_for_review']]),encoding='utf-8-sig')
        print('历史归档完成：',completed,'/',total,'；来源待核对保留：',len(value['payload']['retained_for_review']),'；清单：',report,flush=True)
        return 0 if progress['complete'] else 3


def inspect_workers(root):
    with patch.object(base.workers,'BOOTSTRAP',BOOTSTRAP):return base.workers.active_workers(root,Path(__file__).resolve())


def execute(root):
    root=Path(root).resolve()
    if root!=base.upload.ROOT.resolve():raise ValueError('请在原Windows上传目录运行。')
    # No uploads, comments, Chrome windows or scheduler changes in this entry.
    with patch.object(base,'apply',side_effect=apply),patch.object(base,'inspect_workers',side_effect=inspect_workers):return base.execute(root)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
        raise SystemExit(execute(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停；历史归档进度保留，重跑同一入口续原清单。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
