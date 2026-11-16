"""Cache a verified new publisher without changing a currently running batch."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='4e55e1c3e733557edc3200dd886ccfd4563801a6'
PACKAGE_SHA='3664cf81e127211e93b6bfba4ac3b494e6bb108cdf7102ae578bb7b782041989'
NAMES=('prepare_new50_queue_20261116.py','publish_queued_new50_20261116.py','queued_new50_workflow.py','retry_queued_new50_beforepost.py','stage_new50_materials_v3.py','material_distribution_worker_check.py','verified_publication_lock_recovery.py','finish_first24_nov14_on_nov16.py','retry_first24_original_prepost_on_nov16.py','publish_staged_first24_nov14.py','stage_next_materials_20261114_v1.py','publish_all_distributed_nov13.py','publish_unplanned_fortysix_nov14.py','queue_new50_after_first24.ps1')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import prepare_new50_queue_20261116 as p;import publish_queued_new50_20261116 as r;"
        "assert len(p.owned.NEW)==50 and sorted(p.owned.NEW)[0]=='fb25' and sorted(p.owned.NEW)[-1]=='fb74';"
        "assert p.AUTH=='user-confirmed-real-new50-request-20261116-v1';"
        "assert p.stage.VERSION=='1.3-reserved50-independent-staging';"
        "assert r.queued.VERSION=='1.0-source-bound-cross-midnight-real50';r.first.workflow.require_versions();"
        "print('INSTALL VERIFIED: allocate exact50 fb25-fb74, real footage AI OFF, retained source, wait for first24 run then queued publication/comments, actual dates across midnight. No video uploaded yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/new50-real-queued-publication-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
    if hashlib.sha256(data).hexdigest()!=PACKAGE_SHA:raise ValueError('Checksum mismatch; stopped')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist())!=len(NAMES) or set(archive.namelist())!=set(NAMES):raise ValueError('本批发布工具范围异常。')
        updates={name:archive.read(name) for name in NAMES}
    for name,code in updates.items():
        if name.endswith('.py'):ast.parse(code.decode('utf-8-sig'))
        else:code.decode('utf-8-sig')
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
    print('本次为新增fb25–fb74独立分配50条实拍素材，AI标签关闭。优先用总素材目录剩余新视频，不足时弹窗选择；保留原件。准备后另开排队窗口，等前面44个目标本轮处理结束并退出后发布。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'prepare_new50_queue_20261116.py'),str(root)])
    if result.returncode not in {0,130}:raise RuntimeError('新增50素材准备/排队未完成；原素材、分配进度和原发布任务均保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
