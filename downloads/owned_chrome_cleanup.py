"""Close only the Popen handle this launcher owns; never target a foreign PID."""
import subprocess

VERSION='1.0-owned-headless-process-cleanup'


def finish_owned_process(process,run_mode,graceful_close):
    """Wait for CDP close, then end only our own headless browser if needed."""
    if process is None:
        graceful_close();return
    if process.poll() is not None:return
    try:
        process.wait(timeout=5);return
    except subprocess.TimeoutExpired:pass
    if run_mode!='background':
        # Visible/manual browsers keep the established normal-window close path.
        graceful_close()
        try:process.wait(timeout=5);return
        except subprocess.TimeoutExpired:raise RuntimeError('本次可见Chrome尚未正常退出，未强制结束其他窗口。') from None
    # Popen retains a Windows process handle: this never looks up or kills a
    # numeric PID that could have been recycled or belong to another account.
    if process.poll() is None:process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:raise RuntimeError('本次自己启动的后台Chrome尚未退出，未结束其他账号进程。') from None


def save_launch_error(root,account,original,cleanup_error=None):
    from datetime import datetime
    from pathlib import Path
    import uuid
    folder=Path(root)/'logs';folder.mkdir(exist_ok=True)
    path=folder/('chrome-launch-'+account+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'-error.txt')
    try:
        path.write_text('Original launch error:\n'+original+('\nCleanup error (did not replace original):\n'+str(cleanup_error) if cleanup_error else ''),encoding='utf-8')
        print('后台Chrome原始启动错误已保存：',path,flush=True)
    except OSError:pass
