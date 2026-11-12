"""Explicit Nov-12 recovery of Nov-11 missed targets; preserve all original jobs."""
import contextlib,copy,hashlib,re,shutil,sys,time,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path

if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import publication_preferences as prefs
import scheduled_material_batch as batch
import publish_priority_batch as priority
import scheduled_priority_workflow as workflow
import normal_chrome_batch as normal
import local_file_input as local
import connect_fb09_ten_pages_20261111 as pages
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window
from confirm_all_nov05_20261106 import recover_locks

DAY='2026-11-11';RUN_DATE='2026-11-12';SCHEMA='nov11-missed-explicit-recovery-v1'
PARENT_PREFIX='b98d58f4'
PERSONALS={'fb16','fb17','fb18','fb21','fb24'}
PAIRS={(a,'personal') for a in PERSONALS}|{('fb09',f'page{n:02d}') for n in range(1,11)}
PROOF_FIELDS=('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at')


def require_day():
    if sys.platform!='win32' or datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=RUN_DATE:
        raise ValueError('此命令只在原Windows电脑于北京时间11月12日补发11月11日遗漏素材')
    workflow.require_versions()
    if getattr(upload,'VERIFIED_OWNER_REPLACEMENT_VERSION','')!='1.0-retain-previous-owner-history':raise ValueError('保留旧账号历史的换号兼容修复未安装')
    if local.BATCH_DATE_VERSION!=normal.BATCH_DATE_VERSION or workflow.BATCH_DATE_VERSION!=local.BATCH_DATE_VERSION:
        raise ValueError('本机选文件日期修复未完整安装')


def parent_source():
    pointer=upload.read_json(upload.ROOT/'logs'/('priority-batch-'+DAY+'.json'),{})
    name=pointer.get('manifest','')
    if not re.fullmatch('frozen-material-'+DAY+'-'+PARENT_PREFIX+r'[a-f0-9]{8}\.json',name):raise ValueError('未找到昨天这批30条的确切清单，未按最新文件猜选')
    path=upload.ROOT/'logs'/name;value=upload.read_json(path,{})
    priority.validate(path,value,DAY)
    if pointer.get('sha256')!=value['sha256'] or len(value['payload']['jobs'])!=30:raise ValueError('昨天原批次指纹或条数不一致')
    reports=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if reports.get('manifest')!=path.name or not {j['key'] for j in value['payload']['jobs']}<={a.get('key') for a in reports.get('attempts',[])}:
        raise ValueError('昨天首轮尚未处理完，先完成原流程，不并行开另一批')
    return path,value


def safe_failed_fb17(parent,state):
    jobs=[j for j in parent['payload']['jobs'] if (j['account'],j['target'])==('fb17','personal')]
    if len(jobs)!=1:raise ValueError('昨天缺少唯一fb17原任务')
    job=jobs[0];row=state.get(job['key'],{})
    if (row.get('status')!='failed_before_post' or any(row.get(field) for field in PROOF_FIELDS)
            or (row.get('account'),row.get('target'))!=('fb17','personal')
            or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
            or str(row.get('video','')).replace('\\','/').rsplit('/',1)[-1]!=job['filename']):
        raise ValueError('fb17原视频不是已证实的发布前失败，未重复上传')
    return job


def yesterday_file(stat):
    start=datetime.fromisoformat(DAY+'T00:00:00+08:00').timestamp();cutoff=start+86400
    created=getattr(stat,'st_birthtime',stat.st_ctime)
    return created<cutoff and stat.st_mtime<cutoff and (created>=start or stat.st_mtime>=start)


def snapshot(parent):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{});old=safe_failed_fb17(parent,state)
    selected=[];issues=[]
    for account,target in sorted(PAIRS):
        folder=upload.ROOT/'videos'/account/target/'inbox'
        if not folder.is_dir():issues.append(dict(account=account,target=target,reason='素材目录不存在'));continue
        for video in sorted(folder.glob('*.mp4')):
            stat=video.stat()
            is_fb17=(account,target)==('fb17','personal')
            if is_fb17:
                if video.name!=old['filename']:continue
                if upload.job_key(dict(url=old['url']),video)!=old['key']:raise ValueError('fb17原失败视频内容已变化，未选其他文件代替')
            elif not yesterday_file(stat):
                issues.append(dict(account=account,target=target,filename=video.name,reason='文件日期不能确认为昨天遗留，未选入本次补发'));continue
            if not stat.st_size:continue
            selected.append(dict(account=account,target=target,filename=video.name,video_sha256=batch.file_hash(video),size=stat.st_size,source_old_key=old['key'] if is_fb17 else None))
    return selected,issues,old


