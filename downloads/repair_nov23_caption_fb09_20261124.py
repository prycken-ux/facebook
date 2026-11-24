"""One source-bound video-only repair after auditing the uploaded Nov23 report."""
import contextlib,copy,hashlib,json,os,re,shutil,subprocess,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import publish_nov23_videos_only_20261124 as videos

VERSION='1.0-caption-rich-editor-fb09-prepost-repair'
DAY='2026-11-23'
REQUEST_SHA='cc85956c8985dc3537a4a7bef470dec8af4000d74e750276659873a594b0be48'
REPORT_SHA='322e10181d188ce353b970298ffd8d6c2129a7c40f189e52fe839968a5a5d1f3'
REPORT='eligible60-real-publication-cc85956c8985dc35-videos-only.json'
STATUS='logs/nov23-caption-fb09-repair-status.json'
LOG='logs/nov23-caption-fb09-repair-run.log'
AUTH='user-authorized-nov23-video-only-repair-caption-and-fb09-v1'
CAPTION_ERROR='Node is not an <input>, <textarea> or <select> element'
LOGIN=re.compile(r'登录|安全验证|captcha|checkpoint|log[ -]?in|verification',re.I)

def classification(row):
    if row.get('video_status')=='failed_before_post':
        error=row.get('reason','')
        if 'Locator.input_value' in error and CAPTION_ERROR in error:return 'caption'
        if row.get('account')=='fb14' and 'resumed exact frozen job' in error:return 'interrupted_before_post'
    if row.get('video_status')=='not_started' and row.get('account')=='fb09':return 'profile_busy_before_browser'
    return None

def baseline(root):
    original=root/'logs'/REPORT;archive=root/'logs'/('nov23-repair-baseline-'+REPORT_SHA[:16]+'.json')
    data=(archive if archive.exists() else original).read_bytes()
    if hashlib.sha256(data).hexdigest()!=REPORT_SHA:raise ValueError('不是已核对的23号原报告；未按变化后的状态猜测补发。')
    value=json.loads(data.decode('utf-8-sig'))
    if value.get('request_sha256')!=REQUEST_SHA or value.get('material_date')!=DAY or value.get('comments_enabled') is not False:raise ValueError('原报告来源或仅视频模式不符。')
    if not archive.exists():
        with archive.open('xb') as handle:handle.write(data)
    return value

def busy_before_browser(error):
    return ('fb09' in error and 'Chrome' in error and '资料仍被占用' in error and '尚未启动浏览器' in error)

def missing_proof(job,value,report,retries,claims,ledger,has_submission):
    """No state is reconstructed without original and retry before-browser proof."""
    if job['account']!='fb09':return None
    if any(item.get('video_job')==job['key'] for item in ledger.values() if isinstance(item,dict)):return None
    claim=claims.get('jobs',{}).get(job['key'])
    if (claims.get('schema')!='automatic-before-post-retry-claims-v1' or not isinstance(claim,dict)
            or claim.get('source_sha256')!=value['sha256'] or claim.get('source_manifest')!=report.get('manifest')
            or claim.get('original_record') is not None):return None
    first=[r for r in report.get('attempts',[]) if r.get('key')==job['key']]
    second=[r for r in retries if r.get('key')==job['key']]
    if not first or not second:return None
    attempts=first+second
    if any(a.get('action')!='manual_required' or not busy_before_browser(str(a.get('error',''))) or has_submission(a) for a in attempts):return None
    if any(r.get('key')==job['key'] and r.get('video_status') in {'published','posting','preparing','needs_review'} for r in report.get('rows',[])):return None
    try:created=min(datetime.fromisoformat(a['started_at']) for a in attempts)
    except (KeyError,ValueError,TypeError):return None
    if created.timestamp()<datetime.fromisoformat(value['created_at']).timestamp()-5:return None
    return dict(created=created.isoformat(),error=first[-1]['error'],attempt_count=len(attempts))

def allowed_live(job,row,old,has_submission):
    if not old or not classification(old) or not isinstance(row,dict):return False
    if row.get('status')!='failed_before_post' or has_submission(row) or LOGIN.search(str(row.get('error',''))):return False
    if job['account'] in {'fb32','fb52'}:return False
    kind=classification(old)
    if kind=='profile_busy_before_browser':return row.get('verified_missing_prepost')==AUTH
    if kind=='caption':return CAPTION_ERROR in str(row.get('error','')) and 'Locator.input_value' in str(row.get('error',''))
    return job['account']=='fb14' and ('resumed exact frozen job' in str(row.get('error','')) or 'MemoryError' in str(row.get('error','')))

def worker_pattern(day):
    return re.compile(day.BOOTSTRAP.pattern.replace('start_publish_eligible60_real_20261123','start_repair_nov23_caption_fb09_20261124').replace('verified-real-eligible60-nov23-publication','verified-nov23-caption-fb09-repair'))

def inspect_workers(day,root):
    with patch.object(day.app.workers,'BOOTSTRAP',worker_pattern(day)):
        return day.app.workers.active_workers(root,Path(__file__).resolve())

