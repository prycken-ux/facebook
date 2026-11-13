"""Publish Nov13 distributed originals first, archive extra old inbox media, then comments."""
import contextlib,copy,hashlib,re,shutil,sys,time,uuid
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import scheduled_priority_workflow as workflow
import publish_priority_batch as priority
import normal_chrome_batch as normal
import local_file_input as local
import distribute_video_materials as materials
import archive_nov12_materials_20261113 as archive
import personal_owner_routes as personals
import recovery_numeric_identity as numeric
import page_reel_ai_compat as editor
import capture_current_publication as capture
import safe_video_comments as comments
from apply_common_caption import atomic_caption
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

DAY='2026-11-13'
SCOPE='nov13-distributed-new-materials-first-fb01-to-fb24-v1'
POINTER='nov13-distributed-first24-publication.json'
ALLOWED={f'fb{n:02d}' for n in range(1,25)}
WAVE_LABEL='第一批'
WAVE_DESCRIPTION='fb01–fb24及其公共主页'


def require_day():
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DAY:raise ValueError('只授权北京时间11月13日发布今天分配的新视频。')


def distribution(relative=None):
    if relative is None:
        settings=upload.read_json(upload.ROOT/materials.SETTINGS,{})
        source=settings.get('source')
        if not isinstance(source,str) or not source:raise ValueError('请先运行今天的自动分配视频指令，未改选旧素材。')
        token=hashlib.sha256(str(Path(source).resolve()).casefold().encode()).hexdigest()[:16]
        path=upload.ROOT/'logs/material-distribution'/token/(DAY+'.json')
    else:
        path=upload.ROOT/relative
    archive.safe(path).resolve().relative_to((upload.ROOT/'logs/material-distribution').resolve())
    if path.name!=DAY+'.json':raise ValueError('不是今天第一批或统一分配的清单。')
    value=archive.checked_json(path);payload=value['payload']
    if (payload.get('schema')!=materials.SCHEMA or payload.get('date')!=DAY
            or payload.get('target_scope','all') not in {'all','existing24'}):raise ValueError('今天分配清单范围异常。')
    rows=[r for r in payload.get('assignments',[]) if r.get('account') in ALLOWED]
    pairs=[(r['account'],r['target']) for r in rows]
    if not rows or len(set(pairs))!=len(pairs):raise ValueError('第一批发布目标为空或重复。')
    progress=upload.read_json(path.with_name(path.stem+'-progress.json'),{})
    if (progress.get('sha256')!=value['sha256'] or not isinstance(progress.get('done'),list)
            or not {a+'/'+t for a,t in pairs}<=set(progress['done'])):raise ValueError('fb01–fb24素材尚未全部分配完成，请先续完分配。')
    return path,value,rows,set(progress.get('existing_video_records',[]))


def validate(path,value,material):
    workflow.validate(path,value)
    p=value['payload'];jobs=p['jobs']
    if (p.get('date')!=DAY or p.get('distributed_scope')!=SCOPE
            or p.get('distribution_sha256')!=material['sha256'] or p.get('intended_accounts')!=sorted(ALLOWED)
            or any(j['account'] not in ALLOWED for j in jobs)):
        raise ValueError('今天新素材发布范围或分配指纹变化，未重建或加入旧视频。')
    assignments={(r['account'],r['target']):r for r in material['payload']['assignments']}
    for job in jobs:
        row=assignments.get((job['account'],job['target']),{})
        file=row.get('files',[{}])[-1]
        if (file.get('destination_name')!=job['filename'] or file.get('sha256')!=job.get('video_sha256')
                or file.get('size')!=job.get('video_size')):raise ValueError('发布文件不是今天分配的原视频。')


