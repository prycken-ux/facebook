"""Cache a verified material distributor without modifying the publisher."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='778894c21d039030a12a725ec664cbf5dc09a800'
PACKAGE_SHA='21933402224620ddbb561b2fd18f5f1e337bc5abf409279f7a9aec0632d369f1'
NAMES=('publish_eligible60_materials_20261119.py', 'publication_response_finish_guard.py', 'publication_background_policy.py', 'distribute_eligible60_materials_20261119.py', 'eligible60_publication_workflow.py', 'retry_eligible60_prepost_20261119.py', 'stage_eligible60_materials_v6.py', 'material_distribution_worker_check.py', 'verified_publication_lock_recovery.py', 'finish_first24_nov14_on_nov16.py', 'retry_first24_original_prepost_on_nov16.py', 'publish_staged_first24_nov14.py', 'stage_next_materials_20261114_v1.py', 'publish_all_distributed_nov13.py', 'publish_unplanned_fortysix_nov14.py', 'publication_content_20261119.py', 'reel_audience_prompt_hook_20261119.py', 'pending_video_comment_lookup_20261119.py', 'reel_audience_dialog_recovery.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import publish_eligible60_materials_20261119 as r;"
        "assert r.VERSION=='1.0-new60-paused34-nov19-book-pending-comments' and len(r.EXPECTED)==60;"
        "assert len(r.BLOCKED)==34 and {'fb40','fb43','fb17','fb23'}<=r.BLOCKED and len(r.active_new())==18;"
        "assert {('fb37','personal'),('fb63','personal')}<=r.EXPECTED and not ({a for a,t in r.EXPECTED}&r.BLOCKED);"
        "assert r.REQUEST=='logs/eligible60-real-publication-request-20261119.json';"
        "assert r.content_today.CONTENT['sha256']=='ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894';"
        "assert r.pending_comments.VERSION=='1.0-pending-video-exact-lookup-before-comments';"
        "assert r.audience_hook.VERSION=='1.0-scoped-audience-close-continue-before-public';"
        "assert r.stage.VERSION=='1.6-eligible60-skipping34-independent-staging';r.first.workflow.require_versions();"
        "print('VERIFIED: new60/paused34;Nov19 exact caption and CORRECTED B2F4D52E comment;real AI OFF;headless;pending videos get exact-video comment lookup;audience Close/Continue guard;immutable retries and manual-last. No video uploaded yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/eligible60-nov19-book-publication-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('本次仅发布11月19日新分配的60条视频，跳过34个停用账号。全部实拍、AI标签关闭，使用今日新正文及更正后的B2F4D52E评论链接；无窗口后台处理。待核实也尝试定位对应视频评论；明确失败安全补发，人工事项留到最后。请保持此窗口打开，可最小化。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'publish_eligible60_materials_20261119.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('本批发布尚未完成；原素材、视频/评论记录和补发进度均保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