def release_fb09(day,root):
    worker=day.app.workers
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',worker.WORKERS],input=b'{}',capture_output=True,timeout=20,creationflags=0x08000000)
    if result.returncode:raise ValueError('无法核对现有任务，未释放浏览器。')
    rows=json.loads(result.stdout.decode('utf-8-sig'))
    with patch.object(worker,'BOOTSTRAP',worker_pattern(day)):
        live,allowed=worker.classify_workers(rows,root,os.getpid(),Path(__file__).resolve())
    if live:raise ValueError('仍有其他项目任务，未释放fb09浏览器。')
    identities=[dict(pid=r['pid'],created=r['created'],command_sha=hashlib.sha256(r['command'].encode()).hexdigest()) for r in rows if r['pid'] in allowed]
    packet=root/'logs'/('fb09-orphan-check-'+uuid.uuid4().hex+'.json');videos.save(packet,dict(root=str(root),starter_pid=os.getpid(),allowed=identities))
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('release_fb09_orphan_20261124.ps1')),'-InputFile',str(packet)],
                          stdin=subprocess.DEVNULL,capture_output=True,creationflags=0x08000000,timeout=40)
    output=(result.stdout+result.stderr).decode('utf-8-sig',errors='replace').strip()
    if output:print(output,flush=True)
    return result.returncode==0