def assert_free(account):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    if any(r.get('account')==account and r.get('status') in {'preparing','posting'} for r in state.values() if isinstance(r,dict)):
        raise ValueError(account+'仍有准备或提交中的原任务，未关闭浏览器')


def discover_personal(account):
    from playwright.sync_api import sync_playwright
    profile=upload.ROOT/'profiles'/account
    if not profile.is_dir() or profile.is_symlink():raise ValueError(account+'原登录资料缺失，未新建空白登录')
    assert_free(account);close_selected_window(account)
    probe=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',name='Current personal identity',url='https://www.facebook.com/me',auto_switch_personal=True)
    with sync_playwright() as pw:
        context=normal.launch_normal(pw,probe)
        try:
            page=context.pages[-1] if context.pages else context.new_page()
            people={c['value'] for c in context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and str(c.get('value','')).isdecimal()}
            if len(people)!=1:raise ValueError('未找到唯一登录者，请在该账号原窗口完成登录')
            owner=next(iter(people));url='https://www.facebook.com/profile.php?id='+owner
            upload.navigate_profile(page,url);deadline=time.monotonic()+20;name=None
            while time.monotonic()<deadline:
                upload.checkpoint(page);upload.require_no_advanced_protection(page)
                names={e.inner_text().strip() for e in page.get_by_role('heading',level=1).all() if e.is_visible() and e.inner_text().strip()}
                if len(names)==1:name=next(iter(names));break
                page.wait_for_timeout(250)
            if not name or any(ord(c)<32 for c in name):raise ValueError('本人主页名称尚未唯一加载，未登记')
            entry=dict(probe,name=name,url=url)
            proof=upload.ensure_personal_identity(page,entry)
            if proof.get('session_marker')!=hashlib.sha256(('personal:'+owner).encode()).hexdigest():raise ValueError('核验期间登录者变化')
            return entry,dict(proof,checked_at=datetime.now(timezone.utc).isoformat())
        finally:context.close()


def registration_plan(config,registry,extra,account,entry,proof,old_fb17):
    if account not in PERSONALS or entry.get('account')!=account or entry.get('target')!='personal' or entry.get('type')!='personal':raise ValueError('个人号接入范围不一致')
    upload.validate_entry(entry);identity=upload.target_key(entry['url'])
    if (not identity.startswith('id:') or proof.get('target_url')!=entry['url'] or proof.get('name')!=entry['name']
            or proof.get('method') not in {'personal_actor_id_match','personal_me_redirect_match'} or not proof.get('checked_at')
            or proof.get('session_marker')!=hashlib.sha256(('personal:'+identity[3:]).encode()).hexdigest()):raise ValueError('缺少当前本人主页的确切身份核验')
    if account=='fb17' and identity==upload.target_key(old_fb17['url']):raise ValueError('fb17仍是昨天配置的旧身份，换号尚未生效')
    if not isinstance(registry,dict) or not isinstance(registry.get('accounts'),list):raise ValueError('原账号对应表格式异常')
    for row in config['targets']+registry['accounts']:
        if row.get('account')!=account and upload.target_key(row.get('url',''))==identity:raise ValueError('该本人主页已属于其他编号，未重复接入')
    for row in upload.read_json(upload.ROOT/'logs/publish_state.json',{}).values():
        if isinstance(row,dict) and row.get('account')!=account and isinstance(row.get('identity_validation'),dict) and row['identity_validation'].get('session_marker')==proof['session_marker']:
            raise ValueError('此登录者已有其他账号编号，未通过别名重复登记')
    result,known,manifest=copy.deepcopy((config,registry,extra))
    current=[r for r in result['targets'] if r.get('account')==account]
    stored=[r for r in known['accounts'] if r.get('account')==account]
    if len(current)>1 or len(stored)>1:raise ValueError('该个人号存在多个登记目标，未覆盖')
    for row in current+stored:
        if row.get('type')!='personal' or row.get('target','personal')!='personal':raise ValueError('原账号有公共主页配置，未改成个人主页')
        if account!='fb17' and upload.target_key(row['url'])!=identity:raise ValueError('当前登录者与原登记不一致，只有fb17获准换号')
    if account=='fb24':
        batch_id='personal-20261110-one-fb24';slot=manifest.get('slots',{}).get(account,{})
        if slot.get('batch_id')!=batch_id or manifest.get('batches',{}).get(batch_id,{}).get('accounts')!=['fb24'] or manifest.get('batches',{}).get(batch_id,{}).get('count')!=1:
            raise ValueError('fb24不是这次预留的新账号，未恢复已删除的旧资料')
    mapping={key:entry[key] for key in ('account','target','type','name','url','workflow')}
    same=current and upload.target_key(current[0]['url'])==identity
    row=dict(current[0]) if current else {}
    if not same:
        for key in list(row):
            if key=='prepared_at' or key.startswith('preparation_'):row.pop(key)
        row.update(enabled=False,ai_label=False,excluded_files=[])
    row.update(mapping,identity_verified_at=proof['checked_at'],personal_onboarding_method='verified-personal-onboarding-v1')
    if account=='fb17':row['verified_owner_replacement']=dict(version=upload.VERIFIED_OWNER_REPLACEMENT_VERSION,previous_target_key=upload.target_key(old_fb17['url']),current_target_key=identity,session_marker=proof['session_marker'],verified_at=proof['checked_at'])
    result['targets']=[r for r in result['targets'] if r.get('account')!=account]+[row]
    known_row=dict(stored[0]) if stored else {};known_row.update(mapping,profile='profiles/'+account,inbox='videos/'+account+'/personal/inbox')
    known['accounts']=[r for r in known['accounts'] if r.get('account')!=account]+[known_row]
    if account in manifest.get('slots',{}):manifest['slots'][account].update(state='registered',mapping=mapping,publishing_ready=True,identity_verified_at=proof['checked_at'],identity_method=proof['method'])
    return result,known,manifest


