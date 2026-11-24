"""Publish only Nov23's completed allocation, with the explicitly confirmed real-footage policy."""
import contextlib,copy,os,re,sys,traceback
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

def isolate_background_interrupts():
    """Only the detached automatic worker ignores foreground console signals."""
    if os.environ.get('FB_PUBLISH_ISOLATED_BACKGROUND')!='1' or sys.platform!='win32':return None
    import ctypes,signal
    from ctypes import wintypes
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    if hasattr(signal,'SIGBREAK'):signal.signal(signal.SIGBREAK,signal.SIG_IGN)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.SetConsoleCtrlHandler.argtypes=[ctypes.c_void_p,wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype=wintypes.BOOL
    if kernel.SetConsoleCtrlHandler(None,True):return 'console_interrupts_ignored'
    code=ctypes.get_last_error()
    if code==6:return 'detached_without_console'
    raise RuntimeError('无法核验后台控制台隔离，Windows错误：'+str(code))

_BACKGROUND_GUARD=None
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    _BACKGROUND_GUARD=isolate_background_interrupts()
import publish_eligible60_materials_20261119 as app

first=app.first
VERSION='1.1-nov23-console-isolated-file-log-background'
DAY='2026-11-23'
POINTER='material-staging/eligible60-20261123-pending-import.json'
REQUEST='logs/eligible60-real-publication-request-20261123.json'
AUTH='user-authorized-nov23-original60-real-off-original-book-caption-comment-v1'
CONTENT_SHA='ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894'
LOG='logs/eligible60-2026-11-23-run.log'
_allocation=app.allocation
BOOTSTRAP=re.compile(app.workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_publish_eligible60_real_20261123').replace('verified-first24-material-distribution','verified-real-eligible60-nov23-publication'))

def inspect_workers(root):
    with patch.object(app.workers,'BOOTSTRAP',BOOTSTRAP):return app.workers.active_workers(root,Path(__file__).resolve())

def allocation(root):
    root=Path(root).resolve();read=first.upload.read_json
    dated=app.stage.safe_child(root,root/POINTER);pointer=read(dated,{})
    if pointer.get('complete') is not True:raise ValueError('11月23日素材尚未正式导入完成；保留分配窗口，本入口不另选素材或等待导入。')
    path=app.stage.safe_child(root,root/pointer.get('manifest',''));_,source=app.stage.validate_stage(root,path)
    if source['payload']['date']!=DAY or source['sha256']!=pointer.get('sha256'):raise ValueError('不是11月23日原分配清单，未使用旧视频。')
    generic=(root/'material-staging/eligible60-pending-import.json').resolve()
    # Reuse every existing import, identity, generation and scope validator,
    # reading only this date's immutable pointer; do not replace global state.
    def scoped_read(path,default):
        if Path(path).resolve()==generic:return copy.deepcopy(pointer)
        return read(path,default)
    with patch.object(first.upload,'read_json',side_effect=scoped_read):return _allocation(root)

@contextlib.contextmanager
def authorized_context():
    recover=app.queued.retry.RECOVER
    recoverable=re.compile('(?:'+recover.pattern+r')|查看所有个人主页入口未加载，未选择视频或点击发布',recover.flags)
    with patch.object(app.content_today,'DAY',DAY),patch.object(app.content_today,'save_authorized',side_effect=lambda root:app.content_today.verify(root,CONTENT_SHA)), \
         patch.object(app,'AUTH',AUTH),patch.object(app.queued,'AUTH',AUTH),patch.object(app,'REQUEST',REQUEST), \
         patch.object(app,'allocation',side_effect=allocation),patch.object(app,'current_workers',side_effect=inspect_workers), \
         patch.object(app.queued.retry,'RECOVER',recoverable),patch.object(app.owners.guided,'prompt',return_value='S'):
        yield

def execute(root):
    root=Path(root).resolve()
    if root!=first.upload.ROOT.resolve():raise ValueError('请在原上传目录运行。')
    actual=datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()
    if actual<DAY:raise ValueError('尚未到本批素材授权日期。')
    if app.content_today.CONTENT['sha256']!=CONTENT_SHA:raise ValueError('原文案或更正后的评论版本变化，未发布。')
    launcher=(root/'normal_chrome_batch.py').read_text(encoding='utf-8-sig')
    if "STARTUP_WAIT_VERSION='1.0-wait-for-endpoint-after-launcher-exit'" not in launcher:raise ValueError('后台Chrome启动修复未安装，未开始整批发布。')
    live=inspect_workers(root)
    if live:raise ValueError('原发布/分配/登录任务仍在运行，未停止其他进程。PID：'+','.join(str(r['pid']) for r in live))
    with authorized_context():
        allocation(root)
        print('开始11月23日原60目标发布与评论：用户确认全部实拍，AI标签关闭；沿用原正文和更正后的评论。',flush=True)
        print('后台处理；暂停账号跳过，登录/安全验证保留到报告末尾；明确发布前失败安全补发，已提交/待核实不重复上传。',flush=True)
        return app.execute(root,True)

def main(root):
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
    root=Path(root).resolve();log=root/LOG
    with log.open('a',encoding='utf-8') as handle:
        file_only=os.environ.get('FB_PUBLISH_FILE_LOG_ONLY')=='1'
        out=first.batch.Tee(*[s for s in (None if file_only else sys.stdout,handle) if s is not None]);err=first.batch.Tee(*[s for s in (None if file_only else sys.stderr,handle) if s is not None])
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            print('Nov23 run started:',datetime.now(timezone.utc).astimezone(first.batch.BJ).isoformat(),flush=True)
            if _BACKGROUND_GUARD:print('后台控制台隔离：',_BACKGROUND_GUARD,'；进度直接写入日志。',flush=True)
            try:return execute(root)
            except KeyboardInterrupt:print('已暂停并保留全部进度，重跑同一入口继续。',flush=True);return 130
            except Exception as error:traceback.print_exc();print('STOP：',str(error) or type(error).__name__,flush=True);return 1

if __name__=='__main__':
    if sys.stdout is not None:sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    raise SystemExit(main(Path(sys.argv[1])))
