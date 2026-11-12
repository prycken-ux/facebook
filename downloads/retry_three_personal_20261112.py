"""Recover only fb17/fb18/fb21 original skipped videos after proving personal URLs."""
import contextlib
import copy
import hashlib
import re
import shutil
import sys
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import recover_nov11_missed_20261112 as old
import personal_owner_routes as routes
import page_reel_ai_compat as editor

upload=old.upload
DAY='2026-11-12'
SCHEMA='nov11-three-personal-recovery-v1'
SOURCE_PREFIX='22d011ce'
RECORDS={
 'fb17':('1109 (1)-2.mp4','b58ff02e51fbfbdde32112e9d1c51b4057c6c9a17d3f805dd1210375fc325582'),
 'fb18':('1109 (1)-3.mp4','0bee2a35bdb140a3a366751d97b105498cc6b1b32f8f806c3ab60afbaec3e945'),
 'fb21':('s17.mp4','4c02940974d8c5350481af783edbcc34679ed0f21de18efad607560f7ef6fb30'),
}
BASE_REGISTRATION=old.registration_plan


def source():
    parent_path,parent=old.parent_source()
    pointer=upload.read_json(upload.ROOT/'logs/nov11-identity-repair-on-20261112.json',{})
    name=pointer.get('manifest','')
    if not re.fullmatch('frozen-material-'+DAY+'-'+SOURCE_PREFIX+r'[a-f0-9]{8}\.json',name):raise ValueError('未找到22d011ce这批确切遗漏记录。')
    path=upload.ROOT/'logs'/name;value=upload.read_json(path,{})
    old.workflow.validate(path,value)
    if pointer.get('sha256')!=value['sha256']:raise ValueError('原遗漏清单指纹不一致。')
    records={}
    for account,(filename,checksum) in RECORDS.items():
        matches=[r for r in value.get('issues',[]) if r.get('account')==account and r.get('target')=='personal'
                 and r.get('filename')==filename and r.get('video_sha256')==checksum]
        if len(matches)!=1:raise ValueError('未找到唯一原视频遗漏记录：'+account)
        records[account]=copy.deepcopy(matches[0])
    return parent_path,parent,path,value,records


def register_alias(config,registry,manifest,account,entry,proof,old_fb17):
    config,registry,manifest=copy.deepcopy((config,registry,manifest))
    aliases=set(proof.get('verified_aliases',[]))
    if account!='fb17':
        for row in config['targets']+registry['accounts']:
            if row.get('account')==account and upload.target_key(row.get('url','')) in aliases:
                row['url']=entry['url']  # Same proven owner; canonicalize, do not replace a person.
    result=BASE_REGISTRATION(config,registry,manifest,account,entry,proof,old_fb17)
    row=next(r for r in result[0]['targets'] if r['account']==account)
    row['personal_route_validation']=dict(version=routes.VERSION,aliases=sorted(aliases),route_method=proof['route_method'],checked_at=proof['checked_at'])
    return result


def discover(account):
    from playwright.sync_api import sync_playwright
    profile=upload.ROOT/'profiles'/account
    if not profile.is_dir() or profile.is_symlink():raise ValueError('原登录资料缺失，未创建空白资料。')
    old.assert_free(account);old.close_selected_window(account)
    probe=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',name='Current personal owner',url='https://www.facebook.com/me',auto_switch_personal=True)
    with sync_playwright() as pw:
        context=old.normal.launch_normal(pw,probe)
        try:
            page=context.pages[-1] if context.pages else context.new_page()
            people={c['value'] for c in context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and str(c.get('value','')).isdecimal()}
            if len(people)!=1:raise ValueError('当前登录身份不唯一，请在该编号原窗口完成登录。')
            owner=next(iter(people));entry=dict(probe,url='https://www.facebook.com/profile.php?id='+owner)
            upload.navigate_profile(page,entry['url'])
            proof=routes.ensure_personal(page,entry)
            name=None;deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                routes.stable_actor(page,entry,proof['recovery_login_marker'])
                name=routes.numeric.public_name(page)
                if name:break
                page.wait_for_timeout(200)
            if not name:
                print('本人身份已核验，但显示名称未自动识别：',account,entry['url'],flush=True)
                name=input('填写当前窗口的本人主页名称；S跳过，Q结束：').strip()
                if name.upper()=='Q':raise KeyboardInterrupt
                if name.upper()=='S':raise ValueError('用户跳过本人名称登记。')
            if not name or len(name)>200 or any(ord(c)<32 for c in name):raise ValueError('本人主页名称无效。')
            entry['name']=name;proof.update(name=name,checked_at=datetime.now(timezone.utc).isoformat())
            if routes.stable_actor(page,entry,proof['recovery_login_marker'])!=proof['session_marker']:
                raise ValueError('登记期间本人身份变化。')
            return entry,proof
        finally:context.close()