def freeze():
    pointer=upload.ROOT/'logs'/POINTER;saved=upload.read_json(pointer,None)
    if saved:
        name=saved.get('manifest','')
        if not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json',name):raise ValueError('今天续跑指针异常。')
        path=upload.ROOT/'logs'/name;value=upload.read_json(path,{})
        _,material,_,_=distribution(value.get('payload',{}).get('distribution_manifest'))
        validate(path,value,material)
        if saved.get('sha256')!=value['sha256']:raise ValueError('今天续跑清单校验失败。')
        return path,value
    owned=[]
    for path in (upload.ROOT/'logs').glob('frozen-material-'+DAY+'-*.json'):
        value=upload.read_json(path,{})
        if value.get('payload',{}).get('distributed_scope')==SCOPE:
            _,material,_,_=distribution(value['payload'].get('distribution_manifest'));validate(path,value,material);owned.append((path,value))
    if len(owned)>1:raise ValueError('今天有多个同范围清单，未猜选。')
    if owned:
        path,value=owned[0];upload.save_json(pointer,dict(manifest=path.name,sha256=value['sha256']));return path,value
    material_path,material,rows,duplicates=distribution()
    content=batch.preferences.content_policy(DAY);policy=batch.preferences.load(DAY)
    if (not content or content['payload']['caption']!=batch.preferences.EVERYDAY_CAPTION
            or content['payload']['comment']!=batch.preferences.EVERYDAY_COMMENT):raise ValueError('已保存正文和评论不是之前确认的实拍文案，未擅自替换。')
    config=upload.read_json(upload.CONFIG,{});state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    urls=Counter(upload.target_key(e['url']) for e in config.get('targets',[]) if e.get('account') in ALLOWED and e.get('url'))
    previous=batch.previous_plan_keys(DAY)
    for old in (upload.ROOT/'logs').glob('frozen-material-'+DAY+'-*.json'):
        if not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json',old.name):continue
        candidate=archive.checked_json(old)
        if candidate.get('payload',{}).get('schema')==batch.SCHEMA:
            previous.update({j['key']:old.name for j in candidate['payload'].get('jobs',[])})
    jobs=[];issues=[];old_files=[];backup=upload.ROOT/'backups'/('nov13-new-materials-'+uuid.uuid4().hex[:12])
    protected=archive.today_files()
    for index,assignment in enumerate(rows,1):
        account,target=assignment['account'],assignment['target'];file=assignment.get('files',[{}])[-1]
        print('核对今天分配素材：',index,'/',len(rows),account,target,file.get('destination_name',''),flush=True)
        try:
            filename=file.get('destination_name','');upload.validate_video_filename(filename)
            entries=[e for e in config.get('targets',[]) if (e.get('account'),e.get('target'))==(account,target)]
            if len(entries)!=1:raise ValueError('没有唯一已登记目标，不要求重新填写名称，也不猜选账号')
            entry=entries[0];upload.validate_entry(entry)
            if urls[upload.target_key(entry['url'])]!=1:raise ValueError('同一主页配置到多个目标，未猜选重复发布')
            if assignment.get('url') and upload.target_key(assignment['url'])!=upload.target_key(entry['url']):raise ValueError('分配后账号身份已变化')
            if not batch.eligible(entry,True,date=DAY):raise ValueError('目标未完成发布登记或尚未允许发布')
            if not (upload.ROOT/'profiles'/account).is_dir():raise ValueError('原登录资料缺失')
            video=archive.safe(upload.inbox_for(entry)/filename)
            if archive.info(video)!=dict(size=file['size'],sha256=file['sha256']):raise ValueError('今天分配视频已变化或缺失')
            key=upload.job_key(entry,video)
            if key in state or key in previous or account+'/'+target in duplicates:raise ValueError('今天分配的内容与已有任务重复，保留旧记录，不重发或另选其他视频')
            caption=video.with_suffix('.txt');text=content['payload']['caption']
            if not caption.is_file() or caption.read_text(encoding='utf-8-sig').strip()!=text:
                backup.mkdir(parents=True,exist_ok=True)
                if caption.exists():shutil.copy2(caption,backup/(account+'-'+target+'-'+caption.name))
                atomic_caption(caption,text)
            job=dict(account=account,target=target,filename=filename,key=key,url=entry['url'],entry_sha256=batch.digest(entry),
                     caption_text=text,caption_sha256=batch.file_hash(caption),video_size=file['size'],video_sha256=file['sha256'],publication_content_sha256=content['sha256'])
            jobs.append(job)
            for older in sorted(video.parent.iterdir(),key=lambda p:p.name):
                if not older.is_file() or older.suffix.lower()!='.mp4' or older==video or str(older).casefold() in protected:continue
                old_info=archive.info(older);identity=batch.digest(dict(account=account,target=target,name=older.name,**old_info))
                destination=archive.safe(video.parent.parent/'archive'/('before-'+DAY)/identity[:16])
                if destination.exists():destination=destination.with_name(identity[:16]+'-'+uuid.uuid4().hex[:8])
                files=[]
                for source in (older.with_suffix('.txt'),older.with_suffix('.comment.txt'),older):
                    if source.is_file() and str(source).casefold() not in protected:
                        files.append(dict(source=archive.relative(source),destination=archive.relative(destination/source.name),kind='video' if source==older else 'text',**archive.info(source)))
                related=[]
                for old_key,row in state.items():
                    if (row.get('account'),row.get('target'))==(account,target) and str(row.get('video','')).replace('\\','/').split('/')[-1]==older.name:
                        try:
                            if upload.job_key(dict(url=row['url']),older)==old_key:related.append(old_key)
                        except ValueError:pass
                old_files.append(dict(id=identity,account=account,target=target,files=files,state_keys=related))
        except Exception as error:issues.append(dict(account=account,target=target,filename=file.get('destination_name',''),reason=str(error) or type(error).__name__))
    if not jobs:raise ValueError('没有可发布的今天新素材：'+str(issues))
    now=datetime.now(timezone.utc)
    payload=dict(schema=batch.SCHEMA,date=DAY,start=(now+timedelta(seconds=75)).isoformat(),requested_start=now.isoformat(),
                 ai_label=False,include_fb10_pages=True,excluded_accounts=sorted(batch.excluded_accounts(DAY)),comment_text=content['payload']['comment'],jobs=jobs,
                 publication_content_sha256=content['sha256'],publication_preferences_sha256=policy['sha256'],comment_retry_policy=priority.COMMENT_RECOVERY_VERSION,
                 distributed_scope=SCOPE,distribution_manifest=archive.relative(material_path),distribution_sha256=material['sha256'],old_material_files=old_files,intended_accounts=sorted(ALLOWED))
    value=dict(payload=payload,sha256=batch.digest(payload),created_at=now.isoformat(),issues=issues,workflow='future-video-comments-v1',
               auto_retry_policy=priority.retry.POLICY,comment_timing=priority.TIMING,priority_workflow=priority.PRIORITY_WORKFLOW_VERSION,
               report_format='text',scheduled_priority_runner=workflow.VERSION,browser_launch_mode=normal.NORMAL_CHROME_VERSION,local_file_input_mode=local.VERSION)
    path=upload.ROOT/'logs'/('frozen-material-'+DAY+'-'+value['sha256'][:16]+'.json')
    validate(path,value,material);upload.save_json(path,value);upload.save_json(pointer,dict(manifest=path.name,sha256=value['sha256']))
    return path,value


