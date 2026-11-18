"""Cache a verified material distributor without modifying the publisher."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='f0185a7556fbc496b46d25fecb831f06a3655754'
PACKAGE_SHA='30045ddde8c5d0cb8e1bacd72e67631bc3e539cd6dbf3ddeca1eb814c9b166c6'
NAMES=('publish_eligible78_materials_20261117.py','publication_response_finish_guard.py','publication_background_policy.py','distribute_eligible78_materials_20261117.py', 'eligible78_publication_workflow.py', 'retry_eligible78_prepost_20261117.py', 'stage_eligible78_materials_v4.py', 'material_distribution_worker_check.py', 'verified_publication_lock_recovery.py', 'finish_first24_nov14_on_nov16.py', 'retry_first24_original_prepost_on_nov16.py', 'publish_staged_first24_nov14.py', 'stage_next_materials_20261114_v1.py', 'publish_all_distributed_nov13.py', 'publish_unplanned_fortysix_nov14.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import publish_eligible78_materials_20261117 as r;"
        "assert r.VERSION=='1.2-original78-current62-paused32-no-verification' and len(r.EXPECTED)==78;"
        "assert len(r.BLOCKED)==16 and {'fb17','fb23','fb74'}<=r.BLOCKED;"
        "assert len(r.active_new())==20;assert len(r.PAUSED)==32 and len(r.EXPECTED-{p for p in r.EXPECTED if p[0] in r.PAUSED})==62;assert len(r.ACTIVE_NEW)==36 and not ({a for a,t in r.EXPECTED}&r.BLOCKED);"
        "assert r.queued.VERSION=='1.0-real-eligible78-source-bound-manual-last';assert r.response_guard.VERSION=='1.0-completed-response-capture-bounded-diagnostics';assert r.background_policy.VERSION=='1.0-headless-auto-manual-verification-only';r.first.workflow.require_versions();"
        "print('INSTALL VERIFIED: original78 scope/current62 active, real AI OFF,32 paused without verification including fb23, original caption/comments, auto-first then safe retry/comments, manual checks last, immutable progress. Completed-response guard enabled; original progress retained. No video uploaded yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/eligible78-real-publication-v5.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('最新暂停32个账号：不分配、不验证、不发布、不补发。原78目标清单保持，本次仅继续62个可用目标，自动任务无窗口后台运行。全部实拍、AI标签关闭。32个暂停账号均直接跳过。先自动发布可用视频，再安全补发视频及原评论，最后集中人工检查。请保持窗口打开，可最小化。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'publish_eligible78_materials_20261117.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('本批发布尚未完成；原素材、视频/评论记录和补发进度均保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
