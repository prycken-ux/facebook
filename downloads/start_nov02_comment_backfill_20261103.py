"""Start only the authorized Nov-2 published-video comment backfill on Nov 3."""
import ast,hashlib,ssl,subprocess,sys,urllib.request
from datetime import datetime,timedelta,timezone
from pathlib import Path

RUNNER_COMMIT='9c1108e79f24dfcacd34d1e5cea39e7ec5e53d85'
RUNNER_SHA256='4fccb2aa3f5249ec18c2fb5a9d953c4763c4d0007e097bc532f2b16d03ec92ec'
PROBE = """import sys
sys.path.insert(0,sys.argv[1])
try:
 import fb_upload as u,safe_video_comments as c,publish_new_with_comments as p,automatic_batch_retry as r
 ok=(u.VERSION=='2.47' and getattr(u,'IMMEDIATE_COMMENT_VERSION','')=='1.0-receipt-first-reload' and p.PUBLISH_WORKFLOW_VERSION=='2.3-immediate-comments' and r.AUTO_RETRY_VERSION=='1.1-immediate-aware' and callable(getattr(c,'immediate_verified_comment',None)))
except Exception:
 ok=False
sys.exit(0 if ok else 10)
"""


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


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('Run on the original Windows upload computer.')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-03':
        raise ValueError('This Nov-2 comments-only backfill is authorized for Beijing Nov 3.')
    if not (root/'upload_config.json').is_file():raise ValueError('Original upload_config.json not found; nothing started.')
    runner=download_verified(RUNNER_COMMIT,'backfill_nov02_published_comments_20261103.py',RUNNER_SHA256)
    installer=download_verified('43bb736120d2267bac19b2aa7d4c4ab163e2f83b','install_immediate_comments.py','3a40966fc86a1e67e7b3a528b4839f0e2f60ff69440530459a11f0ec79adf32c')
    recovery=download_verified('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    namespace={'__name__':'verified_lock_cleanup_library','__file__':'verified_lock_cleanup.py'}
    exec(compile(recovery,'verified-lock-cleanup','exec'),namespace);namespace['recover_locks'](root)
    probe=subprocess.run([sys.executable,'-c',PROBE,str(root)],capture_output=True)
    if probe.returncode:
        print('正在校验并更新评论模块；尚未启动任何发布或评论。',flush=True)
        namespace={'__name__':'verified_immediate_installer'}
        exec(compile(installer,'verified-immediate-comment-installer','exec'),namespace);namespace['install'](root)
        if subprocess.run([sys.executable,'-c',PROBE,str(root)],capture_output=True).returncode:
            raise RuntimeError('Fresh comment feature verification failed; no comments started.')
    print('开始只给11月2日已确认成功的26条原视频补评论；不上传或补发视频。请保持窗口打开。',flush=True)
    child='import sys;exec(compile(sys.stdin.buffer.read(),"verified-nov02-comment-backfill","exec"))'
    result=subprocess.run([sys.executable,'-c',child,str(root)],input=runner)
    if result.returncode not in {0,3}:raise RuntimeError('Comment backfill stopped; preserve output and all send-intent records.')
    if result.returncode==3:print('仍有未完成或待核实的评论，详见上方逐条结果；不要清空记录后重复发送。',flush=True)
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已停止，保留已有发送记录。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
