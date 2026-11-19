"""Cache the verified audience prompt installer; no publication is started."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='264b2b94de54a06dd8daef2cc45831f05c05a1f3'
PACKAGE_SHA='5ae342f19615c994c2a5cd9cc035369639efcd9f1f6a8069c36a0e54dae3c5a5'
NAMES=('install_reel_audience_recovery_20261119.py', 'reel_audience_dialog_recovery.py', 'material_distribution_worker_check.py')
VERIFY=("import ast,sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);"
        "import install_reel_audience_recovery_20261119 as r;import reel_audience_dialog_recovery as h;"
        "assert r.VERSION=='1.0-install-audience-prompt-only-no-publication';"
        "assert h.VERSION=='1.0-reel-audience-close-or-continue';"
        "assert r.workers.WORKER_VERSION=='1.1-verified-windows-venv-launch-chain';"
        "ast.parse(r.PATCHED_FUNCTION);assert 'wait_for_public_controls' in r.PATCHED_FUNCTION;"
        "print('INSTALLER VERIFIED: identified Reel audience prompts only, Close/Continue then verify Public; backup and rollback; no video publication or retry.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/reel-audience-dialog-recovery-nov19-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('仅安装公开范围弹窗自动处理修正。先备份原程序；不发布视频、不启动昨天的补发，也不修改账号、素材或成功状态。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'install_reel_audience_recovery_20261119.py'),str(root)])
    if result.returncode not in {0,130}:raise RuntimeError('弹窗修正安装未完成；原记录保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
