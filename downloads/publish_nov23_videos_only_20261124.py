"""Source-bound Nov23 publication and safe retries, with all comments disabled."""
import contextlib,copy,hashlib,json,os,re,subprocess,sys,tempfile,time,traceback
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

VERSION='1.0-nov23-videos-only'
DAY='2026-11-23'
NAME='publish_nov23_videos_only_20261124.py'
STATUS='logs/eligible60-2026-11-23-videos-only-status.json'
LOG='logs/eligible60-2026-11-23-videos-only-run.log'
AUTH='user-authorized-nov23-videos-only-no-comments-20261124'

def save(path,value):
    path=Path(path)
    if path.is_symlink():raise ValueError('记录文件是链接，未覆盖。')
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:
        temp=Path(handle.name);handle.write(json.dumps(value,ensure_ascii=False).encode('utf-8'))
    try:
        for attempt in range(20):
            try:temp.replace(path);break
            except PermissionError:
                if attempt==19:raise
                time.sleep(.02)
    finally:temp.unlink(missing_ok=True)

def inspect_workers(day,root):
    pattern=day.BOOTSTRAP.pattern.replace('start_publish_eligible60_real_20261123','start_publish_nov23_videos_only_20261124').replace('verified-real-eligible60-nov23-publication','verified-nov23-videos-only')
    with patch.object(day.app.workers,'BOOTSTRAP',re.compile(pattern)):
        return day.app.workers.active_workers(root,Path(__file__).resolve())

def stop_comments(root):
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('stop_nov23_comment_monitor_20261124.ps1')),'-Root',str(root)],
        stdin=subprocess.DEVNULL,capture_output=True,creationflags=0x08000000,timeout=60)
    output=(result.stdout+result.stderr).decode('utf-8-sig',errors='replace').strip()
    if output:print(output,flush=True)
    if result.returncode:raise RuntimeError('原评论监控尚未安全停止；未另起第二份视频任务。')

@contextlib.contextmanager
def comments_disabled(app):
    native=app.first.upload.run_entry
    def run(entry,*args,**kwargs):
        entry=dict(entry);entry.pop('_authorized_comment_text',None);entry.pop('_immediate_verified_comment',None)
        kwargs['defer_comments']=True
        return native(entry,*args,**kwargs)
    @contextlib.contextmanager
    def no_pending(*args,**kwargs):yield set()
    def no_backfill(*args,**kwargs):return kwargs.get('rows',[])
    # These guards cover inner retry workflows as well as the top-level phases.
    with patch.object(app.first.upload,'run_entry',side_effect=run),patch.object(app.pending_comments,'installed',side_effect=no_pending), \
         patch.object(app.first.priority.daily,'backfill',side_effect=no_backfill),patch.object(app.first.priority.comment_retry,'run',return_value=[]):yield

def video_report(app,root,req,material,controller,control_path):
    state=app.first.upload.read_json(root/'logs/publish_state.json',{});jobs={};issues={}
    for wave in controller['waves']:
        value=app.first.archive.checked_json(root/'logs'/wave['manifest'])
        jobs.update({(j['account'],j['target']):j for j in value['payload']['jobs']})
        issues.update({(r['account'],r['target']):r.get('reason','') for r in value.get('issues',[])})
    rows=[]
    for assignment in material['payload']['assignments']:
        pair=assignment['account'],assignment['target'];job=jobs.get(pair);row=state.get(job['key'],{}) if job else {}
        rows.append(dict(account=pair[0],target=pair[1],user_paused=pair[0] in app.PAUSED,key=job['key'] if job else None,video_status=row.get('status','not_started'),
                         filename=assignment['files'][-1]['destination_name'],reason=row.get('error') or row.get('review_reason') or issues.get(pair) or controller['pending'].get(pair[0],'')))
    active=[row for row in rows if not row['user_paused']]
    counts={status:sum(r['video_status']==status for r in active) for status in ('published','failed_before_post','needs_review','preparing','posting','not_started')}
    complete=bool(active) and all(row['video_status']=='published' for row in active)
    summary=dict(material_date=DAY,request_sha256=req['sha256'],mode='videos_only',comments_enabled=False,authorization=AUTH,complete=complete,counts=counts,rows=rows,updated_at=datetime.now(timezone.utc).isoformat())
    controller.update(video_only_complete=complete,video_only_mode=True,comments_disabled_for_source=True,video_only_report=control_path.stem+'-videos-only.json')
    app.first.upload.save_json(control_path,controller)
    output=control_path.with_name(control_path.stem+'-videos-only.json');save(output,summary)
    lines=['11月23日原素材：只发视频及安全补发；评论已停用。']
    for row in rows:lines.append(row['account']+'/'+row['target']+' 视频='+row['video_status']+(' 用户暂停' if row['user_paused'] else '')+(' 原因='+row['reason'] if row['reason'] else ''))
    output.with_suffix('.txt').write_text('\n'.join(lines),encoding='utf-8-sig')
    print('23号仅视频处理结果：成功',counts['published'],'；发布前失败',counts['failed_before_post'],'；待核实',sum(counts[s] for s in ('needs_review','preparing','posting')),'；未开始',counts['not_started'],'；评论已停用。报告：',output,flush=True)
    return 0 if complete else 3

