"""Explicit Nov14 continuation of the immutable Nov13 distribution and publication jobs."""
import contextlib,copy,re,shutil,sys,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import publish_all_distributed_nov13 as original
first=original.first
RUN_DAY='2026-11-14'
SOURCE_DAY='2026-11-13'
SOURCE_FIRST_SCOPE='nov13-distributed-new-materials-first-fb01-to-fb24-v1'
SOURCE_SECOND='nov13-distributed-second-owned-fifty-v1'
FIRST_SCOPE='resume-nov13-materials-on-nov14-first24-v1'
SECOND_SCOPE='resume-nov13-materials-on-nov14-second-fifty-v1'
FIRST_POINTER='resume-nov13-first24-on-nov14.json'
CONTROL='resume-nov13-two-waves-on-nov14.json'
FREEZE=first.freeze
RETRY=first.priority.retry.run
RECONCILE=first.reconcile
FINDER=first.priority.actual.make_finder
DISTRIBUTE=first.materials.distribute
CHECK_FIELDS=('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at')


def require_run_day():
    if datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()!=RUN_DAY:
        raise ValueError('此指令仅授权11月14日续跑11月13日的原素材。')


def has_submission(row):
    if isinstance(row,list):return any(has_submission(v) for v in row)
    if not isinstance(row,dict):return False
    return row.get('status') in {'published','posting','needs_review'} or any(row.get(k) for k in CHECK_FIELDS) or any(has_submission(v) for v in row.values() if isinstance(v,(dict,list)))


def bound_record(job,row):
    try:return ((row.get('account'),row.get('target'))==(job['account'],job['target'])
                and first.upload.target_key(row.get('url',''))==first.upload.target_key(job['url'])
                and str(row.get('video','')).replace('\\','/').split('/')[-1]==job['filename'])
    except (ValueError,TypeError):return False


def source():
    pointer=first.upload.read_json(first.upload.ROOT/'logs/nov13-distributed-first24-publication.json',{})
    name=pointer.get('manifest','')
    if not re.fullmatch('frozen-material-'+SOURCE_DAY+r'-[a-f0-9]{16}\.json',name):raise ValueError('没有昨天第一批的原冻结指针，未根据新文件重建。')
    path=first.upload.ROOT/'logs'/name;value=first.archive.checked_json(path);p=value['payload']
    if (pointer.get('sha256')!=value['sha256'] or p.get('date')!=SOURCE_DAY or p.get('distributed_scope')!=SOURCE_FIRST_SCOPE or p.get('ai_label') is not False):raise ValueError('昨天原发布清单的范围或实拍记录异常。')
    material_path=first.upload.ROOT/p['distribution_manifest'];first.archive.safe(material_path).resolve().relative_to((first.upload.ROOT/'logs/material-distribution').resolve())
    material=first.archive.checked_json(material_path)
    if (material_path.name!=SOURCE_DAY+'.json' or material['sha256']!=p.get('distribution_sha256')
            or material['payload'].get('date')!=SOURCE_DAY or material['payload'].get('schema')!=first.materials.SCHEMA):raise ValueError('昨天分配清单与原发布素材不一致。')
    parents={path.name:value}
    for candidate in (first.upload.ROOT/'logs').glob('frozen-material-'+SOURCE_DAY+'-*.json'):
        if not re.fullmatch('frozen-material-'+SOURCE_DAY+r'-[a-f0-9]{16}\.json',candidate.name):continue
        raw=first.upload.read_json(candidate,{})
        if str(raw.get('payload',{}).get('distributed_scope','')).startswith(SOURCE_SECOND+'-'):
            raw=first.archive.checked_json(candidate)
            if raw['payload'].get('date')!=SOURCE_DAY or raw['payload'].get('distribution_sha256')!=material['sha256'] or raw['payload'].get('ai_label') is not False:raise ValueError('昨天第二批原清单指纹不一致。')
            parents[candidate.name]=raw
    assignments={(r['account'],r['target']):r for r in material['payload']['assignments']}
    by_pair={}
    for parent_name,parent in parents.items():
        if not re.fullmatch('frozen-material-'+SOURCE_DAY+'-'+parent['sha256'][:16]+r'\.json',parent_name):raise ValueError('昨天原清单文件名与指纹不一致。')
        for job in parent['payload']['jobs']:
            pair=job['account'],job['target'];file=assignments.get(pair,{}).get('files',[{}])[-1]
            if (file.get('destination_name')!=job['filename'] or file.get('sha256')!=job.get('video_sha256') or file.get('size')!=job.get('video_size')):raise ValueError('原冻结视频不属于昨天分配记录。')
            if pair in by_pair and by_pair[pair][1]!=job:raise ValueError('昨天同一目标有不同原视频，未猜选。')
            by_pair[pair]=(parent_name,job)
    return path,value,material_path,material,parents,by_pair


