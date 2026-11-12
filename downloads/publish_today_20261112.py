"""Nov12 new videos only, fb01-24, safe retry then comments; old retries cancelled."""
import contextlib
import copy
import re
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import personal_owner_registration as personal

old=personal.old
upload=old.upload
DAY='2026-11-12'
SCOPE='nov12-current-materials-fb01-to-fb24-v1'
SOURCE_PREFIX='22d011ce'
ALLOWED={f'fb{n:02d}' for n in range(1,25)}
SKIP=[f'fb{n:02d}' for n in range(25,75)]


def previous_jobs():
    jobs={}
    for path in (upload.ROOT/'logs').glob('frozen-material-????-??-??-*.json'):
        match=re.fullmatch(r'frozen-material-(\d{4}-\d{2}-\d{2})-([a-f0-9]{16})\.json',path.name)
        if not match or match[1]>DAY:continue
        value=upload.read_json(path,{})
        payload=value.get('payload',{})
        if payload.get('schema')!=old.batch.SCHEMA:continue
        if value.get('sha256')!=old.batch.digest(payload) or not value['sha256'].startswith(match[2]) or payload.get('date')!=match[1]:
            raise ValueError('原冻结清单异常，未将旧素材作为今天新视频：'+path.name)
        for job in payload.get('jobs',[]):
            pair=(job.get('account'),job.get('target'))
            if pair[0] in ALLOWED:jobs.setdefault(pair,[]).append(job)
    return jobs