def controller(value,records):
    path=upload.ROOT/'logs/nov11-three-personal-recovery-20261112.json'
    payload=dict(schema=SCHEMA,date=DAY,source_sha256=value['sha256'],records=records)
    doc=upload.read_json(path,dict(payload=payload,sha256=old.batch.digest(payload),jobs={},errors={}))
    if (not isinstance(doc,dict) or doc.get('payload')!=payload or doc.get('sha256')!=old.batch.digest(payload)
            or not isinstance(doc.get('jobs'),dict) or not set(doc['jobs'])<=set(RECORDS) or not isinstance(doc.get('errors'),dict)):
        raise ValueError('这三个个人号的续跑记录异常，未另开重复任务。')
    upload.save_json(path,doc)
    return path,doc


def validate_one(path,value,account,record,original):
    old.workflow.validate(path,value)
    payload=value['payload'];jobs=payload['jobs']
    if (payload.get('three_personal_recovery')!=SCHEMA or payload.get('three_personal_source_sha256')!=original['sha256']
            or len(jobs)!=1 or (jobs[0].get('account'),jobs[0].get('target'))!=(account,'personal')
            or jobs[0].get('filename')!=record['filename'] or jobs[0].get('video_sha256')!=record['video_sha256']):
        raise ValueError('个人号补发清单与原遗漏素材不一致。')


def prepare_one(account,record,original,parent,control_path,control):
    saved=control['jobs'].get(account)
    if saved:
        name=saved.get('manifest','')
        if not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json',name):raise ValueError('个人号续跑清单名异常。')
        path=upload.ROOT/'logs'/name;value=upload.read_json(path,{})
        if saved.get('sha256')!=value.get('sha256'):raise ValueError('个人号续跑指纹不一致。')
        validate_one(path,value,account,record,original)
        return path,value
    video=upload.ROOT/'videos'/account/'personal/inbox'/record['filename']
    if not video.is_file() or video.is_symlink() or old.batch.file_hash(video)!=record['video_sha256'] or video.stat().st_size!=record['size']:
        raise ValueError('原遗漏视频缺失或内容变化，未选择其他素材代替。')
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    old_fb17=old.safe_failed_fb17(parent,state)
    # Retain every known alias so changing its spelling cannot evade a prior
    # submitted video record. The original fb17 failure must remain pre-Post.
    before=upload.read_json(upload.CONFIG,{})
    old_urls=[r['url'] for r in before.get('targets',[]) if r.get('account')==account and r.get('target')=='personal']
    with patch.object(old,'discover_personal',side_effect=discover),patch.object(old,'registration_plan',side_effect=register_alias):
        old.connect(account,old_fb17,already_locked=True)
    rows=[r for r in upload.read_json(upload.CONFIG,{}).get('targets',[]) if (r.get('account'),r.get('target'))==(account,'personal')]
    if len(rows)!=1:raise ValueError('本人主页未唯一登记。')
    entry=rows[0]
    if not old.batch.eligible(entry,True,date=DAY):raise ValueError('该个人号未通过发布接入。')
    urls=[entry['url']]+old_urls
    urls+=['https://www.facebook.com/'+k[5:] for k in entry['personal_route_validation']['aliases']]
    for url in urls:
        key=upload.job_key(dict(url=url),video)
        row=state.get(key)
        if row is not None:
            if row.get('status')!='failed_before_post' or has_proof(row):raise ValueError('这条视频已有提交、成功或待核实记录，未因网址变化重复上传。')
    key=upload.job_key(entry,video)
    if key in state and state[key].get('today_first_retry_used'):raise ValueError('该视频已有本次重试记录，先核实原结果。')
    if old.batch.file_hash(video)!=record['video_sha256']:raise ValueError('身份核验期间原视频变化。')
    content=old.prefs.content_policy(DAY,original['payload']['publication_content_sha256'])
    text=content['payload']['caption'];caption=video.with_suffix('.txt')
    if not caption.is_file() or caption.read_text(encoding='utf-8-sig',errors='replace').strip()!=text:
        backup=upload.ROOT/'backups'/('three-personal-caption-'+uuid.uuid4().hex[:10]);backup.mkdir(parents=True)
        if caption.is_file():shutil.copy2(caption,backup/caption.name)
        old.prefs.atomic_caption(caption,text)
    job=dict(record,key=key,url=entry['url'],entry_sha256=old.batch.digest(entry),caption_text=text,
             caption_sha256=old.batch.file_hash(caption),video_size=record['size'],publication_content_sha256=content['sha256'])
    payload=dict(original['payload'],jobs=[job],start=datetime.now(timezone.utc).astimezone(old.batch.BJ).isoformat(),
                 three_personal_recovery=SCHEMA,three_personal_source_sha256=original['sha256'])
    checksum=old.batch.digest(payload);path=upload.ROOT/'logs'/('frozen-material-'+DAY+'-'+checksum[:16]+'.json')
    value=dict(original,payload=payload,sha256=checksum,issues=[],created_at=datetime.now(timezone.utc).isoformat())
    validate_one(path,value,account,record,original)
    upload.save_json(path,value);control['jobs'][account]=dict(manifest=path.name,sha256=checksum)
    control['errors'].pop(account,None);upload.save_json(control_path,control)
    return path,value


