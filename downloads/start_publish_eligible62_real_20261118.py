"""Cache a verified material distributor without modifying the publisher."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='97dca14ff7b1eb16e026baf8b2ad83105788817d'
PACKAGE_SHA='c794b70404d264c6a055a106d8cebfec85b894554258b21b1458ea21c996c920'
NAMES=('publish_eligible62_materials_20261118.py','publication_response_finish_guard.py','publication_background_policy.py','distribute_eligible62_materials_20261118.py', 'eligible62_publication_workflow.py', 'retry_eligible62_prepost_20261118.py', 'stage_eligible62_materials_v5.py', 'material_distribution_worker_check.py', 'verified_publication_lock_recovery.py', 'finish_first24_nov14_on_nov16.py', 'retry_first24_original_prepost_on_nov16.py', 'publish_staged_first24_nov14.py', 'stage_next_materials_20261114_v1.py', 'publish_all_distributed_nov13.py', 'publish_unplanned_fortysix_nov14.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import publish_eligible62_materials_20261118 as r;"
        "assert r.VERSION=='1.0-new62-paused32-real-background-manual-last' and len(r.EXPECTED)==62;"
        "assert len(r.BLOCKED)==32 and r.PAUSED==r.BLOCKED and r.BLOCKED==r.stage.UNAVAILABLE;"
        "assert len(r.active_new())==20 and len(r.ALLOWED)==42 and not ({a for a,t in r.EXPECTED}&r.BLOCKED);"
        "assert r.REQUEST=='logs/eligible62-real-publication-request-20261118.json';"
        "assert r.queued.VERSION=='1.0-real-eligible62-source-bound-manual-last';"
        "assert r.stage.VERSION=='1.5-eligible62-skipping32-independent-staging';"
        "assert r.response_guard.VERSION=='1.0-completed-response-capture-bounded-diagnostics';"
        "assert r.background_policy.VERSION=='1.0-headless-auto-manual-verification-only';r.first.workflow.require_versions();"
        "print('INSTALL VERIFIED: new62 allocated videos only;32 paused;real AI OFF;original captions/comments;headless automatic processing;bounded retries and manual checks last. No video uploaded yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/eligible62-real-publication-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('最新暂停32个账号：不验证、不发布、不补发。本次只发布新分配的62条素材，自动任务无窗口后台运行。全部实拍、AI标签关闭。32个暂停账号均直接跳过。先自动发布可用视频，再安全补发视频及原评论，最后集中人工检查。请保持窗口打开，可最小化。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'publish_eligible62_materials_20261118.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('本批发布尚未完成；原素材、视频/评论记录和补发进度均保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