def archive_old(path,value):
    progress_path=path.with_name(path.stem+'-old-material-archive.json')
    progress=upload.read_json(progress_path,dict(sha256=value['sha256'],done=[]))
    if progress.get('sha256')!=value['sha256'] or not isinstance(progress.get('done'),list):raise ValueError('旧素材归档进度异常。')
    state_path=upload.ROOT/'logs/publish_state.json'
    if not progress_path.exists():
        backup=upload.ROOT/'backups'/('nov13-before-new-publication-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        if state_path.exists():shutil.copy2(state_path,backup/state_path.name)
        upload.save_json(progress_path,progress)
    for row in value['payload']['old_material_files']:
        if row['id'] in progress['done']:continue
        try:
            protected=archive.today_files()
            if any(str(archive.safe(upload.ROOT/f['source'])).casefold() in protected for f in row['files']):raise ValueError('该路径属于今天其他已分配素材，保留')
            for file in row['files']:archive.move_exact(file)
            current=upload.read_json(state_path,{})
            video=next(f for f in row['files'] if f['kind']=='video')
            for key in row['state_keys']:
                record=current.get(key,{})
                record.update(material_archive_video=str(upload.ROOT/video['destination']),material_archive_before_batch=path.name)
                if record.get('uploader_version')=='2.47' and record.get('status') in {'preparing','posting'}:
                    old=record['status']
                    record.update(status='needs_review' if record.get('post_intent_at') else 'paused',
                                  status_before_archive=old,pause_reason='old_material_archived_for_today_new_video')
            upload.save_json(state_path,current)
            progress['done'].append(row['id']);upload.save_json(progress_path,progress)
            print('已归档同目录旧视频：',row['account'],row['target'],Path(video['source']).name,flush=True)
        except Exception as error:print('此旧素材保留待检查，继续今天新视频：',row['account'],row['target'],str(error).split('\n',1)[0],flush=True)
    return {r['id'] for r in value['payload']['old_material_files']}<=set(progress['done'])


def recover_own(path,value):
    state_path=upload.ROOT/'logs/publish_state.json';state=upload.read_json(state_path,{})
    report_path=path.with_name(path.stem+'-results.json');report=upload.read_json(report_path,dict(manifest=path.name,attempts=[]))
    if report.get('manifest')!=path.name or not isinstance(report.get('attempts'),list):raise ValueError('本批续跑结果异常。')
    changed=[];attempted={r['key'] for r in report['attempts']}
    for job in value['payload']['jobs']:
        row=state.get(job['key'],{})
        if row.get('source_frozen_manifest')!=path.name or row.get('source_frozen_sha256')!=value['sha256'] or row.get('status') not in {'preparing','posting'}:continue
        if row.get('uploader_version')!='2.47' or (row.get('account'),row.get('target'))!=(job['account'],job['target']):raise ValueError('中断记录身份不一致。')
        if row.get('permalink') or row.get('success_message'):continue
        changed.append(copy.deepcopy(row))
        row.update(status='needs_review' if row.get('post_intent_at') else 'failed_before_post',
                   error='Target page, context or browser has been closed; resumed exact frozen job',
                   review_reason='publication_interrupted' if row.get('post_intent_at') else '')
        if job['key'] not in attempted:
            report['attempts'].append(dict(key=job['key'],account=job['account'],target=job['target'],action='manual_required',started_at=row['created'],error=row['error']))
    if changed:
        backup=upload.ROOT/'backups'/('nov13-interrupted-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        upload.save_json(backup/'before-recovery.json',changed);upload.save_json(state_path,state);upload.save_json(report_path,report)


def pause_archived_history(path,value):
    state_path=upload.ROOT/'logs/publish_state.json';state=upload.read_json(state_path,{})
    current_keys={j['key'] for j in value['payload']['jobs']};changes=[]
    for key,row in state.items():
        if (key in current_keys or row.get('account') not in ALLOWED or row.get('status') not in {'preparing','posting'}
                or row.get('uploader_version')!='2.47' or row.get('material_archive_date')!='2026-11-12'):continue
        name=row.get('material_archive_video')
        if not name:continue
        video=archive.safe(Path(name))
        if not video.is_file() or upload.job_key(dict(url=row['url']),video)!=key:continue
        changes.append(copy.deepcopy(row))
        row.update(status='needs_review' if row.get('post_intent_at') else 'paused',status_before_archive=row['status'],
                   pause_reason='verified_old_material_already_archived_before_new_batch',paused_for_manifest=path.name)
    if changes:
        backup=upload.ROOT/'backups'/('nov13-archived-history-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        upload.save_json(backup/'original-records.json',changes);upload.save_json(state_path,state)
        print('已保留归档旧任务的历史记录，暂停其执行，继续今天新素材：',len(changes),'条。',flush=True)


def reconcile(path,value):
    state_path=upload.ROOT/'logs/publish_state.json';finder=priority.actual.make_finder(value['payload']['jobs'],True,interactive=False,total_timeout_ms=120000)
    for job in value['payload']['jobs']:
        state=upload.read_json(state_path,{});row=state.get(job['key'],{});original=copy.deepcopy(row)
        if (row.get('status')!='needs_review' or row.get('source_frozen_manifest')!=path.name
                or row.get('source_frozen_sha256')!=value['sha256'] or not row.get('post_intent_at')):continue
        try:
            if ((row.get('account'),row.get('target'))!=(job['account'],job['target'])
                    or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
                    or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):raise ValueError('结果记录与本批原视频身份不一致')
            batch.validate_job(job,date=DAY);link=comments.direct_link(row.get('fresh_publication_candidate',''))
            explicit=(link and row.get('fresh_publication_job_key')==job['key'] and row.get('fresh_publication_candidate_count')==1 and row.get('fresh_publication_explicit_published') is True)
            method='fresh_owned_published_metadata' if explicit else None
            if not explicit:
                from playwright.sync_api import sync_playwright
                entry=dict(priority.daily.configured(job),auto_switch_personal=True)
                close_selected_window(entry['account'])
                with sync_playwright() as pw:
                    context=upload.launch_context(pw,entry)
                    try:
                        page=context.pages[0] if context.pages else context.new_page();upload.ensure_identity(page,entry)
                        since=datetime.fromisoformat(row['post_intent_at']).timestamp()-5;end=datetime.now(timezone.utc).timestamp()+5
                        if link:
                            valid,_=priority.actual.inspect_video(page,context,entry,job['caption_text'],since,end,link)
                            if not valid:raise ValueError('新视频直链尚未取得完整核验，保留待核实')
                            method='verified_owner_caption_time'
                        else:link,method=finder(page,context,entry,job['caption_text'],since,end,diagnostic_path=upload.ROOT/'logs'/('nov13-'+job['key'][:12]+'-lookup.json'))
                    finally:context.close()
            current=upload.read_json(state_path,{})
            if current.get(job['key'])!=original:raise ValueError('核对期间记录变化，未覆盖')
            row=current[job['key']];now=datetime.now(timezone.utc).isoformat()
            row.update(status='published',confirmation_method=method,confirmed_at=now,confirmed_batch_lookup_cutoff=now,
                       permalink=link,comment_link_job_key=job['key'],comment_link_method=method,error='',review_reason='')
            if row.get('comment_status') not in {'sent','already_present','sending','verifying','needs_review'}:row['comment_status']='deferred'
            upload.save_json(state_path,current)
            entry=batch.validate_job(job,date=DAY);video=upload.inbox_for(entry)/job['filename'];folder=upload.archive(video,video.with_suffix('.txt'))
            row.update(archived_video=str(folder/video.name),archived_caption=str(folder/video.with_suffix('.txt').name),archived_at=now);upload.save_json(state_path,current)
            print('已核实本批视频成功：',job['account'],job['target'],link,flush=True)
        except Exception as error:print('保留待核实，不再次上传：',job['account'],job['target'],str(error).split('\n',1)[0],flush=True)


def execute(real_footage):
    if not real_footage:raise ValueError('今天这批素材尚未确认全部实拍，未发布。')
    require_day();workflow.require_versions()
    with locked():path,value=freeze();archive_ok=archive_old(path,value);pause_archived_history(path,value);recover_own(path,value)
    jobs=value['payload']['jobs'];pages={(j['account'],j['target']) for j in jobs if j['target']!='personal'};ensure=numeric.ensure
    print('今天'+WAVE_LABEL+'：',len(jobs),'条；范围：',WAVE_DESCRIPTION,'。',flush=True)
    for issue in value['issues']:print('本目标暂未进入发布：',issue,flush=True)
    with priority.daily.keep_awake(),personals.scoped(ALLOWED),numeric.scoped(pages),editor.installed(), \
            patch.object(numeric,'ensure',side_effect=lambda page,entry:ensure(page,entry,interactive=False)), \
            patch.object(upload,'launch_context',normal.launcher_for_jobs(jobs,date=DAY)),capture.installed(path,value):
        if datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):
            print('正在等待新视频和统一文案写入稳定，约一分钟后自动开始，请保持窗口打开。',flush=True)
        while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
        batch.run(path,defer_comments=True,resume=True)
        priority.retry.run(path)
        with locked():reconcile(path,value)
        rows=[]
        with patch.object(priority.daily,'find_published',priority.actual.make_finder(jobs,True,interactive=False)):
            priority.daily.backfill(value,None,only_keys={j['key'] for j in jobs},rows=rows,future_only=True,reconcile_pending=True,reporter=lambda *_:priority.comment_report(path,value,rows))
        priority.comment_retry.run(path,reporter=lambda m,r,o:priority.comment_report(path,value,r))
    report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    final=batch.results(path,value,report.get('attempts',[]),None,final=True)
    if not archive_ok:print('同目录旧素材仍有归档未完成项，详见前面的逐条提示。',flush=True)
    return 0 if archive_ok and not value['issues'] and all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in final) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute('--real-footage' in sys.argv[2:]))
    except KeyboardInterrupt:print('已暂停，保留归档和发布进度；重跑继续今天第一批。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
