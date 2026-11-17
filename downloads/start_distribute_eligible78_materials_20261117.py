"""Cache a verified material distributor without modifying the publisher."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='534f9ebd29184384073935102588f9e49b68ac62'
PACKAGE_SHA='bdd9e835f0b8928b771fbe519d485532e4645afc78de8984cbd8a9ee7ea825c7'
NAMES=('distribute_eligible78_materials_20261117.py','stage_eligible78_materials_v4.py','material_distribution_worker_check.py','verified_publication_lock_recovery.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import distribute_eligible78_materials_20261117 as r;"
        "assert r.VERSION=='1.0-eligible78-retain-manual-fb23' and len(r.EXPECTED)==78;"
        "assert len(r.UNAVAILABLE)==15 and ('fb23','personal') not in r.EXPECTED;"
        "assert not ({a for a,t in r.EXPECTED}&r.UNAVAILABLE);"
        "assert r.stage.VERSION=='1.4-eligible78-excluding-user-problem-accounts';"
        "assert r.workers.WORKER_VERSION=='1.1-verified-windows-venv-launch-chain';"
        "print('INSTALL VERIFIED: allocate78, skip15 unavailable and manual fb23; retained source, safe wait and import. No video published.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/eligible78-material-distribution-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('请选择素材总文件夹：跳过15个问题账号及已手动放好的fb23，共78个目标，每目标1条，按文件名自然顺序，保留原件。若当前发布尚未结束，将先准备素材，再自动导入。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'distribute_eligible78_materials_20261117.py'),str(root)])
    if result.returncode not in {0,130}:raise RuntimeError('素材分配暂未完成；原素材、当前发布任务及分配进度均保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