def today_controller(original):
    path=upload.ROOT/'logs/nov12-current-materials-original-accounts.json'
    saved=upload.read_json(path,None)
    if saved:
        payload=saved.get('payload',{})
        if (payload.get('scope')!=SCOPE or payload.get('date')!=DAY or payload.get('source_sha256')!=original['sha256']
                or saved.get('sha256')!=old.batch.digest(payload) or not isinstance(saved.get('plans'),list)):
            raise ValueError('今天新素材续跑记录异常，未重新扫描加入其他视频。')
        return path,saved
    config=upload.read_json(upload.CONFIG,{})
    pairs={(e['account'],e['target']) for e in config.get('targets',[]) if e.get('account') in ALLOWED}
    pairs|={(a,'personal') for a in {'fb17','fb18','fb21','fb24'} if (upload.ROOT/'profiles'/a).is_dir()}
    previous=previous_jobs();records=[];excluded=[]
    old_issues={(r.get('account'),r.get('target'),r.get('video_sha256')) for r in original.get('issues',[]) if r.get('video_sha256')}
    for account,target in sorted(pairs):
        if not re.fullmatch(r'personal|page[0-9]{2,}',target):raise ValueError('发布目标目录格式异常。')
        folder=upload.ROOT/'videos'/account/target/'inbox'
        for video in sorted(folder.glob('*.mp4'),key=upload.queue_order):
            if video.is_symlink():raise ValueError('视频是文件链接，未加入今天清单。')
            stat=video.stat();checksum=old.batch.file_hash(video)
            prior_jobs=previous.get((account,target),[])
            known=any(j.get('video_sha256')==checksum for j in prior_jobs)
            if not known:
                keys_by_url={}
                for job in prior_jobs:
                    url=job['url']
                    key=keys_by_url.setdefault(url,None)
                    if key is None:key=keys_by_url[url]=upload.job_key(dict(url=url),video)
                    if key==job['key']:known=True;break
            if known or (account,target,checksum) in old_issues:
                excluded.append(dict(account=account,target=target,filename=video.name,reason='以前已冻结或明确属于原遗漏素材，不混入今天新批次'))
                continue
            after=video.stat()
            if not stat.st_size or (stat.st_size,stat.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError('今天视频为空或仍在复制：'+str(video))
            records.append(dict(account=account,target=target,filename=video.name,video_sha256=checksum,size=stat.st_size))
    payload=dict(scope=SCOPE,date=DAY,source_sha256=original['sha256'],records=records,skip_new_accounts=SKIP,cancelled_old_personal_retries=['fb17','fb18','fb21'])
    value=dict(payload=payload,sha256=old.batch.digest(payload),plans=[],excluded=excluded,setup_issues=[])
    upload.save_json(path,value)
    print('已锁定今天新素材：',len(records),'条；后加入或变化的文件不会自动混入本次发布。',flush=True)
    return path,value


def prepare_wave(control_path,control,blocked):
    snapshots={(r['account'],r['target'],r['filename']):r for r in control['payload']['records']}
    config=upload.read_json(upload.CONFIG,{})
    previous=previous_jobs();excluded={j['key']:'原冻结清单' for rows in previous.values() for j in rows}
    for entry in config.get('targets',[]):
        if entry.get('account') not in ALLOWED:continue
        for video in upload.inbox_for(entry).glob('*.mp4'):
            record=snapshots.get((entry['account'],entry['target'],video.name))
            if record is None or old.batch.file_hash(video)!=record['video_sha256']:
                excluded[upload.job_key(entry,video)]='不属于今天已锁定的新素材'
    eligible=old.batch.eligible
    def allowed(entry,include_pages,date=None):return entry.get('account') in ALLOWED-blocked and eligible(entry,include_pages,date=date)
    save=upload.save_json
    def defer_draft(path,value):
        if Path(path).name.startswith('frozen-material-'+DAY+'-') and value.get('payload',{}).get('schema')==old.batch.SCHEMA:return
        return save(path,value)
    try:
        with patch.object(old.batch,'eligible',side_effect=allowed),patch.object(old.batch,'previous_plan_keys',return_value=excluded),patch.object(upload,'save_json',side_effect=defer_draft):
            path,value=old.batch.freeze(DAY,datetime.now(timezone.utc).astimezone(old.batch.BJ).strftime('%H:%M'),True,
                                       old.prefs.content_policy(DAY)['payload']['comment'],datetime.now(timezone.utc),report_format='text',exclude_previous_plans=True)
    except ValueError as error:
        if '没有可冻结的全新视频' in str(error):return None
        raise
    value.update(workflow='future-video-comments-v1',auto_retry_policy=old.priority.retry.POLICY,comment_timing=old.priority.TIMING,
                 priority_workflow=old.priority.PRIORITY_WORKFLOW_VERSION,report_format='text',scheduled_priority_runner=old.workflow.VERSION,
                 browser_launch_mode=old.normal.NORMAL_CHROME_VERSION,local_file_input_mode=old.local.VERSION)
    value['payload'].update(current_material_scope=SCOPE,current_snapshot_sha256=control['sha256'],skip_new_accounts=SKIP,
                            comment_retry_policy=old.priority.COMMENT_RECOVERY_VERSION)
    for job in value['payload']['jobs']:
        record=snapshots[(job['account'],job['target'],job['filename'])]
        video=upload.ROOT/'videos'/job['account']/job['target']/'inbox'/job['filename']
        if old.batch.file_hash(video)!=record['video_sha256'] or video.stat().st_size!=record['size']:
            raise ValueError('今天原视频在冻结期间变化，未替换发布素材。')
        job['video_sha256']=record['video_sha256']
    value['sha256']=old.batch.digest(value['payload'])
    new_path=path.with_name('frozen-material-'+DAY+'-'+value['sha256'][:16]+'.json')
    old.workflow.validate(new_path,value);upload.save_json(new_path,value)
    control['plans'].append(dict(manifest=new_path.name,sha256=value['sha256']))
    upload.save_json(control_path,control)
    return new_path,value


def load_today_plans(control):
    result=[]
    snapshots={(r['account'],r['target'],r['filename']):r for r in control['payload']['records']}
    names={r.get('manifest') for r in control['plans']}
    # Recover a committed owned plan if a crash preceded the pointer update.
    for candidate in (upload.ROOT/'logs').glob('frozen-material-'+DAY+'-*.json'):
        value=upload.read_json(candidate,{})
        if candidate.name not in names and value.get('payload',{}).get('current_material_scope')==SCOPE and value['payload'].get('current_snapshot_sha256')==control['sha256']:
            old.workflow.validate(candidate,value)
            control['plans'].append(dict(manifest=candidate.name,sha256=value['sha256']));names.add(candidate.name)
    for row in control['plans']:
        name=row.get('manifest','')
        if not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json',name):raise ValueError('今天发布清单名称异常。')
        path=upload.ROOT/'logs'/name;value=upload.read_json(path,{})
        old.workflow.validate(path,value)
        if (row.get('sha256')!=value['sha256'] or value['payload'].get('current_material_scope')!=SCOPE
                or value['payload'].get('current_snapshot_sha256')!=control['sha256']
                or any(j['account'] not in ALLOWED for j in value['payload']['jobs'])):raise ValueError('今天发布范围或素材快照不一致。')
        if any((j['account'],j['target'],j['filename']) not in snapshots or j.get('video_sha256')!=snapshots[(j['account'],j['target'],j['filename'])]['video_sha256'] for j in value['payload']['jobs']):
            raise ValueError('今天清单包含非原快照的视频，未发布。')
        result.append((path,value))
    return result


def old_sources():
    _,parent=old.parent_source()
    pointer=upload.read_json(upload.ROOT/'logs/nov11-identity-repair-on-20261112.json',{})
    name=pointer.get('manifest','')
    if not re.fullmatch('frozen-material-'+DAY+'-'+SOURCE_PREFIX+r'[a-f0-9]{8}\.json',name):raise ValueError('未找到原任务来源记录，未猜选旧素材。')
    path=upload.ROOT/'logs'/name;original=upload.read_json(path,{})
    old.workflow.validate(path,original)
    if pointer.get('sha256')!=original['sha256']:raise ValueError('原任务来源指纹不一致。')
    return parent,original


def ready_personals(parent):
    blocked=set();issues=[]
    previous=next(j for j in parent['payload']['jobs'] if (j['account'],j['target'])==('fb17','personal'))
    for account in ('fb17','fb18','fb21','fb24'):
        config=upload.read_json(upload.CONFIG,{})
        row=next((r for r in config['targets'] if (r.get('account'),r.get('target'))==(account,'personal')),None)
        if row and row.get('personal_route_validation',{}).get('version')==personal.routes.VERSION and old.batch.eligible(row,True,date=DAY):continue
        try:
            with patch.object(old,'discover_personal',side_effect=personal.discover),patch.object(old,'registration_plan',side_effect=personal.register_alias):
                old.connect(account,previous,already_locked=True)
        except Exception as error:
            blocked.add(account);issues.append(dict(account=account,reason=str(error).split('\n',1)[0]))
            print('此账号待本人身份核验，继续其他原有账号：',account,issues[-1]['reason'],flush=True)
    return blocked,issues


def run_video(path,value,retry=False):
    if datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):print('等待视频及统一文案写入稳定后开始；约一分钟，请保持窗口打开。',flush=True)
    while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
    with personal.launcher(value):old.batch.run(path,defer_comments=True,resume=True,retry_before_post=retry)