def seed_missing(app,root,path,value,jobs):
    if not jobs:return
    state_path=root/'logs/publish_state.json';source_report=app.first.upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if source_report.get('manifest')!=path.name:raise ValueError('缺少原首轮报告，未恢复未开始的视频。')
    retries=[]
    for report_path in (root/'logs').glob('automatic-retry-*-results.json'):
        retry_path=report_path.with_name(report_path.name.replace('-results.json','.json'))
        retry=app.first.upload.read_json(retry_path,{})
        p=retry.get('payload',{})
        if p.get('source_manifest')!=path.name or p.get('source_sha256')!=value['sha256']:continue
        expected=copy.deepcopy(value['payload']);expected.update(jobs=p.get('jobs'),run_kind='automatic-safe-retry-v1',source_manifest=path.name,source_sha256=value['sha256'])
        if p!=expected or retry.get('sha256')!=app.first.batch.digest(p):raise ValueError('原自动补发清单指纹不符。')
        actual=app.first.upload.read_json(report_path,{})
        if actual.get('manifest')!=retry_path.name:raise ValueError('原自动补发结果身份不符。')
        retries.extend(actual.get('attempts',[]))
        # A receipt in a retry report overrides a missing state row; never infer
        # "not uploaded" from the absence of a current state entry alone.
        retries.extend(dict(key=row.get('key'),action='submission_evidence') for row in actual.get('rows',[]) if row.get('video_status') in {'published','posting','preparing','needs_review'})
    claims=app.first.upload.read_json(root/'logs/automatic_before_post_retry_claims.json',{})
    ledger=app.first.upload.read_json(root/'logs/video_comments.json',{})
    with app.first.locked():
        state=app.first.upload.read_json(state_path,{});before=copy.deepcopy(state);audit=[]
        for job in jobs:
            if job['key'] in state:continue
            proof=missing_proof(job,value,source_report,retries,claims,ledger,app.queued.has_submission)
            if not proof:
                print('fb09原失败证据不足，保留未开始：',job['target'],flush=True);continue
            entry=app.first.batch.validate_job(job,date=value['payload']['date']);video=app.first.upload.inbox_for(entry)/job['filename']
            if app.first.archive.info(video)!=dict(size=job['video_size'],sha256=job['video_sha256']):raise ValueError('fb09原视频文件变化。')
            state[job['key']]=dict(account=job['account'],target=job['target'],url=job['url'],video=str(video),status='failed_before_post',ai_label_requested=False,uploader_version='2.47',
                created=proof['created'],error=proof['error'],failure_stage='open_target_profile',before_media_launch_failure=True,verified_missing_prepost=AUTH,
                source_frozen_manifest=path.name,source_frozen_sha256=value['sha256'])
            audit.append(dict(key=job['key'],account='fb09',target=job['target'],proof=proof))
        if audit:
            backup=root/'backups'/('nov23-fb09-before-browser-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
            videos.save(backup/'before-state.json',before);videos.save(backup/'proof.json',audit);app.first.upload.save_json(state_path,state)
            print('已按两轮明确未启动浏览器的证据恢复fb09发布前失败记录：',len(audit),'条；原记录备份：',backup,flush=True)

def execute_current(app,root,real_footage_confirmed=False,comment_lookup_seen=None):
    root=Path(root).resolve()
    if real_footage_confirmed is not True or root!=app.first.upload.ROOT.resolve():raise ValueError('原目录或实拍确认不符。')
    app.first.workflow.require_versions()
    if app.current_workers(root):raise ValueError('其他任务仍在运行，未另起补发。')
    app.browser.staged.lock_recovery.recover_locks(root)
    with patch.object(app.first.batch,'excluded_accounts',side_effect=app.exclusions),patch.object(app.owned,'reservation',side_effect=app.active_reservation):
        _,source,journal,material=app.allocation(root)
        with app.first.locked():req=app.request(root,source,journal,material)
        if req['sha256']!=REQUEST_SHA:raise ValueError('不是已核对的23号原任务。')
        report=baseline(root);old={r['key']:r for r in report['rows']};eligible={key for key,r in old.items() if classification(r)}
        control_path=root/'logs'/('eligible60-real-publication-'+REQUEST_SHA[:16]+'.json');controller=app.first.upload.read_json(control_path,{})
        if controller.get('request_sha256')!=REQUEST_SHA:raise ValueError('原视频执行进度不符。')
        app.recover_waves(req,source,journal,material,controller,control_path)
        jobs=[j for w in controller['waves'] for j in app.first.archive.checked_json(root/'logs'/w['manifest'])['payload']['jobs']]
        if {j['key'] for j in jobs}!=set(old):raise ValueError('原60目标清单与已核对报告不一致。')
        fb09_ready=release_fb09(app._nov23_day,root)
        if not fb09_ready:eligible-={k for k,r in old.items() if r['account']=='fb09'}
        native=app.extra.checked
        def checked(job,state,claims,value):
            if job['key'] not in eligible or job['account'] in app.PAUSED:return None,'本次修复范围之外，保留原记录'
            # For a resumed reservation, inspect its saved original failure; the
            # original durable grant still decides consumed/changed-state cases.
            original=claims.get('jobs',{}).get(job['key'],{}).get('original',state.get(job['key']))
            if not allowed_live(job,original,old[job['key']],app.queued.has_submission):return None,'已提交、登录问题或失败类型已变化，保留不重发'
            return native(job,state,claims,value)
        import builtins
        def repair_print(*args,**kwargs):
            if args and isinstance(args[0],str) and args[0].startswith('使用无窗口后台Chrome；新补发成功的视频按原文案评论。'):
                args=('使用无窗口后台Chrome；仅补发原视频，评论已停用。',)+args[1:]
            if args and isinstance(args[0],str) and args[0].startswith('原清单补发阶段结束；仅本许可实际新成功的视频进入评论'):
                args=('本次原视频修复补发结束；评论已停用，已提交和待核实的视频保留。',)+args[1:]
            builtins.print(*args,**kwargs)
        deferred={}
        with patch.object(app.extra,'checked',side_effect=checked),patch.object(app.first,'reconcile',return_value=None),patch.object(app.extra,'print',side_effect=repair_print,create=True):
            for wave in controller['waves']:
                with app.wave_context(req,source,journal,material,wave,controller):
                    path=root/'logs'/wave['manifest'];value=app.first.archive.checked_json(path);app.first.validate(path,value,material)
                    if fb09_ready:seed_missing(app,root,path,value,[j for j in value['payload']['jobs'] if j['account']=='fb09' and j['key'] in eligible])
                app.run_phase('extra',req,source,journal,material,wave,controller,deferred)
        return videos.video_report(app,root,req,material,controller,control_path)

def main(root):
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
    launch=os.environ.get('FB_NOV23_REPAIR_LAUNCH','')
    if not re.fullmatch('[a-f0-9]{32}',launch):raise ValueError('补发任务标识缺失。')
    root=Path(root).resolve();sys.path.insert(0,str(root));sys.path.insert(0,str(Path(__file__).resolve().parent))
    import publish_eligible60_real_20261123 as day
    if root!=day.first.upload.ROOT.resolve():raise ValueError('不是原上传目录。')
    day.isolate_background_interrupts()
    def status(phase,message):videos.save(root/STATUS,dict(phase=phase,message=message,pid=os.getpid(),launch_id=launch,material_date=DAY,comments_enabled=False,updated_at=datetime.now(timezone.utc).isoformat()))
    with (root/LOG).open('a',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        try:
            status('preparing','正在核对23号原报告、文案框修复和后台进程。')
            with patch.object(day,'inspect_workers',side_effect=lambda p:inspect_workers(day,p)),day.authorized_context():
                if inspect_workers(day,root):raise ValueError('原视频/登录任务仍在运行，未开始第二份。')
                baseline(root);day.allocation(root)
                status('running','23号文案框修复补发已启动；只处理可证明未发布的视频，评论停用。')
                with videos.comments_disabled(day.app),patch.object(day.app,'_nov23_day',day,create=True),patch.object(day.app,'execute_current',side_effect=lambda *args,**kwargs:execute_current(day.app,*args,**kwargs)):
                    code=day.app.execute(root,True)
            status('finished' if code==0 else 'review_required','修复补发结束；实际结果见仅视频报告。');return code
        except Exception as error:
            import traceback
            status('failed',str(error) or type(error).__name__);traceback.print_exc();return 1

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    raise SystemExit(main(Path(sys.argv[1])))
