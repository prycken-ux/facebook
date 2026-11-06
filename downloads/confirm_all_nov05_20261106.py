"""Record the user's confirmation for the exact 30 Nov-5 videos; no browser work."""
import ast,copy,hashlib,re,shutil,ssl,sys,urllib.request,uuid
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import publish_priority_batch as priority
from add_fb_accounts import locked

PREFIX='ba7aa00b'
METHOD='user_confirmed_all_nov05_published_20261106'


def source():
    paths=[p for p in (upload.ROOT/'logs').glob('frozen-material-2026-11-05-'+PREFIX+'*.json')
           if re.fullmatch(r'frozen-material-2026-11-05-[a-f0-9]{16}\.json',p.name)]
    if len(paths)!=1:raise ValueError('没有唯一的11月5日ba7aa00b原批次，未改选今天素材')
    path=paths[0];value=upload.read_json(path,{})
    priority.validate(path,value,'2026-11-05')
    jobs=value['payload']['jobs'];expected=Counter(daily.EXPECTED_PAIRS);del expected[('fb10','page10')];expected[('fb10','page08')]+=1
    if (not value['sha256'].startswith(PREFIX) or len(jobs)!=30
            or Counter((j['account'],j['target']) for j in jobs)!=expected
            or len({j['key'] for j in jobs})!=30):raise ValueError('原30条清单范围不一致，未标记其他批次')
    pointer=upload.read_json(upload.ROOT/'logs/priority-batch-2026-11-05.json',{})
    if pointer!={'date':'2026-11-05','manifest':path.name,'sha256':value['sha256']}:raise ValueError('11月5日原批次指针不一致')
    report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if report.get('manifest')!=path.name or not isinstance(report.get('attempts'),list):raise ValueError('原尝试记录不匹配，未覆盖结果')
    return path,value,report


def original_file(entry,job):
    folder=upload.inbox_for(entry);candidates=[folder/job['filename']]
    completed=folder.parent/'completed'
    if completed.is_dir():candidates.extend(completed.rglob(job['filename']))
    for video in candidates:
        if not video.is_file():continue
        video.resolve().relative_to(folder.parent.resolve())
        before=video.stat();key=upload.job_key(entry,video);after=video.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('原视频正在变化，未补建成功记录')
        if before.st_size and key==job['key']:return video
    raise ValueError('缺少任务记录，且未找到指纹一致的原视频：'+job['account']+'/'+job['target']+' '+job['filename'])


def execute():
    if upload.VERSION!='2.47':raise ValueError('需使用现有2.47核心，未升级或降级程序')
    state_path=upload.ROOT/'logs/publish_state.json'
    with locked():
        path,value,report=source();jobs=value['payload']['jobs'];original=upload.read_json(state_path,{})
        plan=[]
        for job in jobs:
            entry=daily.configured(job);upload.validate_video_filename(job['filename']);row=original.get(job['key'])
            if row is None:
                video=original_file(entry,job)
            else:
                if (not isinstance(row,dict) or (row.get('account'),row.get('target'))!=(job['account'],job['target'])
                        or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
                        or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']
                        or row.get('status') not in {'published','failed_before_post','needs_review'}):raise ValueError('当前原视频记录或阶段不一致，未覆盖：'+job['account']+'/'+job['target'])
                if row['status']=='published':continue
                video=Path(row['video'])
            plan.append(dict(job=job,entry=entry,video=video,previous=copy.deepcopy(row)))
        # Recheck absent-record source bytes before creating any guard.
        for item in plan:
            if item['previous'] is None and upload.job_key(item['entry'],item['video'])!=item['job']['key']:raise ValueError('补记前原视频内容变化，未创建记录')
        backup=upload.ROOT/'backups'/('confirmed-nov05-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        for file in (state_path,path,path.with_name(path.stem+'-results.json'),path.with_name(path.stem+'-results.txt')):
            if file.is_file():shutil.copy2(file,backup/file.name)
        now=datetime.now(timezone.utc).isoformat()
        audit=dict(source_manifest=path.name,method=METHOD,confirmed_at=now,
                   changes=[dict(account=i['job']['account'],target=i['job']['target'],key=i['job']['key'],previous_record=i['previous']) for i in plan])
        upload.save_json(backup/'confirmation-audit.json',audit)
        state=copy.deepcopy(original)
        for item in plan:
            job=item['job'];row=state.get(job['key'])
            if row is None:
                row=dict(account=job['account'],target=job['target'],url=job['url'],video=str(item['video']),caption=str(item['video'].with_suffix('.txt')),
                         created=value['created_at'],ai_label_requested=False,comment_status='not_started',created_from_user_confirmation=True)
                state[job['key']]=row
            row.update(status='published',status_before_user_confirmation=item['previous'].get('status') if item['previous'] else 'unrecorded',
                       confirmation_method=METHOD,confirmed_at=now,confirmed_source_manifest=path.name,confirmed_batch_lookup_cutoff=now,error='')
            row.setdefault('published_caption_text',job['caption_text']);row.pop('review_reason',None)
        if plan:upload.save_json(state_path,state)  # No-reupload guards before any archive operation.
        for item,change in zip(plan,audit['changes']):
            job=item['job'];entry=item['entry'];video=upload.inbox_for(entry)/job['filename'];caption=video.with_suffix('.txt')
            change['archive_result']='原文件已归档、缺失或内容/文案变化；未移动其他文件'
            try:
                if video.is_file() and caption.is_file() and upload.job_key(entry,video)==job['key'] and batch.file_hash(caption)==job['caption_sha256']:
                    folder=upload.archive(video,caption)
                    state[job['key']].update(archived_video=str(folder/video.name),archived_caption=str(folder/caption.name),archived_at=now)
                    upload.save_json(state_path,state);change['archive_result']='原视频已归档'
            except Exception as error:change['archive_result']='成功记录保留；归档需核实：'+str(error).split('\n',1)[0]
        upload.save_json(backup/'confirmation-audit.json',audit)
        rows=batch.results(path,value,report['attempts'],None,final=True)
        counts=Counter(r['comment_status'] for r in rows)
        print('11月5日原批次已按你的确认：发布成功30/30。新增补记：',len(plan),'条；原有成功记录保留。',flush=True)
        print('评论保持原状态：已成功/已存在',counts['sent']+counts['already_present'],'条；其余未标记为评论成功。',flush=True)
        print('本次没有打开浏览器、上传、补发或发送评论；账号配置及申诉状态未更改。备份：',backup,flush=True)
    return 0


def recover_locks(root):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    expected='2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3'
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            url=base+'d8c998c705801c948a230c0504fcb65653ae8086/downloads/recover_resume_new_batch.py'
            with urllib.request.urlopen(url,context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Lock helper checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));break
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    else:raise RuntimeError('锁核验组件下载失败，未改动发布记录')
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(data,'verified-lock-library','exec'),namespace);namespace['recover_locks'](root)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        root=Path(sys.argv[1]).resolve()
        if sys.platform!='win32' or upload.ROOT.resolve()!=root:raise ValueError('请在原Windows上传电脑运行')
        recover_locks(root);raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止，已保存的成功记录保留；未上传或评论。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
