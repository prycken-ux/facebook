"""One source-bound grant for the user's 18 incomplete Nov25 targets."""
import contextlib,copy,re,uuid,os
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import chrome_profile_guard as profiles
import publication_file_state_20261124 as files

DAY='2026-11-25'
REQUEST_PREFIX='bab707146073f17b'
GRANT_SUFFIX='-user-resume18-20261126-v1'
RESULT='logs/nov25-resume18-on-nov26-results.json'
EXPECTED={('fb01', 'page01'): '20261125-b4ca255d-eligible60-001_2026-05-22_7642647165650652446.mp4', ('fb02', 'page01'): '20261125-b4ca255d-eligible60-01_7711306545920773406.mp4', ('fb04', 'personal'): '20261125-b4ca255d-eligible60-02_7710225984598936863.mp4', ('fb06', 'page01'): '20261125-b4ca255d-eligible60-03_7710226204153908511.mp4', ('fb07', 'personal'): '20261125-b4ca255d-eligible60-004_2026-05-26_7643756923652672799.mp4', ('fb08', 'personal'): '20261125-b4ca255d-eligible60-04_7710225083406535967.mp4', ('fb10', 'page01'): '20261125-b4ca255d-eligible60-12_2026-11-20_7710224681046986014.mp4', ('fb10', 'page02'): '20261125-b4ca255d-eligible60-013_2026-06-08_7648968071163432222.mp4', ('fb10', 'page03'): '20261125-b4ca255d-eligible60-13_2026-11-21_7710226172415724830.mp4', ('fb10', 'page04'): '20261125-b4ca255d-eligible60-014_2026-06-10_7649716543454039326.mp4', ('fb10', 'page05'): '20261125-b4ca255d-eligible60-14_2026-11-22_7710631034169150751.mp4', ('fb10', 'page06'): '20261125-b4ca255d-eligible60-015_2026-06-10_7649715196394622238.mp4', ('fb10', 'page07'): '20261125-b4ca255d-eligible60-15_2026-11-23_7711320299819617567.mp4', ('fb10', 'page08'): '20261125-b4ca255d-eligible60-016_2026-06-11_7650077525078576415.mp4', ('fb10', 'page09'): '20261125-b4ca255d-eligible60-017_2026-06-11_7650079026337352991.mp4', ('fb10', 'page10'): '20261125-b4ca255d-eligible60-018_2026-06-11_7650078411183918367.mp4', ('fb10', 'personal'): '20261125-b4ca255d-eligible60-012_2026-06-05_7647858793564409119.mp4', ('fb11', 'personal'): '20261125-b4ca255d-eligible60-019_2026-06-12_7650450520615718174.mp4'}
DENY=re.compile(r'captcha|checkpoint|verification|log[ -]?in|sign[ -]?in|安全验证|验证码|登录|身份不一致|账号限制',re.I)
RECOVER=re.compile(r'Timeout|ERR_(?:ABORTED|PROXY_CONNECTION_FAILED|CONNECTION_(?:CLOSED|RESET))|resumed exact frozen job|Target.*closed|浏览器.*占用',re.I)
VERSION='1.0-nov25-user18-preflight-one-grant'

def eligible(job,row,submitted):
    if EXPECTED.get((job.get('account'),job.get('target')))!=job.get('filename'):return False
    if row is None:return True
    return (isinstance(row,dict) and row.get('status') in {'not_started','failed_before_post'} and not submitted(row)
            and not DENY.search(str(row.get('error','')))
            and (row.get('status')=='not_started' or bool(RECOVER.search(str(row.get('error',''))))))

def source_jobs(app,root,req,controller):
    if not req['sha256'].startswith(REQUEST_PREFIX) or req['payload'].get('material_date')!=DAY:raise ValueError('不是已核对的11月25日原批次')
    found={}
    for wave in controller.get('waves',[]):
        name=wave.get('manifest','')
        if not re.fullmatch(r'frozen-material-\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json',name):raise ValueError('原冻结清单路径异常')
        value=app.first.archive.checked_json(root/'logs'/name);payload=value['payload']
        if value['sha256']!=wave['sha256'] or payload.get('queue_id')!=req['sha256'] or payload.get('material_source_date')!=DAY:raise ValueError('原视频来源或指纹不符')
        for job in payload['jobs']:
            pair=job['account'],job['target']
            if pair in EXPECTED:
                if pair in found or job['filename']!=EXPECTED[pair]:raise ValueError('指定素材名称冲突或发生变化')
                found[pair]=job
    if set(found)!=set(EXPECTED):raise ValueError('原冻结清单缺少指定18个目标')
    return found

