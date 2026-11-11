"""Install a future-only, bounded comment retry pass; never backfill old comments."""
import ast
import hashlib
import importlib.util
import io
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

COMMIT='3b3c148971c1c9416deaab8e3e112faaf913a329'
PACKAGE_SHA='12b24103e79f6d62d5ba2b1c9547e6da515249178206a00c4bc9cc2aa347425d'
NAMES=('publication_preferences.py','scheduled_material_batch.py','publish_priority_batch.py','daily_publish_and_comments.py','safe_video_comments.py','automatic_comment_retry.py')
PROBE=("import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
       "import fb_upload as u,publication_preferences as p,scheduled_material_batch as b,publish_priority_batch as q,daily_publish_and_comments as d,scheduled_priority_workflow as w,safe_video_comments as c,automatic_comment_retry as a;"
       "assert u.ROOT.resolve()==Path(sys.argv[1]).resolve();w.require_versions();"
       "assert p.CONTENT_UPDATES_VERSION==b.CONTENT_UPDATES_VERSION==q.CONTENT_UPDATES_VERSION==d.CONTENT_UPDATES_VERSION=='1.0-frozen-caption-and-comment';"
       "assert c.COMMENT_RECOVERY_VERSION==a.VERSION==d.COMMENT_RECOVERY_VERSION==q.COMMENT_RECOVERY_VERSION==b.COMMENT_RETRY_POLICY=='1.0-scoped-retry-readonly-reconcile';"
       "item=p.save_content_authorized();assert item==p.content_policy('2026-11-11');"
       "assert item['payload']['caption']==p.EVERYDAY_CAPTION;assert item['payload']['comment']==p.EVERYDAY_COMMENT;"
       "assert (u.ROOT/'common_caption_today.txt').read_text(encoding='utf-8-sig').strip()==p.EVERYDAY_CAPTION;"
       "print('之后新批次的失败评论自动补评已启用；历史评论不补发。未创建批次或发送评论。',flush=True);"
       "print('正文：',flush=True);print(p.EVERYDAY_CAPTION,flush=True);print('评论：',flush=True);print(p.EVERYDAY_COMMENT,flush=True)")


def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    url='https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/nov11-future-comment-retry-v1.zip'
    with urllib.request.urlopen(url,context=context,timeout=30) as response:data=response.read(1024*1024+1)
    if hashlib.sha256(data).hexdigest()!=PACKAGE_SHA:raise ValueError('Checksum mismatch; stopped')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist())!=len(NAMES) or set(archive.namelist())!=set(NAMES):raise ValueError('更新包文件范围不一致')
        updates={name:archive.read(name) for name in NAMES}
    for data in updates.values():ast.parse(data.decode('utf-8-sig'))
    return updates


def write_atomic(root,path,data):
    with tempfile.NamedTemporaryFile(dir=root,delete=False) as handle:temporary=Path(handle.name);handle.write(data)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def clear_caches(root):
    for name in NAMES:Path(importlib.util.cache_from_source(str(root/name))).unlink(missing_ok=True)


def install(root,updates):
    root=Path(root).resolve();sys.path.insert(0,str(root))
    import fb_upload as upload
    import add_fb_accounts as accounts
    if (upload.ROOT.resolve()!=root or accounts.ROOT.resolve()!=root or upload.VERSION!='2.47'
            or not (root/'publication_preferences.json').is_file() or not (root/'upload_config.json').is_file()):
        raise ValueError('请在原上传目录运行；原配置或发布规则缺失，未另建配置')
    if set(updates)!=set(NAMES):raise ValueError('安装文件范围不一致')
    with accounts.locked():
        backup=root/'backups'/('future-comment-retry-install-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
        paths=[root/name for name in NAMES]+[root/'publication_preferences.json',root/'common_caption_today.txt']
        originals={path:path.read_bytes() if path.is_file() else None for path in paths}
        for path,data in originals.items():
            if data is not None:(backup/path.name).write_bytes(data)
        try:
            for name in NAMES:write_atomic(root,root/name,updates[name])
            clear_caches(root)
            subprocess.run([sys.executable,'-c',PROBE,str(root)],check=True)
        except BaseException:
            for path,data in originals.items():
                if data is None:path.unlink(missing_ok=True)
                else:shutil.copy2(backup/path.name,path)
            clear_caches(root);raise
        print('原程序与文案设置备份：',backup,flush=True)
        print('之后新建批次：先发布、再安全补发视频、再评论，最后补评一次；旧批次不新增补评任务。',flush=True)
    return 0


def main():
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    return install(Path(sys.argv[1]),download())


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(main())
    except KeyboardInterrupt:print('已停止，原设置有备份。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
