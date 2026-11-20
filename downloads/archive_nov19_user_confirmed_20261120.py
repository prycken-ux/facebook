"""Archive only the original Nov19 sixty videos on explicit user confirmation."""
import copy,re,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parent))
import archive_all_user_confirmed_20261117 as base

VERSION='1.0-nov19-exact60-user-confirmed-archive-comments-retained'
DAY='2026-11-19'
SOURCE_PREFIX='7702cad3af70ce94'
CONTENT_SHA='ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894'
REQUEST='logs/eligible60-real-publication-request-20261119.json'
CONTROLLER='logs/eligible60-real-publication-'+SOURCE_PREFIX+'.json'
JOURNAL='logs/user-confirmed-nov19-archive-20261120.json'
METHOD='user_confirmed_nov19_videos_published_20261120'
SCHEMA='user-confirmed-exact-nov19-video-archive-v1'
MANUAL_COMMENTS={('fb04','personal'):'https://www.facebook.com/reel/1450837626603440',('fb01','page01'):'https://www.facebook.com/reel/1114161698059872'}
BLOCKED={f'fb{n:02d}' for n in (17,23,25,27,28,29,30,33,34,35,36,38,39,40,41,42,43,44,48,50,53,56,57,58,59,61,64,65,67,69,71,72,73,74)}
EXPECTED={(f'fb{n:02d}','page01' if n in {1,2,5,6,12,13} else 'personal') for n in range(1,75) if f'fb{n:02d}' not in BLOCKED}|{(f'fb{n:02d}',f'page{p:02d}') for n in (9,10) for p in range(1,11)}
BOOTSTRAP=re.compile(base.workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_archive_nov19_user_confirmed_20261120').replace('verified-first24-material-distribution','verified-nov19-user-confirmed-archive'))


def checked(root,relative):
    path=base.safe(root,root/relative);value=base.upload.read_json(path,{})
    if not isinstance(value,dict) or not isinstance(value.get('payload'),dict) or value.get('sha256')!=base.digest(value['payload']):raise ValueError('原11月19日清单指纹异常：'+str(relative))
    return value


def source_jobs(root):
    req=checked(root,REQUEST);p=req['payload']
    if (req['sha256'][:16]!=SOURCE_PREFIX or p.get('schema')!='eligible60-real-publication-request-v1'
            or p.get('material_date')!=DAY or p.get('content_sha256')!=CONTENT_SHA
            or p.get('targets')!=[list(x) for x in sorted(EXPECTED)]):raise ValueError('不是用户确认的11月19日60条原视频批次。')
    controller=base.upload.read_json(base.safe(root,root/CONTROLLER),{})
    if controller.get('request_sha256')!=req['sha256'] or not controller.get('waves'):raise ValueError('缺少原发布进度，不扫描其他日期的视频代替。')
    jobs={}
    for wave in controller['waves']:
        name=wave.get('manifest','')
        if Path(name).name!=name or not re.fullmatch(r'frozen-material-\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json',name):raise ValueError('原冻结文件名异常。')
        value=checked(root,'logs/'+name);q=value['payload']
        if (value['sha256']!=wave.get('sha256') or not name.endswith(value['sha256'][:16]+'.json')
                or q.get('queue_id')!=req['sha256'] or q.get('material_source_date')!=DAY
                or q.get('publication_content_sha256')!=CONTENT_SHA):raise ValueError('原冻结批次不属于11月19日。')
        for job in q.get('jobs',[]):
            pair=job.get('account'),job.get('target')
            if pair not in EXPECTED or pair in jobs or not re.fullmatch(r'20261119-[a-f0-9]{8}-eligible60-[^/\\]+\.mp4',job.get('filename','')):raise ValueError('原视频目标或文件名异常。')
            if any(not re.fullmatch('[a-f0-9]{64}',str(job.get(k,''))) for k in ('key','video_sha256','caption_sha256')) or type(job.get('video_size')) is not int:raise ValueError('原视频指纹缺失。')
            base.upload.target_key(job['url']);jobs[pair]=copy.deepcopy(job)
    if set(jobs)!=EXPECTED:raise ValueError('原60条视频清单不完整，未扫描其他素材。')
    return req,jobs


def snapshot(root,jobs):
    state=base.upload.read_json(base.safe(root,root/'logs/publish_state.json'),{})
    if not isinstance(state,dict):raise ValueError('原发布状态格式异常。')
    rows=[]
    for pair,job in sorted(jobs.items()):
        owner=base.upload.target_key(job['url']);record=state.get(job['key'])
        if record is not None and ((record.get('account'),record.get('target'))!=pair
                or base.upload.target_key(record.get('url',''))!=owner
                or str(record.get('video','')).replace('\\','/').rsplit('/',1)[-1]!=job['filename']):raise ValueError('任务后来变为其他素材，保留不归档：'+pair[0]+'/'+pair[1])
        folder=base.safe(root,root/'videos'/pair[0]/pair[1]);inbox=base.safe(root,folder/'inbox'/job['filename'])
        candidates=[inbox] if inbox.is_file() else []
        completed=base.safe(root,folder/'completed')
        if completed.is_dir():
            candidates += [base.safe(root,p) for p in completed.rglob(job['filename'])]
        candidates=list(dict.fromkeys(candidates))
        if not candidates:raise ValueError('找不到原视频或原归档副本，未改动：'+pair[0]+'/'+pair[1]+' '+job['filename'])
        # Keep every existing exact copy; no duplicate video is deleted.
        for video in candidates:
            fingerprint,keys=base.info(root,video,[owner])
            if fingerprint!=dict(size=job['video_size'],sha256=job['video_sha256']) or keys[owner]!=job['key']:raise ValueError('原视频指纹变化，未移动：'+pair[0])
            ident=base.digest(dict(key=job['key'],source=str(video.relative_to(root)),**fingerprint))
            archived=video.relative_to(folder).parts[0]=='completed'
            destdir=video.parent if archived else folder/'completed'/'user-confirmed-20261119'/ident[:20]
            files=[]
            for kind,path in [('caption',video.with_suffix('.txt')),('comment',video.with_suffix('.comment.txt')),('video',video)]:
                if not path.exists() and not path.is_symlink():continue
                meta=fingerprint if kind=='video' else base.info(root,path)[0]
                if kind=='caption' and meta['sha256']!=job['caption_sha256']:raise ValueError('原视频文案文件已变化，保留不移动：'+pair[0])
                files.append(dict(kind=kind,source=str(path.relative_to(root)),destination=str((destdir/path.name).relative_to(root)),**meta))
            if pair in MANUAL_COMMENTS and record and record.get('permalink') and record['permalink'].rstrip('/')!=MANUAL_COMMENTS[pair].rstrip('/'):
                raise ValueError('用户提供链接与原记录不同，保留待核对：'+pair[0])
            rows.append(dict(id=ident,account=pair[0],target=pair[1],filename=job['filename'],already_archived=archived,files=files,
                             bindings=[dict(key=job['key'],url=job['url'])],binding_note='用户确认11月19日视频已发布；评论状态保留，不生成平台回执'))
    return rows


def validate_plan(root,path,req,jobs):
    value=base.checked_plan(root,path);p=value['payload'];seen=set()
    if (p.get('source_request_sha256')!=req['sha256'] or p.get('scope')!='nov19-exact60-original-videos'
            or p.get('manual_comments')!={a+'/'+t:link for (a,t),link in MANUAL_COMMENTS.items()}):raise ValueError('归档来源异常。')
    for row in p['rows']:
        pair=row['account'],row['target'];job=jobs.get(pair)
        if not job or row['filename']!=job['filename'] or row['bindings']!=[dict(key=job['key'],url=job['url'])]:raise ValueError('归档清单混入其他任务。')
        video=next(f for f in row['files'] if f['kind']=='video')
        if (video['sha256'],video['size'])!=(job['video_sha256'],job['video_size']):raise ValueError('归档视频指纹不符。')
        for f in row['files']:
            source=Path(f['source']);dest=Path(f['destination'])
            expected_name=job['filename'] if f['kind']=='video' else str(Path(job['filename']).with_suffix('.comment.txt' if f['kind']=='comment' else '.txt'))
            if source.name!=expected_name or dest.name!=expected_name or source.parts[3] not in {'inbox','completed'}:raise ValueError('归档路径超出原视频及配套文本。')
        seen.add(pair)
    if seen!=EXPECTED:raise ValueError('归档清单缺少原60个目标。')
    return value


def prepare(root):
    req,jobs=source_jobs(root);path=base.safe(root,root/JOURNAL)
    if path.exists():return path,validate_plan(root,path,req,jobs)
    rows=snapshot(root,jobs);stamp=base.now()
    payload=dict(schema=SCHEMA,confirmation_method=METHOD,user_confirmed=True,scope='nov19-exact60-original-videos',source_request_sha256=req['sha256'],manual_comments={a+'/'+t:link for (a,t),link in MANUAL_COMMENTS.items()},snapshot_at=stamp,rows=rows)
    value=dict(payload=payload,sha256=base.digest(payload));backup=base.safe(root,root/'backups'/('user-confirmed-nov19-'+value['sha256'][:16]));backup.mkdir(parents=True,exist_ok=False)
    for relative in ('logs/publish_state.json',base.LEDGER,REQUEST,CONTROLLER):
        original=base.safe(root,root/relative)
        if original.is_file():shutil.copy2(original,backup/original.name)
    base.upload.save_json(backup/'archive-plan.json',value);value['backup']=str(backup.relative_to(root));base.upload.save_json(path,value)
    print('已冻结11月19日原60个目标，共',len(rows),'份视频文件；今天及周末新素材不纳入。备份：',backup,flush=True)
    return path,validate_plan(root,path,req,jobs)


def inspect_workers(root):
    with patch.object(base.workers,'BOOTSTRAP',BOOTSTRAP):return base.workers.active_workers(root,Path(__file__).resolve())


def mark_with_manual_comments(native,root,row,value):
    native(root,row,value)
    pair=row['account'],row['target']
    if pair not in MANUAL_COMMENTS:return
    state_path=base.safe(root,root/'logs/publish_state.json');state=base.upload.read_json(state_path,{})
    before=copy.deepcopy(state);key=row['bindings'][0]['key'];record=state[key];link=MANUAL_COMMENTS[pair]
    if record.get('permalink') and record['permalink'].rstrip('/')!=link.rstrip('/'):
        raise ValueError('实际记录链接与用户确认不一致，不登记评论。')
    record.setdefault('user_confirmed_manual_comment',dict(permalink=link,confirmed_at=base.now(),source='user_explicit_confirmation_20261120',plan_sha256=value['sha256']))
    if record.get('comment_status') not in {'sent','already_present'}:
        record.setdefault('comment_status_before_user_confirmation',record.get('comment_status','not_started'))
        record.setdefault('comment_error_before_user_confirmation',record.get('comment_error',''))
        record.update(comment_status='already_present',comment_confirmation_method='user_confirmed_manual_comment_20261120',comment_error='')
    # Store this as user-supplied evidence, without fabricating a platform lookup.
    record.setdefault('user_supplied_permalink',link)
    if state!=before:base.upload.save_json(state_path,state)


def execute(root):
    root=Path(root).resolve()
    if root!=base.upload.ROOT.resolve():raise ValueError('请在原Windows上传目录运行。')
    native_mark=base.mark_row
    with patch.object(base,'mark_row',side_effect=lambda r,row,v:mark_with_manual_comments(native_mark,r,row,v)),patch.object(base,'SCHEMA',SCHEMA),patch.object(base,'METHOD',METHOD),patch.object(base,'JOURNAL',JOURNAL),patch.object(base,'prepare',side_effect=prepare),patch.object(base,'inspect_workers',side_effect=inspect_workers):
        return base.execute(root)


def execute_with_diagnostics(root):
    result=execute(root)
    from diagnose_nov19_comment_samples_20261120 import collect
    try:collect(root)
    except KeyboardInterrupt:raise
    except Exception as error:print('视频归档结果已保留；评论诊断未完成：',str(error).split('\n',1)[0],flush=True)
    return result


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的新PowerShell窗口运行。')
        raise SystemExit(execute_with_diagnostics(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停；归档及用户确认记录保留，重跑同一入口继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