def execute_current(app,root,real_footage_confirmed=False,comment_lookup_seen=None):
    if real_footage_confirmed is not True:raise ValueError('本批实拍确认缺失。')
    root=Path(root).resolve()
    if root!=app.first.upload.ROOT.resolve():raise ValueError('不是原上传目录。')
    app.first.workflow.require_versions()
    live=app.current_workers(root)
    if live:raise ValueError('仍有其他项目任务，未开始第二份。PID：'+','.join(str(r['pid']) for r in live))
    app.browser.staged.lock_recovery.recover_locks(root)
    with patch.object(app.first.batch,'excluded_accounts',side_effect=app.exclusions),patch.object(app.owned,'reservation',side_effect=app.active_reservation):
        _,source,journal,material=app.allocation(root)
        with app.first.locked():
            req=app.request(root,source,journal,material);app.save_availability(root);app.background_policy.save_background(root)
            save(root/'logs/nov23-videos-only-policy.json',dict(authorization=AUTH,material_date=DAY,request_sha256=req['sha256'],stage_sha256=source['sha256'],comments_enabled=False,ai_label=False,updated_at=datetime.now(timezone.utc).isoformat()))
        path=root/'logs'/('eligible60-real-publication-'+req['sha256'][:16]+'.json')
        controller=app.first.upload.read_json(path,dict(request_sha256=req['sha256'],waves=[],modes={},pending={}))
        if controller.get('request_sha256')!=req['sha256'] or not isinstance(controller.get('waves'),list):raise ValueError('原23号视频进度异常。')
        app.background_policy.retire_foreground_modes(controller);app.recover_waves(req,source,journal,material,controller,path)
        controller['paused_accounts']=sorted(app.PAUSED);deferred={}
        ready=app.registered_ready(material,controller);app.add_wave(ready,req,source,journal,material,controller,path)
        for wave in controller['waves']:app.run_phase('videos',req,source,journal,material,wave,controller,deferred)
        before=len(controller['waves']);app.auto_register_pending(material,controller,path)
        ready=app.registered_ready(material,controller);app.add_wave(ready,req,source,journal,material,controller,path)
        for wave in controller['waves'][before:]:app.run_phase('videos',req,source,journal,material,wave,controller,deferred)
        for wave in controller['waves']:app.run_phase('retry',req,source,journal,material,wave,controller,deferred)
        # The original single, durable before-Post retry policy remains in force.
        # Submitted/unknown results and already-consumed retry claims are preserved.
        return video_report(app,root,req,material,controller,path)

def execute(day,root):
    if day.app.content_today.CONTENT['sha256']!=day.CONTENT_SHA:raise ValueError('原发布文案版本变化。')
    launcher=(root/'normal_chrome_batch.py').read_text(encoding='utf-8-sig')
    if "STARTUP_WAIT_VERSION='1.0-wait-for-endpoint-after-launcher-exit'" not in launcher:raise ValueError('Chrome启动修复缺失。')
    with patch.object(day,'inspect_workers',side_effect=lambda path:inspect_workers(day,path)),day.authorized_context():
        # Validate source and immutable authorization before stopping the monitor.
        _,source,journal,material=day.allocation(root)
        if not (root/day.REQUEST).is_file():raise ValueError('原23号发布授权缺失。')
        day.app.request(root,source,journal,material)
        stop_comments(root)
        for _ in range(30):
            live=inspect_workers(day,root)
            if not live:break
            time.sleep(.1)
        if live:raise ValueError('其他项目任务尚未退出，未开始第二份。PID：'+','.join(str(r['pid']) for r in live))
        with comments_disabled(day.app),patch.object(day.app,'execute_current',side_effect=lambda *args,**kwargs:execute_current(day.app,*args,**kwargs)):
            return day.app.execute(root,True)

def main(root):
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
    launch=os.environ.get('FB_NOV23_VIDEO_LAUNCH','')
    if not re.fullmatch('[a-f0-9]{32}',launch):raise ValueError('仅视频入口任务标识缺失。')
    root=Path(root).resolve();sys.path.insert(0,str(root));sys.path.insert(0,str(Path(__file__).resolve().parent))
    import publish_eligible60_real_20261123 as day
    if root!=day.first.upload.ROOT.resolve():raise ValueError('不是原上传目录。')
    day.isolate_background_interrupts()
    def status(phase,message):save(root/STATUS,dict(phase=phase,message=message,launch_id=launch,pid=os.getpid(),material_date=DAY,mode='videos_only',comments_enabled=False,updated_at=datetime.now(timezone.utc).isoformat()))
    with (root/LOG).open('a',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        try:
            status('preparing','正在停止23号评论并核对原视频进度。')
            print('23号批次切换为仅发视频：原文案、实拍AI关闭、排除账号及安全补发规则保留；评论全部停用。',flush=True)
            # The actual running acknowledgment follows the preflight and takeover.
            native=day.app.execute
            def run(*args,**kwargs):
                status('running','23号仅发视频及安全补发已启动；评论定位、发送和补评全部停用。')
                return native(*args,**kwargs)
            with patch.object(day.app,'execute',side_effect=run):code=execute(day,root)
            status('finished' if code==0 else 'review_required','视频流程已结束；评论保持停用，实际结果见仅视频报告。');return code
        except Exception as error:
            status('failed',str(error) or type(error).__name__);traceback.print_exc();print('STOP：',str(error) or type(error).__name__,flush=True);return 1

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    raise SystemExit(main(Path(sys.argv[1])))
