"""Cache the fixed, source-bound Nov19 textbox32 retry without replacing root programs."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='1a4ad2599f36c7754ee9b23bcd8346996d7d412a'
PACKAGE_SHA='795d79d926614cbd1f11c31971dd7cf7b8ce144089a4827fa5e48715db4a4029'
NAMES=('retry_nov19_textbox32_on_nov20.py', 'publish_eligible60_materials_20261119.py', 'publication_response_finish_guard.py', 'publication_background_policy.py', 'distribute_eligible60_materials_20261119.py', 'eligible60_publication_workflow.py', 'retry_eligible60_prepost_20261119.py', 'stage_eligible60_materials_v6.py', 'material_distribution_worker_check.py', 'verified_publication_lock_recovery.py', 'finish_first24_nov14_on_nov16.py', 'retry_first24_original_prepost_on_nov16.py', 'publish_staged_first24_nov14.py', 'stage_next_materials_20261114_v1.py', 'publish_all_distributed_nov13.py', 'publish_unplanned_fortysix_nov14.py', 'publication_content_20261119.py', 'reel_audience_prompt_hook_20261119.py', 'pending_video_comment_lookup_20261119.py', 'reel_audience_dialog_recovery.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import publish_eligible60_materials_20261119 as r;"
        "assert r.VERSION=='1.0-new60-paused34-nov19-book-pending-comments' and len(r.EXPECTED)==60;"
        "assert len(r.BLOCKED)==34 and {'fb40','fb43','fb17','fb23'}<=r.BLOCKED and len(r.active_new())==18;"
        "assert {('fb37','personal'),('fb63','personal')}<=r.EXPECTED and not ({a for a,t in r.EXPECTED}&r.BLOCKED);"
        "assert r.REQUEST=='logs/eligible60-real-publication-request-20261119.json';"
        "assert r.content_today.CONTENT['sha256']=='ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894';"
        "assert r.pending_comments.VERSION=='1.0-pending-video-exact-lookup-before-comments';"
        "assert r.audience_hook.VERSION=='1.0-scoped-audience-close-continue-before-public';import reel_audience_dialog_recovery as recovery;assert recovery.VERSION=='1.1-contenteditable-caption-audience-recovery';import retry_nov19_textbox32_on_nov20 as retry;assert len(retry.SPEC)==32 and retry.SOURCE_PREFIX=='7702cad3af70ce94' and retry.SKIP_RETRY=={'fb52'} and not ({a for a,t in retry.SPEC}&r.BLOCKED);"
        "assert r.stage.VERSION=='1.6-eligible60-skipping34-independent-staging';r.first.workflow.require_versions();"
        "print('VERIFIED: exact Nov19 textbox32 original pre-Post failures only, one new attempt each;skip34 and fb52;real AI OFF;headless;corrected B2F4D52E comments;native/contenteditable caption fix;no old pending reuploads. No video uploaded yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/nov19-textbox32-retry-on-nov20-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('本次仅对11月19日文案框故障导致发布前失败的32条原视频各补发一次。保留成功及26条旧待核实视频，跳过34个停用账号及fb52；后台处理，登录验证先跳过，新补发的视频沿用11月19日正文及更正后的评论、AI标签关闭。请保持此窗口打开，可最小化。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'retry_nov19_textbox32_on_nov20.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('本批发布尚未完成；原素材、视频/评论记录和补发进度均保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