def source_day_finder(jobs,*args,**kwargs):
    inner=FINDER(jobs,*args,**kwargs);mapping={(j['account'],j['target']):j for j in jobs}
    midnight=datetime.fromisoformat(RUN_DAY+'T00:00:00+08:00').timestamp()
    source_start=datetime.fromisoformat(SOURCE_DAY+'T00:00:00+08:00').timestamp()
    def find(page,context,entry,caption,start,end,**options):
        job=mapping[(entry['account'],entry['target'])];row=first.upload.read_json(first.upload.ROOT/'logs/publish_state.json',{}).get(job['key'],{})
        if start==midnight and row.get('created'):
            created=datetime.fromisoformat(row['created']).timestamp()
            if source_start<=created<midnight:start=max(source_start,created-5)
        if row.get('created') and row.get('post_intent_at'):
            created=datetime.fromisoformat(row['created']).timestamp()
            if source_start<=created<midnight:end=min(end,datetime.fromisoformat(row['post_intent_at']).timestamp()+900)
        return inner(page,context,entry,caption,start,end,**options)
    return find


def resume_distribution(*args,**kwargs):
    if kwargs.get('day')!=SOURCE_DAY:raise ValueError('跨天续跑不能建立今天的新素材分配。')
    save=first.upload.save_json;settings=first.upload.ROOT/first.materials.SETTINGS
    def preserve_settings(path,value):
        if Path(path)==settings:return
        return save(path,value)
    with patch.object(first.upload,'save_json',side_effect=preserve_settings):return DISTRIBUTE(*args,**kwargs)


