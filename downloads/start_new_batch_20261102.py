"""Single-line Windows entry for the authorized Nov-2 real-footage new batch."""
import ast
import hashlib
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def download_verified(commit, name, expected):
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    for prefix in (
        'https://raw.githubusercontent.com/prycken-ux/facebook/',
        'https://github.com/prycken-ux/facebook/raw/',
    ):
        try:
            with urllib.request.urlopen(prefix + commit + '/downloads/' + name,
                                        context=context, timeout=25) as response:
                data = response.read(131073)
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError('Downloaded script checksum mismatch')
            ast.parse(data.decode('utf-8-sig'))
            return data
        except Exception as error:
            print('Download failed:', str(error).splitlines()[0], flush=True)
    raise RuntimeError('Verified download failed; no unverified script executed.')


def run(root):
    root = Path(root).resolve()
    if sys.platform != 'win32':
        raise RuntimeError('Run this command on the original Windows computer.')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat() != '2026-11-02':
        raise RuntimeError('This new real-footage batch is authorized for Beijing Nov 2.')
    if not (root / 'upload_config.json').is_file():
        raise RuntimeError('Original upload_config.json not found; nothing started.')
    # Fetch both immutable programs before touching locks or installing files.
    recovery = download_verified(
        'd8c998c705801c948a230c0504fcb65653ae8086', 'recover_resume_new_batch.py',
        '2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    installer = download_verified(
        'df72d3b7d4af16a490378a6def0e90fc5b277365', 'install_new_batch_retry_tabs.py',
        'c55cccf27132bd0f5a7e051b094e8e96a14051629b357b3666e7187a3b733124')
    namespace = {'__name__': 'verified_lock_cleanup_library', '__file__': 'verified_lock_cleanup.py'}
    exec(compile(recovery, 'verified-lock-cleanup', 'exec'), namespace)
    namespace['recover_locks'](root)
    # Installer uses argv[1]; imports no task runner and sends nothing.
    sys.argv = [sys.argv[0], str(root)]
    exec(compile(installer, 'verified-new-batch-installer', 'exec'),
         {'__name__': 'verified_new_batch_installer'})
    verify = (
        "import sys;sys.path.insert(0,sys.argv[1]);"
        "import fb_upload as u,safe_video_comments as c,publish_new_with_comments as p,automatic_batch_retry as r,published_video_lookup as l;"
        "assert u.VERSION=='2.47';assert c.COMMENT_WORKFLOW_VERSION=='1.4-exact-post-lookup';"
        "assert p.PUBLISH_WORKFLOW_VERSION=='2.2-retry-tabs';assert l.LOOKUP_WORKFLOW_VERSION=='1.1-reels-tabs';"
        "assert r.AUTO_RETRY_VERSION=='1.0-before-post-once';"
        "print('INSTALL VERIFIED. No video upload started.',flush=True)"
    )
    subprocess.run([sys.executable, '-c', verify, str(root)], check=True)
    print('开始今天新批次：全部实拍，排除fb16/fb18/fb21；先发布，再安全补发一次，最后评论。不补发31号旧素材。请保持窗口打开。', flush=True)
    result = subprocess.run([sys.executable, str(root / 'publish_new_with_comments.py'), '--date', '2026-11-02', '--real-footage'])
    if result.returncode not in {0, 3}:
        raise RuntimeError('New batch stopped; preserve the output and all publication/comment/retry records.')
    if result.returncode == 3:
        print('仍有未完成或待核实项目，详见上方结果；不要清空发送记录后重复发。', flush=True)
    return result.returncode


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(run(Path(sys.argv[1])))
    except KeyboardInterrupt:
        print('已停止，保留全部发送记录。', flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP:', str(error) or type(error).__name__, flush=True)
        raise SystemExit(1)
