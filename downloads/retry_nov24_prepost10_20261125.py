"""One additional user-authorized grant for ten audited Nov24 pre-Post failures."""
import contextlib,copy,re
from pathlib import Path
from unittest.mock import patch

DAY='2026-11-24'
REQUEST_PREFIX='2a3bef46c1aa99e9'
GRANT_SUFFIX='-user-retry10-20261125-v1'
RESULT='logs/nov24-retry10-on-nov25-results.json'
EXPECTED={
 ('fb03','personal'):'20261124-b4ca255d-eligible60-3.mp4',
 ('fb09','personal'):'20261124-b4ca255d-eligible60-44.mp4',
 ('fb13','page01'):'20261124-b4ca255d-eligible60-2026-11-10_7706484671927815455.mp4',
 ('fb37','personal'):'20261124-b4ca255d-eligible60-2026-11-13_7707595014947360031.mp4',
 ('fb45','personal'):'20261124-b4ca255d-eligible60-2026-11-13_7707595578833767710.mp4',
 ('fb49','personal'):'20261124-b4ca255d-eligible60-2026-11-14_7707991754531720479.mp4',
 ('fb62','personal'):'20261124-b4ca255d-eligible60-2026-11-18_7709462289719577886.mp4',
 ('fb63','personal'):'20261124-b4ca255d-eligible60-2026-11-18_7709463020707122463.mp4',
 ('fb68','personal'):'20261124-b4ca255d-eligible60-2026-11-19_7709843344452635934.mp4',
 ('fb70','personal'):'20261124-b4ca255d-eligible60-2026-11-19_7709845263048920350.mp4',
}
DENY=re.compile(r'captcha|checkpoint|verification|log[ -]?in|sign[ -]?in|安全验证|验证码|登录|身份不一致|账号限制',re.I)
RECOVER=re.compile(r'Timeout|ERR_CONNECTION_(?:CLOSED|RESET)|intercepts pointer events|个人主页.*(?:入口|列表).*未加载|查看所有个人主页入口未加载',re.I)

def eligible(job,row,submitted):
    return (EXPECTED.get((job.get('account'),job.get('target')))==job.get('filename')
            and isinstance(row,dict) and row.get('status')=='failed_before_post'
            and not submitted(row) and not DENY.search(str(row.get('error','')))
            and bool(RECOVER.search(str(row.get('error','')))))

def source_jobs(app,root,req,controller):
    if not req['sha256'].startswith(REQUEST_PREFIX) or req['payload'].get('material_date')!=DAY:raise ValueError('不是已核对的11月24日原批次。')
    found={}
    for wave in controller.get('waves',[]):
        if wave.get('date')!=DAY:raise ValueError('原任务冻结日期发生变化，未猜选其他批次。')
        value=app.first.archive.checked_json(root/'logs'/wave['manifest']);p=value['payload']
        if value['sha256']!=wave['sha256'] or p.get('queue_id')!=req['sha256'] or p.get('material_source_date')!=DAY:raise ValueError('原冻结清单不符。')
        for job in p['jobs']:
            pair=job['account'],job['target']
            if pair in EXPECTED:
                if pair in found or job['filename']!=EXPECTED[pair]:raise ValueError('所选原视频名称冲突或变化。')
                found[pair]=job
    if set(found)!=set(EXPECTED):raise ValueError('原清单中未找到完整的10个指定目标。')
    return found

