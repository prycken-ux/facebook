"""Resume only the original Nov20 allocation, with actual execution timestamps."""
import contextlib,copy,re,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    root=Path(sys.argv[1]).resolve()
    sys.path.insert(0,str(root))
    sys.path.insert(0,str(root/'material-staging/tools/ba94d914345c9974'))
import weekend60_schedule_20261120 as schedule

app=schedule.app
first=app.first
VERSION='1.0-source-bound-nov20-resume-from-nov23'
SOURCE_DAY='2026-11-20'
AUTHORIZED_FROM='2026-11-23'
EXPECTED_MASTER_PREFIX='9851ee33'
EXPECTED_SOURCE_PREFIX='d036b4ae'
AUDIT='logs/nov20-original60-resume-authorized-nov23.json'
BOOTSTRAP=re.compile(app.workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_resume_weekend60_nov20_on_nov23').replace('verified-first24-material-distribution','verified-weekend60-nov20-resume'))

def inspect_workers(root):
    with patch.object(app.workers,'BOOTSTRAP',BOOTSTRAP):
        return app.workers.active_workers(root,Path(__file__).resolve())

def check_source(root,value):
    schedule.validate(root,value)
    if not value['sha256'].startswith(EXPECTED_MASTER_PREFIX):raise ValueError('不是此前已排期的原三天计划，未改选其他素材。')
    batch=value['payload']['batches'][SOURCE_DAY]
    if not batch['source_id'].startswith(EXPECTED_SOURCE_PREFIX):raise ValueError('不是20日d036b4ae原素材，未继续。')
    progress=first.upload.read_json(root/schedule.FOLDER/'copy-progress.json',{})
    if progress.get('sha256')!=value['sha256'] or progress.get('complete') is not True:raise ValueError('原三天分配未完整结束，不重新分配素材。')
    request_path=root/'logs'/('weekend60-publication-request-'+SOURCE_DAY+'.json')
    request=first.archive.checked_json(request_path)
    p=request['payload']
    if (p.get('material_date')!=SOURCE_DAY or p.get('authorization')!=schedule.AUTH
            or p.get('content_sha256')!=schedule.content.CONTENT['sha256']
            or p.get('ai_label') is not False or p.get('real_footage_confirmed') is not True
            or p.get('targets')!=[list(p) for p in sorted(app.EXPECTED)]):raise ValueError('20日原发布授权不符。')
    controller=first.upload.read_json(root/'logs'/('eligible60-real-publication-'+request['sha256'][:16]+'.json'),{})
    if controller.get('request_sha256')!=request['sha256'] or not controller.get('waves'):raise ValueError('缺少20日原冻结进度，不重建旧任务。')
    return request

def authorize(root,value,request):
    identity=dict(schema='nov20-original60-resume-on-nov23-v1',authorization='user-requested-resend-original-nov20-materials',
                  authorized_from=AUTHORIZED_FROM,material_date=SOURCE_DAY,original_schedule_sha256=value['sha256'],
                  original_request_sha256=request['sha256'],content_sha256=schedule.content.CONTENT['sha256'],
                  ai_label=False,preserve_submitted=True,targets=[list(p) for p in sorted(app.EXPECTED)])
    path=root/AUDIT;saved=first.upload.read_json(path,None)
    if saved:
        payload=saved.get('payload',{})
        if saved.get('sha256')!=schedule.digest(payload) or {k:v for k,v in payload.items() if k!='created_at'}!=identity:raise ValueError('本次续发授权记录发生变化。')
        return saved
    payload=dict(identity,created_at=datetime.now(timezone.utc).isoformat());saved=dict(payload=payload,sha256=schedule.digest(payload))
    backup=root/'backups'/('resume-original-nov20-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
    for name in ('publish_state.json','weekend60-publication-request-'+SOURCE_DAY+'.json','eligible60-real-publication-'+request['sha256'][:16]+'.json'):
        original=root/'logs'/name
        if original.is_file():shutil.copy2(original,backup/name)
    first.upload.save_json(backup/'resume-authorization.json',saved);first.upload.save_json(path,saved)
    print('原记录备份：',backup,flush=True)
    return saved

@contextlib.contextmanager
def source_context(root,value):
    # Material-day constants validate the original content. Neither the clock
    # nor app.today() is changed: all new actions retain their actual time.
    recover=app.queued.retry.RECOVER
    recoverable=re.compile('(?:'+recover.pattern+r')|查看所有个人主页入口未加载，未选择视频或点击发布',recover.flags)
    with patch.object(app.content_today,'save_authorized',side_effect=lambda r:schedule.content.verify(r,value['payload']['content']['sha256'])), \
         patch.object(app,'AUTH',schedule.AUTH),patch.object(app.queued,'AUTH',schedule.AUTH),patch.object(app.content_today,'DAY',SOURCE_DAY), \
         patch.object(app,'REQUEST','logs/weekend60-publication-request-'+SOURCE_DAY+'.json'), \
         patch.object(app,'allocation',side_effect=lambda r:schedule.allocation(r,SOURCE_DAY,value)),patch.object(app,'current_workers',side_effect=inspect_workers), \
         patch.object(first.upload,'inbox_for',side_effect=lambda entry:schedule.day_inbox(root,entry['account'],entry['target'],SOURCE_DAY)), \
         patch.object(app.queued.retry,'RECOVER',recoverable),patch.object(app.owners.guided,'prompt',return_value='S'):
        yield

def execute(root):
    root=Path(root).resolve()
    if root!=first.upload.ROOT.resolve():raise ValueError('请使用原E盘上传目录。')
    actual=datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()
    if actual<AUTHORIZED_FROM:raise ValueError('尚未到本次用户授权续发日期。')
    value=schedule.checked_json(root,root/schedule.MANIFEST);request=check_source(root,value)
    launcher=(root/'normal_chrome_batch.py').read_text(encoding='utf-8-sig')
    if "STARTUP_WAIT_VERSION='1.0-wait-for-endpoint-after-launcher-exit'" not in launcher:raise ValueError('原后台Chrome启动修复未安装，未继续整批尝试。')
    live=inspect_workers(root)
    if live:raise ValueError('仍有发布/登录检查任务，未终止它们；请等其结束后重跑。PID：'+','.join(str(r['pid']) for r in live))
    folder=schedule.safe(root,root/schedule.FOLDER/'resume-original-nov20-on-nov23');folder.mkdir(exist_ok=True)
    with app.stage.staging_lock(folder):
        app.browser.staged.lock_recovery.recover_locks(root)
        with first.locked():
            check_source(root,schedule.checked_json(root,root/schedule.MANIFEST))
            authorize(root,value,request)
        print('仅续发11月20日原60目标；沿用原文案和评论，AI标签关闭，暂停账号直接跳过。',flush=True)
        print('先恢复原中断状态；已提交/待核实视频保留并查找原视频，不重复上传；未开始及明确发布前失败继续处理。',flush=True)
        print('本次实际执行日期：',actual,'；不会执行、重排或修改21、22日的批次。',flush=True)
        with source_context(root,value):return app.execute(root,True)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的PowerShell窗口运行。')
        log=Path(sys.argv[1])/'logs'/'resume-weekend60-nov20-on-nov23-run.log'
        with log.open('a',encoding='utf-8') as handle,contextlib.redirect_stdout(first.batch.Tee(sys.stdout,handle)),contextlib.redirect_stderr(first.batch.Tee(sys.stderr,handle)):
            print('Resume run started:',datetime.now(timezone.utc).astimezone(first.batch.BJ).isoformat(),flush=True)
            raise SystemExit(execute(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停并保留进度，重跑同一指令继续，不重复已有提交。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