def execute():
    require_run_day()
    with first.locked():parent_path,parent,material_path,material,parents,by_pair=source()
    content=first.batch.preferences.content_policy(SOURCE_DAY,parent['payload']['publication_content_sha256'])
    if not content or content['payload']['caption']!=first.batch.preferences.EVERYDAY_CAPTION or content['payload']['comment']!=first.batch.preferences.EVERYDAY_COMMENT:
        raise ValueError('昨天原正文和评论版本异常，未更换。')
    distribution=original.DISTRIBUTION
    def bound_distribution(relative=None):
        result=distribution(relative or first.archive.relative(material_path))
        if result[1]['sha256']!=material['sha256']:raise ValueError('续跑只接受昨天原分配清单。')
        return result

    def freeze_resume():
        pointer=first.upload.ROOT/'logs'/first.POINTER;saved=first.upload.read_json(pointer,None)
        if saved:
            name=saved.get('manifest','')
            if not re.fullmatch('frozen-material-'+RUN_DAY+r'-[a-f0-9]{16}\.json',name):raise ValueError('跨天续跑指针异常。')
            path=first.upload.ROOT/'logs'/name;value=first.archive.checked_json(path)
            first.validate(path,value,material)
            if saved.get('sha256')!=value['sha256'] or value['payload'].get('resume_source_first_sha256')!=parent['sha256']:raise ValueError('跨天续跑原任务发生变化。')
            return path,value
        for path in (first.upload.ROOT/'logs').glob('frozen-material-'+RUN_DAY+'-*.json'):
            raw=first.upload.read_json(path,{})
            if raw.get('payload',{}).get('distributed_scope')==first.SCOPE:
                first.validate(path,raw,material)
                if raw['payload'].get('resume_source_first_sha256')!=parent['sha256']:raise ValueError('中断留下的续跑来源异常。')
                first.upload.save_json(pointer,dict(manifest=path.name,sha256=raw['sha256']));return path,raw
        _,_,rows,duplicates=first.distribution(first.archive.relative(material_path))
        config=first.upload.read_json(first.upload.CONFIG,{});state=first.upload.read_json(first.upload.ROOT/'logs/publish_state.json',{})
        jobs=[];issues=[];bindings={};changed_caption=False
        for assignment in rows:
            pair=assignment['account'],assignment['target'];file=assignment.get('files',[{}])[-1]
            try:
                if pair in by_pair:
                    name,job=by_pair[pair];jobs.append(copy.deepcopy(job));bindings[name]=parents[name]['sha256'];continue
                entries=[e for e in config['targets'] if (e.get('account'),e.get('target'))==pair]
                if len(entries)!=1 or not first.batch.eligible(entries[0],True,date=RUN_DAY):raise ValueError('新账号尚未完成登录及发布登记')
                entry=entries[0];first.upload.validate_entry(entry)
                filename=file['destination_name'];first.upload.validate_video_filename(filename)
                video=first.archive.safe(first.upload.inbox_for(entry)/filename)
                if first.archive.info(video)!=dict(size=file['size'],sha256=file['sha256']):raise ValueError('昨天分配的视频变化或缺失')
                key=first.upload.job_key(entry,video)
                if key in state or pair[0]+'/'+pair[1] in duplicates:raise ValueError('此原素材已有其他任务记录，保留，不重复上传')
                caption=video.with_suffix('.txt');text=content['payload']['caption']
                if not caption.is_file() or caption.read_text(encoding='utf-8-sig').strip()!=text:
                    backup=first.upload.ROOT/'backups'/('nov14-resume-caption-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
                    if caption.is_file():shutil.copy2(caption,backup/caption.name)
                    first.atomic_caption(caption,text);changed_caption=True
                jobs.append(dict(account=pair[0],target=pair[1],filename=filename,key=key,url=entry['url'],entry_sha256=first.batch.digest(entry),
                                 caption_text=text,caption_sha256=first.batch.file_hash(caption),video_size=file['size'],video_sha256=file['sha256'],publication_content_sha256=content['sha256']))
            except Exception as error:issues.append(dict(account=pair[0],target=pair[1],filename=file.get('destination_name',''),reason=str(error)))
        if not jobs:raise ValueError('没有可续跑的昨天原素材：'+str(issues))
        now=datetime.now(timezone.utc);policy=first.batch.preferences.load(RUN_DAY)
        payload=dict(schema=first.batch.SCHEMA,date=RUN_DAY,start=(now+timedelta(seconds=75 if changed_caption else 0)).isoformat(),requested_start=now.isoformat(),
                     ai_label=False,include_fb10_pages=True,excluded_accounts=sorted(first.batch.excluded_accounts(RUN_DAY)),jobs=jobs,comment_text=content['payload']['comment'],
                     publication_content_sha256=content['sha256'],publication_preferences_sha256=policy['sha256'],comment_retry_policy=first.priority.COMMENT_RECOVERY_VERSION,
                     distributed_scope=first.SCOPE,intended_accounts=sorted(first.ALLOWED),distribution_manifest=first.archive.relative(material_path),distribution_sha256=material['sha256'],
                     old_material_files=[],resume_source_date=SOURCE_DAY,resume_source_first_sha256=parent['sha256'],resume_source_plans=bindings)
        value=dict(payload=payload,sha256=first.batch.digest(payload),created_at=now.isoformat(),issues=issues,workflow='future-video-comments-v1',
                   auto_retry_policy=first.priority.retry.POLICY,comment_timing=first.priority.TIMING,priority_workflow=first.priority.PRIORITY_WORKFLOW_VERSION,
                   report_format='text',scheduled_priority_runner=first.workflow.VERSION,browser_launch_mode=first.normal.NORMAL_CHROME_VERSION,local_file_input_mode=first.local.VERSION)
        path=first.upload.ROOT/'logs'/('frozen-material-'+RUN_DAY+'-'+value['sha256'][:16]+'.json')
        first.validate(path,value,material);first.upload.save_json(path,value);first.upload.save_json(pointer,dict(manifest=path.name,sha256=value['sha256']))
        return path,value

    def normalize_previous(path,value):
        state_path=first.upload.ROOT/'logs/publish_state.json';state=first.upload.read_json(state_path,{});changes=[]
        for job in value['payload']['jobs']:
            row=state.get(job['key'],{});pair=job['account'],job['target']
            if pair not in by_pair or row.get('status') not in {'preparing','posting'} or row.get('uploader_version')!='2.47':continue
            parent_name=row.get('source_frozen_manifest')
            if (parent_name not in parents or row.get('source_frozen_sha256')!=parents[parent_name]['sha256']
                    or job['key'] not in {j['key'] for j in parents[parent_name]['payload']['jobs']}):continue
            if not bound_record(job,row):raise ValueError('中断原任务身份与冻结视频不一致，未覆盖。')
            changes.append(copy.deepcopy(row))
            posted=bool(row.get('post_intent_at') or row.get('success_message') or row.get('permalink'))
            row.update(status='needs_review' if posted else 'failed_before_post',error='Target page, context or browser has been closed; previous-day task retained',
                       review_reason='previous_day_interrupted_after_post' if posted else '')
        if changes:
            backup=first.upload.ROOT/'backups'/('resume-nov13-interrupted-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
            first.upload.save_json(backup/'original-records.json',changes);first.upload.save_json(state_path,state)

    def recover(path,value):
        normalize_previous(path,value);return original_recover(path,value)

    def old_retry(path):
        selected=RETRY(path)
        value=first.archive.checked_json(Path(path));state_path=first.upload.ROOT/'logs/publish_state.json'
        claims_path=Path(path).with_name(Path(path).stem+'-previous-day-before-post-claims.json')
        with first.locked():
            claims=first.upload.read_json(claims_path,dict(sha256=value['sha256'],jobs={}))
            if claims.get('sha256')!=value['sha256'] or not isinstance(claims.get('jobs'),dict):raise ValueError('跨天补发许可记录异常。')
            if not claims_path.exists():
                backup=first.upload.ROOT/'backups'/('resume-nov13-before-post-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
                if state_path.exists():shutil.copy2(state_path,backup/state_path.name)
            report_path=Path(path).with_name(Path(path).stem+'-results.json');report=first.upload.read_json(report_path,{})
            attempts=report.get('attempts',[])
            for job in value['payload']['jobs']:
                state=first.upload.read_json(state_path,{});row=state.get(job['key']);prior=claims['jobs'].get(job['key'])
                if prior:
                    if prior.get('phase')=='consumed' or row!=prior.get('replacement'):continue
                elif ((job['account'],job['target']) not in by_pair or not isinstance(row,dict) or row.get('status')!='failed_before_post'
                      or has_submission(row) or not bound_record(job,row) or row.get('uploader_version')!='2.47'
                      or row.get('source_frozen_manifest') not in parents
                      or row.get('source_frozen_sha256')!=parents[row['source_frozen_manifest']]['sha256']):continue
                attempt=None;replacement=None
                try:
                    entry=first.batch.validate_job(job,date=RUN_DAY)
                    if any(r.get('account')==job['account'] and r.get('status') in {'preparing','posting'} for r in state.values()):raise ValueError('账号还有进行中记录，保留')
                    first.close_selected_window(entry['account'])
                    if first.upload.read_json(state_path,{})!=state:raise ValueError('关闭窗口期间发布进度变化，未覆盖。')
                    if not prior:
                        replacement=dict(account=job['account'],target=job['target'],url=job['url'],video=str(first.upload.inbox_for(entry)/job['filename']),
                                         status='failed_before_post',uploader_version='2.47',ai_label_requested=False,created=datetime.now(timezone.utc).isoformat(),
                                         previous_day_attempt=copy.deepcopy(row),source_frozen_manifest=Path(path).name,source_frozen_sha256=value['sha256'])
                        claims['jobs'][job['key']]=dict(phase='reserved',original=copy.deepcopy(row),replacement=copy.deepcopy(replacement))
                        first.upload.save_json(claims_path,claims);state[job['key']]=replacement;first.upload.save_json(state_path,state)
                    else:replacement=prior['replacement']
                    attempt=dict(key=job['key'],account=job['account'],target=job['target'],started_at=datetime.now(timezone.utc).isoformat(),action='manual_required',attempt_phase='authorized_previous_day_before_post_retry')
                    print('补试昨天明确发布前失败的原视频，仅一次：',job['account'],job['target'],job['filename'],flush=True)
                    first.upload.run_entry(dict(entry,enabled=True,auto_switch_personal=True,_authorized_comment_text=value['payload']['comment_text']),state,state_path,True,
                                           filename=job['filename'],expected_job_key=job['key'],ai_label_override=False,retry_before_post=True,preserve_old_review_for_exact_job=True,defer_comments=True)
                    attempt['action']='finished'
                except KeyboardInterrupt:raise
                except Exception as error:
                    if attempt:attempt['error']=str(error)
                    print('该条保留结果，继续其他原任务：',job['account'],str(error).split('\n',1)[0],flush=True)
                finally:
                    if replacement is not None:
                        current=first.upload.read_json(state_path,{})
                        if current.get(job['key'])!=replacement:claims['jobs'][job['key']]['phase']='consumed'
                        first.upload.save_json(claims_path,claims)
                    if attempt:attempts.append(attempt);first.batch.results(Path(path),value,attempts,None)
        return selected

    def reconcile(path,value):
        RECONCILE(path,value)
        keys={j['key'] for j in value['payload']['jobs']}
        for parent_name,parent_value in parents.items():
            scoped=[j for j in parent_value['payload']['jobs'] if j['key'] in keys]
            if not scoped:continue
            view=copy.deepcopy(parent_value);view['payload']['jobs']=scoped
            RECONCILE(first.upload.ROOT/'logs'/parent_name,view)

    original_recover=first.recover_own
    print('11月14日仅续跑11月13日原分配素材；成功保留、已提交先核实、剩余继续，再接新50账号及评论。',flush=True)
    with patch.object(first,'DAY',RUN_DAY),patch.object(first,'MATERIAL_DAY',SOURCE_DAY),patch.object(first,'SCOPE',FIRST_SCOPE),patch.object(first,'POINTER',FIRST_POINTER), \
         patch.object(original,'SECOND',SECOND_SCOPE),patch.object(original,'CONTROL',CONTROL),patch.object(original,'SUMMARY','resume-nov13-on-nov14-summary.json'), \
         patch.object(original,'WAVE_POINTER_PREFIX','resume-nov13-on-nov14-second-wave-'), \
         patch.object(original,'DISTRIBUTION',side_effect=bound_distribution),patch.object(first,'freeze',side_effect=freeze_resume), \
         patch.object(first.materials,'distribute',side_effect=resume_distribution), \
         patch.object(first,'recover_own',side_effect=recover),patch.object(first.priority.retry,'run',side_effect=old_retry), \
         patch.object(first,'reconcile',side_effect=reconcile),patch.object(first.priority.actual,'make_finder',side_effect=source_day_finder):
        return original.execute(True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if first.upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已暂停；保留11月13日原批次的续跑进度，重跑同一指令继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
