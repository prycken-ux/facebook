"""Cache exact Nov19 archival and read-only sample diagnostics without replacing root programs."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='9c084427552cd763eef203f7124ca98e3ef3d712'
PACKAGE_SHA='5d0deaee590614d90f175ca94989a10a153103c1642ae7d3ee7cfc856ae7c32a'
NAMES=('archive_nov19_user_confirmed_20261120.py', 'archive_all_user_confirmed_20261117.py', 'diagnose_nov19_comment_samples_20261120.py', 'publish_eligible60_materials_20261119.py', 'publication_response_finish_guard.py', 'publication_background_policy.py', 'distribute_eligible60_materials_20261119.py', 'eligible60_publication_workflow.py', 'retry_eligible60_prepost_20261119.py', 'stage_eligible60_materials_v6.py', 'material_distribution_worker_check.py', 'verified_publication_lock_recovery.py', 'finish_first24_nov14_on_nov16.py', 'retry_first24_original_prepost_on_nov16.py', 'publish_staged_first24_nov14.py', 'stage_next_materials_20261114_v1.py', 'publish_all_distributed_nov13.py', 'publish_unplanned_fortysix_nov14.py', 'publication_content_20261119.py', 'reel_audience_prompt_hook_20261119.py', 'pending_video_comment_lookup_20261119.py', 'reel_audience_dialog_recovery.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import archive_nov19_user_confirmed_20261120 as r;"
        "assert r.VERSION=='1.0-nov19-exact60-user-confirmed-archive-comments-retained' and len(r.EXPECTED)==60;"
        "assert r.SOURCE_PREFIX=='7702cad3af70ce94' and len(r.MANUAL_COMMENTS)==2 and r.METHOD=='user_confirmed_nov19_videos_published_20261120';"
        "assert r.MANUAL_COMMENTS['fb04','personal'].endswith('/1450837626603440') and r.MANUAL_COMMENTS['fb01','page01'].endswith('/1114161698059872');"
        "import diagnose_nov19_comment_samples_20261120 as d;assert d.VERSION=='1.0-two-user-linked-reels-readonly-comment-diagnostics';"
        "print('VERIFIED: exact original Nov19 sixty videos USER-CONFIRMED archive; preserve new materials and comments;two manual comments recorded;read-only sample diagnostics;no video/comment upload.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/nov19-exact60-user-confirmed-archive-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('按用户确认只归档11月19日原60条视频，保留今天及周末新素材；登记fb04个人号和fb01公共主页已手动评论，其他评论状态保留。之后后台只读检查这两个链接，生成评论定位诊断ZIP，不发视频或评论。当前任务运行则先等待，请保持此窗口打开。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'archive_nov19_user_confirmed_20261120.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('本批发布尚未完成；原素材、视频/评论记录和补发进度均保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