def preflight(day,root,accounts):
    import resume18_target_watchdog_20261126 as watchdog
    blocked=[]
    for account in sorted(accounts):
        owners=profiles.profile_owners(root/'profiles'/account)
        if owners:
            try:watchdog.release_idle(day,root,account)
            except RuntimeError as error:
                blocked.append(dict(account=account,pids=[o['pid'] for o in owners],reason=str(error)));continue
            owners=profiles.profile_owners(root/'profiles'/account)
        if owners:blocked.append(dict(account=account,pids=[o['pid'] for o in owners],reason='账号资料仍被占用'))
    files.save(root/'logs/nov25-resume18-preflight.json',dict(accounts=sorted(accounts),blocked=blocked,at=datetime.now(timezone.utc).isoformat()))
    if blocked:raise ValueError('续发前占用检查未通过，请正常关闭这些账号的Chrome窗口后重跑同一入口：'+','.join(r['account']+' PID '+','.join(map(str,r['pids'])) for r in blocked))
    print('指定账号浏览器占用检查通过；将核对18条原文件及提交记录。',flush=True)

def initialize_unstarted(day,root,selected,controller):
    first=day.first;path=root/'logs/publish_state.json'
    with first.locked():
        state=first.upload.read_json(path,{});before=copy.deepcopy(state);now=datetime.now(timezone.utc).isoformat()
        for pair,job in selected.items():
            if pair[0] in day.app.PAUSED or job['key'] in state:continue
            wave=next(w for w in controller['waves'] if pair in {tuple(p) for p in w['pairs']})
            # A truthful not_started audit row allows the existing grant engine
            # to preserve absence/history without inventing a failed attempt.
            state[job['key']]=dict(account=pair[0],target=pair[1],url=job['url'],video=str(first.upload.inbox_for(job)/job['filename']),
                status='not_started',created=now,uploader_version='2.47',ai_label_requested=False,
                source_frozen_manifest=wave['manifest'],source_frozen_sha256=wave['sha256'],resume18_never_started=True)
        if state!=before:
            backup=root/'backups'/('nov25-resume18-initial-'+uuid.uuid4().hex);backup.mkdir(parents=True);files.save(backup/'publish-state-before.json',before);files.save(path,state)

def execute_current(day,root,real_footage_confirmed=False,comment_lookup_seen=None):
    app=day.app;first=day.first;root=Path(root).resolve()
    if real_footage_confirmed is not True or root!=first.upload.ROOT.resolve():raise ValueError('原目录或本批实拍确认不符')
    first.workflow.require_versions()
    if app.current_workers(root):raise ValueError('仍有其他发布/分配/评论任务，未并发续发')
    app.browser.staged.lock_recovery.recover_locks(root)
    with patch.object(first.batch,'excluded_accounts',side_effect=app.exclusions),patch.object(app.owned,'reservation',side_effect=app.active_reservation):
        _,source,journal,material=app.allocation(root)
        with first.locked():req=app.request(root,source,journal,material)
        controller=first.upload.read_json(root/'logs'/('eligible60-real-publication-'+req['sha256'][:16]+'.json'),{})
        if controller.get('request_sha256')!=req['sha256']:raise ValueError('原发布进度与25号素材不符')
        selected=source_jobs(app,root,req,controller);day._resume18_allowed={j['key'] for j in selected.values()}
        state=first.upload.read_json(root/'logs/publish_state.json',{})
        already_consumed=set()
        for wave in controller['waves']:
            grant='eligible60-real-extra-'+req['sha256'][:12]+'-'+first.batch.digest(sorted(tuple(p) for p in wave['pairs']))[:12]+GRANT_SUFFIX
            claims=first.upload.read_json(root/'logs'/(grant+'-claims.json'),{})
            already_consumed.update(k for k,v in claims.get('jobs',{}).items() if v.get('phase')=='consumed')
        if any(job['key'] in already_consumed and job['key'] not in state for job in selected.values()):raise ValueError('追加许可已使用但原任务记录缺失，需核实，不重建未开始记录')
        accounts={pair[0] for pair,job in selected.items() if pair[0] not in app.PAUSED and job['key'] not in already_consumed and eligible(job,state.get(job['key']),app.queued.has_submission)}
        preflight(day,root,accounts)
        initialize_unstarted(day,root,selected,controller)
        print('只续发指定18个未完成目标；4条提交前失败、14条此前未开始；AI关闭，原正文和原评论。',flush=True)
        deferred={}
        for wave in controller['waves']:app.run_phase('extra',req,source,journal,material,wave,controller,deferred)
        consumed=set()
        for wave in controller['waves']:
            grant='eligible60-real-extra-'+req['sha256'][:12]+'-'+first.batch.digest(sorted(tuple(p) for p in wave['pairs']))[:12]+GRANT_SUFFIX
            claims=first.upload.read_json(root/'logs'/(grant+'-claims.json'),{})
            consumed.update(k for k,v in claims.get('jobs',{}).items() if v.get('phase')=='consumed')
        day._resume18_allowed &= consumed
        for phase in ('comments','comment_retry'):
            for wave in controller['waves']:app.run_phase(phase,req,source,journal,material,wave,controller,deferred)
        state=first.upload.read_json(root/'logs/publish_state.json',{});rows=[]
        for pair,job in sorted(selected.items()):
            row=state.get(job['key'],{})
            rows.append(dict(account=pair[0],target=pair[1],filename=job['filename'],key=job['key'],video_status=row.get('status','not_started'),assumed_published=row.get('assumed_published',False),comment_status=row.get('comment_status','not_started'),reason=row.get('error') or row.get('comment_error','')))
        summary=dict(material_date=DAY,grant=GRANT_SUFFIX,request_sha256=req['sha256'],rows=rows,published=sum(r['video_status']=='published' for r in rows),assumed_published=sum(r['assumed_published'] for r in rows),needs_review=sum(r['video_status'] in {'posting','preparing','needs_review'} for r in rows),failed_before_post=sum(r['video_status']=='failed_before_post' for r in rows),comments_sent=sum(r['comment_status'] in {'sent','already_present'} for r in rows))
        files.save(root/RESULT,summary);print('指定18条续发本轮结束：',summary['published'],'条记录成功，其中',summary['assumed_published'],'条按回执超时规则处理；评论成功',summary['comments_sent'],'报告：',root/RESULT,flush=True)
        return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows) else 3

