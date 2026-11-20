"""Cache a verified material distributor without modifying the publisher."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='0f0a228123e47671673fcabf07a199faeaa64aa1'
PACKAGE_SHA='59e1e6d216de2531800972709753b4d5e0df53f45449c93f1a5e6d3b2fb4cce3'
NAMES=('archive_history_through_20261119.py','archive_all_user_confirmed_20261117.py','material_distribution_worker_check.py','verified_publication_lock_recovery.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import archive_history_through_20261119 as r;"
        "assert r.VERSION=='1.0-historical-through-nov19-protect-nov20-onward' and r.CUTOFF=='2026-11-19' and r.TODAY=='2026-11-20';"
        "assert r.METHOD=='user_confirmed_nov19_success_archive_history_20261120';"
        "assert r.file_name('E:'+chr(92)+'videos'+chr(92)+'old.mp4')=='old.mp4';"
        "print('VERIFIED: archive proven Nov19-and-earlier account media;Nov19 USER-CONFIRMED published;preserve original older outcomes and comments;protect Nov20/weekend materials;retained files/backups;no browser/upload/scheduler changes.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/historical-archive-through-nov19-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
    if hashlib.sha256(data).hexdigest()!=PACKAGE_SHA:raise ValueError('Checksum mismatch; stopped')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist())!=len(NAMES) or set(archive.namelist())!=set(NAMES):raise ValueError('本批发布工具范围异常。')
        updates={name:archive.read(name) for name in NAMES}
    for code in updates.values():ast.parse(code.decode('utf-8-sig'))
    return updates


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的新PowerShell窗口运行。')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置。')
    updates=download();folder=root/'material-staging/tools'/PACKAGE_SHA[:16]
    for item in (root/'material-staging',root/'material-staging/tools',folder):
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):raise ValueError('工具缓存目录是链接。')
        item.mkdir(exist_ok=True)
    for name,data in updates.items():
        path=folder/name
        if path.is_symlink():raise ValueError('工具缓存文件是链接。')
        if path.exists():
            if path.read_bytes()!=data:raise ValueError('同指纹工具内容异常，未覆盖。')
            continue
        with tempfile.NamedTemporaryFile(dir=folder,delete=False) as handle:temporary=Path(handle.name);handle.write(data)
        try:temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
    subprocess.run([sys.executable,'-c',VERIFY,str(folder),str(root)],check=True)
    print('仅归档有可靠来源的11月19日及以前历史视频；昨天视频登记用户确认已发布成功，较早视频保留原结果。今天和周末待发素材、评论、程序及登录资料保留，不删除视频。若当前有发布任务则先等待它结束；请保持窗口打开，可最小化。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'archive_history_through_20261119.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('归档及用户确认成功标记尚未全部完成；文件和逐条进度保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