def execute_current(day,root,real_footage_confirmed=False,comment_lookup_seen=None):
    app=day.app;root=Path(root).resolve()
    if real_footage_confirmed is not True or root!=app.first.upload.ROOT.resolve():raise ValueError('原目录或实拍确认不符。')
    app.first.workflow.require_versions()
    if app.current_workers(root):raise ValueError('仍有发布/分配任务，未并发补发。')
    app.browser.staged.lock_recovery.recover_locks(root)
    with patch.object(app.first.batch,'excluded_accounts',side_effect=app.exclusions),patch.object(app.owned,'reservation',side_effect=app.active_reservation):
        _,source,journal,material=app.allocation(root)
        with app.first.locked():req=app.request(root,source,journal,material)
        control_path=root/'logs'/('eligible60-real-publication-'+req['sha256'][:16]+'.json');controller=app.first.upload.read_json(control_path,{})
        if controller.get('request_sha256')!=req['sha256']:raise ValueError('原执行进度与24号素材不符。')
        selected=source_jobs(app,root,req,controller);day._retry10_allowed={j['key'] for j in selected.values()}
        print('本次仅追加补发10个指定原视频：',','.join(a+'/'+t for a,t in sorted(EXPECTED)),'；AI关闭，原正文和评论。',flush=True)
        print('新授权逐条记录；成功、已提交/待核实、登录/安全验证和暂停目标保留原记录。',flush=True)
        deferred={}
        for wave in controller['waves']:
            app.run_phase('extra',req,source,journal,material,wave,controller,deferred)
        # Only rows consumed by THIS new grant can enter its comment phase.
        consumed=set()
        for wave in controller['waves']:
            grant='eligible60-real-extra-'+req['sha256'][:12]+'-'+app.first.batch.digest(sorted(tuple(p) for p in wave['pairs']))[:12]+GRANT_SUFFIX
            claims=app.first.upload.read_json(root/'logs'/(grant+'-claims.json'),{})
            consumed.update(k for k,v in claims.get('jobs',{}).items() if v.get('phase')=='consumed')
        day._retry10_allowed &= consumed
        for phase in ('comments','comment_retry'):
            for wave in controller['waves']:app.run_phase(phase,req,source,journal,material,wave,controller,deferred)
        state=app.first.upload.read_json(root/'logs/publish_state.json',{});rows=[]
        for pair,job in sorted(selected.items()):
            record=state.get(job['key'],{})
            rows.append(dict(account=pair[0],target=pair[1],filename=job['filename'],key=job['key'],video_status=record.get('status','not_started'),comment_status=record.get('comment_status','not_started'),reason=record.get('error') or record.get('comment_error','')))
        summary=dict(material_date=DAY,grant=GRANT_SUFFIX,request_sha256=req['sha256'],rows=rows,published=sum(r['video_status']=='published' for r in rows),needs_review=sum(r['video_status'] in {'posting','preparing','needs_review'} for r in rows),failed_before_post=sum(r['video_status']=='failed_before_post' for r in rows),comments_sent=sum(r['comment_status'] in {'sent','already_present'} for r in rows))
        app.first.upload.save_json(root/RESULT,summary)
        print('指定10条本轮结果：确认发布成功',summary['published'],'；待核实',summary['needs_review'],'；发布前失败',summary['failed_before_post'],'；评论成功',summary['comments_sent'],'；报告：',root/RESULT,flush=True)
        return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows) else 3

@contextlib.contextmanager
def installed(day):
    app=day.app;native_wave=app.wave_context;native_checked=app.extra.checked;native_extra=app.extra.execute;native_menu=app.first.upload.open_facebook_menu
    @contextlib.contextmanager
    def wave(*args,**kwargs):
        with native_wave(*args,**kwargs) as old:
            grant=old+GRANT_SUFFIX
            with patch.object(app.queued,'GRANT',grant):yield grant
    def checked(job,state,claims,value):
        row=claims.get('jobs',{}).get(job['key'],{}).get('original',state.get(job['key']))
        if not eligible(job,row,app.queued.has_submission):return None,'本次10条之外，或已提交/状态变化，保留'
        if job['account'] in app.PAUSED:return None,'用户暂停账号，保留'
        ledger=app.first.upload.read_json(app.first.upload.ROOT/'logs/video_comments.json',{})
        if any(isinstance(r,dict) and r.get('video_job')==job['key'] and r.get('status') in {'sending','sent','already_present','needs_review'} for r in ledger.values()):return None,'已有评论提交记录，保留不重复上传'
        return native_checked(job,state,claims,value)
    def menu(page,click_timeout_ms=5000,keyboard_timeout_ms=5000):
        return native_menu(page,click_timeout_ms=max(15000,click_timeout_ms),keyboard_timeout_ms=keyboard_timeout_ms)
    def extra():
        if not app.extra.GRANT.endswith(GRANT_SUFFIX):raise ValueError('缺少本次10条追加许可。')
        # Keep the immutable source freeze date (24th); actual grant creation
        # and attempt timestamps remain the real execution time on the 25th.
        # Inline comments are deferred to the independent 180-second watchdog.
        with patch.object(app.extra,'DAY',DAY),patch.object(app.first.priority.daily,'backfill',return_value=[]),patch.object(app.first.priority.comment_retry,'run',return_value=[]):return native_extra()
    try:
        with patch.object(app,'execute_current',side_effect=lambda root,real_footage_confirmed=False,comment_lookup_seen=None:execute_current(day,root,real_footage_confirmed,comment_lookup_seen)),patch.object(app,'wave_context',side_effect=wave),patch.object(app.extra,'checked',side_effect=checked),patch.object(app.extra,'execute',side_effect=extra),patch.object(app.first,'reconcile',return_value=None),patch.object(app.first.upload,'open_facebook_menu',side_effect=menu):yield
    finally:
        if hasattr(day,'_retry10_allowed'):del day._retry10_allowed