def connect(account,old_fb17,already_locked=False):
    with (contextlib.nullcontext() if already_locked else locked()):
        print('核对当前本人账号：',account,flush=True);entry,proof=discover_personal(account)
        paths=[upload.CONFIG,upload.ROOT/'account_registry.json',upload.ROOT/'additional_personal_accounts.json']
        docs=[upload.read_json(paths[0],{}),upload.read_json(paths[1],{}),upload.read_json(paths[2],dict(schema='additional-personal-logins-v1',slots={},batches={}))]
        updated=registration_plan(*docs,account,entry,proof,old_fb17)
        backup=upload.ROOT/'backups'/('verified-recovery-owner-'+account+'-'+uuid.uuid4().hex[:10]);backup.mkdir(parents=True)
        originals={p:p.read_bytes() if p.is_file() else None for p in paths}
        for p,data in originals.items():
            if data is not None:(backup/p.name).write_bytes(data)
        upload.save_json(backup/'verified-owner.json',dict(account=account,proof=proof))
        try:
            for p,doc in zip(paths,updated):upload.save_json(p,doc)
            if account=='fb24' and not batch.eligible(next(r for r in updated[0]['targets'] if r['account']==account),True,date=RUN_DATE):raise ValueError('fb24仍未通过发布接入校验')
        except BaseException:
            for p,data in originals.items():
                if data is None:p.unlink(missing_ok=True)
                else:shutil.copy2(backup/p.name,p)
            raise
        for folder in ('inbox','completed','failed'):(upload.ROOT/'videos'/account/'personal'/folder).mkdir(parents=True,exist_ok=True)
        print('当前身份已核验并登记：',account,entry['name'],entry['url'],'；原配置备份：',backup,flush=True)


def prepare(parent_path,parent):
    # Hold the original locks through identity registration and source creation,
    # so two invocations cannot freeze overlapping recovery batches.
    with locked():return _prepare_locked(parent_path,parent)