@contextlib.contextmanager
def installed(day):
    app=day.app;first=day.first;native_wave=app.wave_context;native_extra=app.extra.execute
    @contextlib.contextmanager
    def wave(*args,**kwargs):
        with native_wave(*args,**kwargs) as old:
            grant=old+GRANT_SUFFIX
            with patch.object(app.queued,'GRANT',grant):yield grant
    def checked(job,state,claims,value):
        row=state.get(job['key']);claim=claims.get('jobs',{}).get(job['key']);original=claim.get('original') if claim else row
        if job['account'] in app.PAUSED or not eligible(job,original,app.queued.has_submission) or app.queued.has_submission(row):return None,'非指定18条、用户暂停、已有提交或登录异常，保留不重发'
        if claim:
            if claim.get('phase')=='consumed':return None,'本次追加机会已使用，不重复尝试'
            if row not in (claim.get('original'),claim.get('replacement')):return None,'许可后任务记录变化，保留'
        elif (first.batch.digest(row)!=value['payload']['authorized_state_sha256'].get(job['key']) or row.get('repair_authorization')==app.extra.GRANT):return None,'授权后原记录变化，保留'
        if not app.extra.resume.bound_record(job,row) or row.get('uploader_version')!='2.47' or row.get('ai_label_requested') is not False:raise ValueError('原视频身份或实拍标记不符')
        if not claim and (row.get('source_frozen_manifest'),row.get('source_frozen_sha256')) not in {(b['manifest'],b['sha256']) for b in value['payload']['source_bindings']}:raise ValueError('不是原冻结来源')
        ledger=first.upload.read_json(first.upload.ROOT/'logs/video_comments.json',{})
        if any(isinstance(r,dict) and r.get('video_job')==job['key'] and r.get('status') in {'sending','verifying','sent','already_present','needs_review'} for r in ledger.values()):return None,'已有评论记录，保留不重发视频'
        if any(r.get('account')==job['account'] and r.get('status') in {'preparing','posting'} for r in state.values()):return None,'账号另有进行中的任务'
        entry=first.batch.validate_job(job,date=DAY);video=first.upload.inbox_for(entry)/job['filename']
        if first.archive.info(video)!=dict(size=job['video_size'],sha256=job['video_sha256']):raise ValueError('原视频指纹变化')
        chosen=first.upload.named_job(entry,{k:r for k,r in state.items() if k!=job['key']},job['filename'])
        if not chosen or chosen[0]!=job['key'] or chosen[3]!=job['caption_text']:raise ValueError('原视频或文案不一致')
        return dict(entry,enabled=True,auto_switch_personal=True),'ready'
    def extra():
        if not app.extra.GRANT.endswith(GRANT_SUFFIX):raise ValueError('缺少本次18目标追加授权')
        with patch.object(app.extra,'DAY',DAY),patch.object(first.priority.daily,'backfill',return_value=[]),patch.object(first.priority.comment_retry,'run',return_value=[]):return native_extra()
    def worker_status(root,phase,message):
        attempt=os.environ.get('FB_PUBLISH_LAUNCH_ID','')
        if re.fullmatch('[a-f0-9]{32}',attempt):files.save(Path(root)/'logs'/('nov25-resume18-worker-'+attempt+'.json'),dict(phase=phase,message=message,material_date=DAY,mode='selected18_resume'))
    def execute(root):
        import set_login_abnormal_fb32_fb52_20261126 as disabled
        if day.inspect_workers(root):raise ValueError('仍有其他任务，未修改账号停用设置')
        disabled.apply(root)
        with day.authorized_context():return app.execute(root,True)
    try:
        with patch.object(app,'execute_current',side_effect=lambda root,real_footage_confirmed=False,comment_lookup_seen=None:execute_current(day,root,real_footage_confirmed,comment_lookup_seen)),patch.object(app,'wave_context',side_effect=wave),patch.object(app.extra,'checked',side_effect=checked),patch.object(app.extra,'execute',side_effect=extra),patch.object(first,'reconcile',return_value=None),patch.object(day,'execute',side_effect=execute),patch.object(day,'worker_status',side_effect=worker_status):yield
    finally:
        if hasattr(day,'_resume18_allowed'):del day._resume18_allowed