def has_proof(value):
    if isinstance(value,list):return any(has_proof(v) for v in value)
    if not isinstance(value,dict):return False
    return any(value.get(k) for k in old.PROOF_FIELDS) or any(has_proof(v) for v in value.values() if isinstance(v,(dict,list)))


@contextlib.contextmanager
def launcher(value):
    original=upload.launch_context
    upload.launch_context=old.normal.launcher_for_jobs(value['payload']['jobs'],date=DAY)
    try:yield
    finally:upload.launch_context=original


def execute():
    old.require_day();old.recover_locks(upload.ROOT)
    with old.locked():
        _,parent,_,original,records=source()
        control_path,control=controller(original,records)
    plans=[]
    with old.priority.daily.keep_awake(),routes.scoped(set(RECORDS)),editor.installed():
        for account in sorted(RECORDS):
            try:
                with old.locked():path,value=prepare_one(account,records[account],original,parent,control_path,control)
                plans.append((path,value))
                print('\n只发布指定原视频：',account,records[account]['filename'],flush=True)
                with launcher(value):old.batch.run(path,defer_comments=True,resume=True,retry_before_post=True)
            except KeyboardInterrupt:raise
            except Exception as error:
                with old.locked():
                    control['errors'][account]=(str(error) or type(error).__name__).split('\n',1)[0]
                    upload.save_json(control_path,control)
                print('此账号未完成，保留记录并继续其他账号：',account,control['errors'][account],flush=True)
        for path,value in plans:
            with launcher(value):old.priority.retry.run(path)
        for path,value in plans:
            finder=old.priority.daily.find_published
            old.priority.daily.find_published=old.priority.actual.make_finder(value['payload']['jobs'],True)
            rows=[]
            try:
                with launcher(value):
                    old.priority.daily.backfill(value,None,only_keys={value['payload']['jobs'][0]['key']},rows=rows,future_only=True,
                                                reporter=lambda *_:old.priority.comment_report(path,value,rows))
                    old.priority.comment_retry.run(path,reporter=lambda m,r,o:old.priority.comment_report(path,value,r))
            finally:old.priority.daily.find_published=finder
        print('\n这三个个人号最终视频结果：',flush=True)
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        names={'published':'发布成功','failed_before_post':'发布前失败','needs_review':'待核实','posting':'已提交待核实','preparing':'准备中待核实'}
        for account in sorted(RECORDS):
            saved=control['jobs'].get(account)
            if not saved:print(account,records[account]['filename'],'未发布：',control['errors'].get(account,'未完成身份核验'),flush=True);continue
            path=upload.ROOT/'logs'/saved['manifest'];value=upload.read_json(path,{})
            key=value['payload']['jobs'][0]['key'];row=state.get(key,{})
            print(account,records[account]['filename'],names.get(row.get('status'),'未开始'),'；评论：',row.get('comment_status','未开始'),flush=True)
            report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
            old.batch.results(path,value,report.get('attempts',[]),None,final=True)
    final=[state.get(upload.read_json(upload.ROOT/'logs'/v['manifest'],{})['payload']['jobs'][0]['key'],{}) for v in control['jobs'].values()]
    return 0 if len(final)==3 and all(r.get('status')=='published' and r.get('comment_status') in {'sent','already_present'} for r in final) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if upload.ROOT.resolve()!=Path(sys.argv[1]).resolve() or '--real-footage' not in sys.argv[2:]:raise ValueError('需使用原目录及已确认的原视频实拍设置。')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已暂停；已提交结果和三个账号进度保留，重跑只继续未完成项目。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