def _prepare_locked(parent_path,parent):
    pointer=upload.ROOT/'logs/nov11-missed-recovery-on-20261112.json'
    with contextlib.nullcontext():
        saved=upload.read_json(pointer,None)
        if saved:
            if saved.get('schema')!=SCHEMA or saved.get('source_sha256')!=parent['sha256'] or not re.fullmatch('frozen-material-'+RUN_DATE+r'-[a-f0-9]{16}\.json',str(saved.get('manifest',''))):raise ValueError('补发续跑指针异常，未另建清单')
            path=upload.ROOT/'logs'/saved['manifest'];value=upload.read_json(path,{})
            if saved.get('sha256')!=value.get('sha256'):raise ValueError('补发指纹不一致')
            validate(path,value,parent);return path,value
        records,issues,old=snapshot(parent)
    blocked=set()
    for account in sorted(PERSONALS):
        if not any(r['account']==account for r in records):continue
        try:connect(account,old,already_locked=True)
        except Exception as error:
            blocked.add(account)
            issues.append(dict(account=account,target='personal',reason=(str(error) or type(error).__name__).split('\n',1)[0]));print('此账号待处理，继续其他账号：',account,str(error).split('\n',1)[0],flush=True)
    with contextlib.nullcontext():
        config=upload.read_json(upload.CONFIG,{});state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        content=prefs.content_policy(RUN_DATE);policy=prefs.load(RUN_DATE);jobs=[];seen=set();reserved=batch.previous_plan_keys(RUN_DATE)
        expected_pages={target:(name,number) for target,name,number in pages.PAGES}
        backup=upload.ROOT/'backups'/('recovery-captions-'+uuid.uuid4().hex[:10])
        for record in records:
            try:
                if record['account'] in blocked:continue
                matches=[e for e in config['targets'] if (e['account'],e['target'])==(record['account'],record['target'])]
                if len(matches)!=1:raise ValueError('目标仍未唯一登记')
                entry=matches[0];upload.validate_entry(entry)
                if entry['account']=='fb09' and (entry['name'],upload.target_key(entry['url']))!=(expected_pages[entry['target']][0],'id:'+expected_pages[entry['target']][1]):raise ValueError('fb09主页名称或ID与用户给定对应关系不一致')
                if not batch.eligible(entry,True,date=RUN_DATE):raise ValueError('账号尚未完成发布接入')
                video=upload.inbox_for(entry)/record['filename']
                if batch.file_hash(video)!=record['video_sha256'] or video.stat().st_size!=record['size']:raise ValueError('昨日选定文件内容已变化')
                key=upload.job_key(entry,video)
                if key in seen:continue
                if key in state:
                    if key!=old['key'] or state[key].get('status')!='failed_before_post' or any(state[key].get(f) for f in PROOF_FIELDS):continue
                if key in {j['key'] for j in parent['payload']['jobs']} and key!=old['key']:raise ValueError('素材属于昨天已处理任务，未重复上传')
                if key in reserved and key!=old['key']:raise ValueError('素材已属于旧冻结清单，未重传')
                caption=video.with_suffix('.txt');text=content['payload']['caption']
                if not caption.is_file() or caption.read_text(encoding='utf-8-sig',errors='replace').strip()!=text:
                    backup.mkdir(parents=True,exist_ok=True)
                    if caption.is_file():dest=backup/caption.relative_to(upload.ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(caption,dest)
                    prefs.atomic_caption(caption,text)
                jobs.append(dict(record,account=entry['account'],target=entry['target'],key=key,url=entry['url'],entry_sha256=batch.digest(entry),caption_text=text,caption_sha256=batch.file_hash(caption),video_size=record['size'],publication_content_sha256=content['sha256']))
                seen.add(key)
            except Exception as error:issues.append(dict(record,reason=str(error)))
        if not jobs:
            upload.save_json(upload.ROOT/'logs/nov11-missed-recovery-issues.json',dict(schema=SCHEMA,issues=issues));raise ValueError('没有通过核验的昨日遗漏素材；问题已记录，未选今天新素材代替')
        now=datetime.now(timezone.utc);payload=dict(schema=batch.SCHEMA,date=RUN_DATE,start=(now.astimezone(batch.BJ)+timedelta(seconds=75)).isoformat(),requested_start=now.astimezone(batch.BJ).isoformat(),ai_label=False,include_fb10_pages=True,excluded_accounts=sorted(batch.excluded_accounts(RUN_DATE)),comment_text=content['payload']['comment'],jobs=jobs,publication_preferences_sha256=policy['sha256'],publication_content_sha256=content['sha256'],comment_retry_policy=priority.COMMENT_RECOVERY_VERSION,recovery_schema=SCHEMA,source_manifest=parent_path.name,source_sha256=parent['sha256'],source_date=DAY)
        checksum=batch.digest(payload);path=upload.ROOT/'logs'/('frozen-material-'+RUN_DATE+'-'+checksum[:16]+'.json')
        value=dict(payload=payload,sha256=checksum,created_at=now.isoformat(),issues=issues,workflow='future-video-comments-v1',auto_retry_policy=priority.retry.POLICY,comment_timing=priority.TIMING,priority_workflow=priority.PRIORITY_WORKFLOW_VERSION,report_format='text',scheduled_priority_runner=workflow.VERSION,browser_launch_mode=normal.NORMAL_CHROME_VERSION,local_file_input_mode=local.VERSION)
        validate(path,value,parent);upload.save_json(path,value);upload.save_json(pointer,dict(schema=SCHEMA,manifest=path.name,sha256=checksum,source_sha256=parent['sha256']))
        return path,value


def validate(path,value,parent):
    workflow.validate(path,value);payload=value['payload']
    if payload.get('date')!=RUN_DATE or payload.get('recovery_schema')!=SCHEMA or payload.get('source_sha256')!=parent['sha256'] or payload.get('source_date')!=DAY:
        raise ValueError('昨日遗漏补发范围校验失败')
    old=next(j for j in parent['payload']['jobs'] if j['account']=='fb17')
    parent_keys={j['key'] for j in parent['payload']['jobs']}
    for job in payload['jobs']:
        if (job['account'],job['target']) not in PAIRS or job['key'] in parent_keys-{old['key']}:raise ValueError('补发混入已成功或待核实的昨天原任务')
        if job['account']=='fb17' and (job.get('source_old_key')!=old['key'] or job['filename']!=old['filename'] or upload.target_key(job['url'])==upload.target_key(old['url'])):raise ValueError('fb17未绑定昨天失败素材和已换号的新身份')


def execute():
    require_day();recover_locks(upload.ROOT);parent_path,parent=parent_source()
    path,value=prepare(parent_path,parent);validate(path,value,parent)
    print('只补昨天遗漏及fb17明确失败的素材：',len(value['payload']['jobs']),'条；不重传昨天15条成功或14条待核实视频。',flush=True)
    for issue in value.get('issues',[]):print('暂未选入：',issue.get('account'),issue.get('filename',''),str(issue.get('reason','')).split('\n',1)[0],flush=True)
    original=upload.launch_context;upload.launch_context=normal.launcher_for_jobs(value['payload']['jobs'],date=RUN_DATE)
    try:
        with priority.daily.keep_awake():
            while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
            with locked():
                validate(path,upload.read_json(path,{}),parent)
                state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
                fresh=[j for j in value['payload']['jobs'] if j['key'] not in state and not any(r.get('account')==j['account'] and r.get('status') in {'preparing','posting'} for r in state.values())]
                if fresh:
                    from playwright.sync_api import sync_playwright
                    job=fresh[0];entry=dict(priority.daily.configured(job),_local_file_selfcheck=True);close_selected_window(entry['account'])
                    with sync_playwright() as pw:
                        context=upload.launch_context(pw,entry)
                        try:local.self_check(context,job)
                        finally:context.close()
            batch.run(path,defer_comments=True,resume=True,retry_before_post=True)
            priority.retry.run(path)
            finder=priority.daily.find_published;priority.daily.find_published=priority.actual.make_finder(value['payload']['jobs'],True);rows=[]
            try:priority.daily.backfill(value,None,only_keys={j['key'] for j in value['payload']['jobs']},rows=rows,future_only=True,reporter=lambda *_:priority.comment_report(path,value,rows))
            finally:priority.daily.find_published=finder
            priority.comment_retry.run(path,reporter=lambda manifest,rows,out:priority.comment_report(path,value,rows))
            report=upload.read_json(path.with_name(path.stem+'-results.json'),{});batch.results(path,value,report.get('attempts',[]),None,final=True)
    finally:upload.launch_context=original
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    return 0 if not value.get('issues') and all(state.get(j['key'],{}).get('status')=='published' and state[j['key']].get('comment_status') in {'sent','already_present'} for j in value['payload']['jobs']) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if upload.ROOT.resolve()!=Path(sys.argv[1]).resolve() or '--real-footage' not in sys.argv[2:]:raise ValueError('需使用原目录和昨天已确认的实拍设置')
        logs=upload.ROOT/'logs';logs.mkdir(exist_ok=True)
        with (logs/'nov11-missed-recovery-20261112.log').open('a',encoding='utf-8') as log:
            with contextlib.redirect_stdout(batch.Tee(sys.stdout,log)),contextlib.redirect_stderr(batch.Tee(sys.stderr,log)):raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止；原发布记录及本次补发指针保留，重跑继续同一补发批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
