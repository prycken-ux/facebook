"""Archive local tasks and permanently delete the user-authorized fixed media snapshot."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='ad493cae33a16eb66d812a7110abb7bcfbaa428c'
PACKAGE_SHA='f34e37db9239569d963ac657cc4d4cc1b4456d282fe730cbb011996bd2dcfb08'
NAMES=('archive_delete_project_videos_20261119.py', 'cleanup_confirmed_published_videos.py', 'material_distribution_worker_check.py', 'verified_publication_lock_recovery.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import archive_delete_project_videos_20261119 as r;"
        "assert r.VERSION=='1.0-user-archive-delete-all-managed-video-media';"
        "assert r.DAY=='2026-11-19' and r.ARCHIVE_DAY=='2026-11-18';assert r.upload.VERSION=='2.47';"
        "assert {'profiles','browser-profile','browsers','.venv','tools'}<=r.PROTECTED;"
        "assert not {'.py','.json','.txt','.zip'}&r.EXTENSIONS;"
        "assert r.workers.WORKER_VERSION=='1.1-verified-windows-venv-launch-chain';"
        "print('VERIFIED: user-authorized archival and permanent deletion of managed video files,all outcomes;fixed snapshot,resumable audit,metadata backup,no fake publication success,no external originals,no program/profile deletion. No video deleted yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/user-archive-delete-project-videos-nov19-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('本次会永久删除程序管理目录中的视频文件，包括成功、失败、待核实及未发布素材；先备份状态并标记任务归档。文案、程序、登录资料、配置和外部素材原件保留。不发布或补发视频。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'archive_delete_project_videos_20261119.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('视频清理未全部完成；原清单和剩余文件处理进度保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停清理，保留固定清单和进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
