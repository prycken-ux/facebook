"""Cache a verified material distributor without modifying the publisher."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='a22634e17cbaef520867a86cf9b712a27adea037'
PACKAGE_SHA='edb35d3c72b58b8d27565d4a5d2f0ce7df6410a32249a8bf5deb59fc42132dce'
NAMES=('archive_all_user_confirmed_20261117.py','material_distribution_worker_check.py','verified_publication_lock_recovery.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import archive_all_user_confirmed_20261117 as r;"
        "assert r.VERSION=='1.0-all74-media-user-confirmed-archive' and len(r.ACCOUNTS)==74;"
        "assert r.METHOD=='user_confirmed_all_existing_account_videos_20261117';"
        "assert {'fb17','fb23','fb74'}<=r.ACCOUNTS;"
        "print('INSTALL VERIFIED: archive all existing fb01-fb74 media and pages, mark USER-CONFIRMED published, retained media, preserved comments, immutable snapshot and backups. No platform receipt claimed.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/all74-user-confirmed-archive-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('按用户明确确认：fb01–fb74及公共主页现有视频全部归档为已发布成功，包含新素材和fb23。不选择新素材目录，不删除视频，不修改评论。当前任务结束后自动执行；保留窗口。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'archive_all_user_confirmed_20261117.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('归档及用户确认成功标记尚未全部完成；文件和逐条进度保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