def execute(real_footage):
    if not real_footage:raise ValueError('今天新素材尚未确认全部实拍。')
    old.require_day();old.recover_locks(upload.ROOT)
    content=old.prefs.content_policy(DAY)
    if not content or content['payload']['caption']!=old.prefs.EVERYDAY_CAPTION or content['payload']['comment']!=old.prefs.EVERYDAY_COMMENT:
        raise ValueError('正文或评论与之前确认的实拍文案不一致，未替换。')
    with old.locked():
        parent,original=old_sources()
        blocked,issues=ready_personals(parent)
        today_path,today=today_controller(original)
        today['setup_issues']=issues;upload.save_json(today_path,today)
        prepare_wave(today_path,today,blocked)
        new_plans=load_today_plans(today)
        upload.save_json(today_path,today)
        config=upload.read_json(upload.CONFIG,{})
        pages={(e['account'],e['target']) for e in config['targets'] if e.get('account') in ALLOWED and e.get('type')=='page'}
    all_plans=new_plans
    print('今天只发布fb01–fb24及其已登记公共主页；fb25–fb74本次全部跳过。',flush=True)
    print('今天新视频：',sum(len(v['payload']['jobs']) for p,v in new_plans),'条；昨天fb17/fb18/fb21原素材不补发。全部实拍，AI标签关闭。',flush=True)
    with old.priority.daily.keep_awake(),personal.routes.numeric.scoped(pages),personal.routes.scoped(ALLOWED),personal.editor.installed():
        for path,value in new_plans:run_video(path,value)
        for path,value in all_plans:
            with personal.launcher(value):old.priority.retry.run(path)
        for path,value in all_plans:
            finder=old.priority.daily.find_published;old.priority.daily.find_published=old.priority.actual.make_finder(value['payload']['jobs'],True)
            rows=[]
            try:
                with personal.launcher(value):old.priority.daily.backfill(value,None,only_keys={j['key'] for j in value['payload']['jobs']},rows=rows,future_only=True,
                    reporter=lambda *_:old.priority.comment_report(path,value,rows))
            finally:old.priority.daily.find_published=finder
        for path,value in all_plans:
            with personal.launcher(value):old.priority.comment_retry.run(path,reporter=lambda m,r,o:old.priority.comment_report(path,value,r))
        final=[]
        for path,value in all_plans:
            report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
            final+=old.batch.results(path,value,report.get('attempts',[]),None,final=True)
        for issue in issues:print('仍待处理：',issue['account'],issue['reason'],flush=True)
    return 0 if final and not issues and all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in final) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute('--real-footage' in sys.argv[2:]))
    except KeyboardInterrupt:print('已暂停，保留今天新素材、发布及评论进度，重跑继续原清单。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
