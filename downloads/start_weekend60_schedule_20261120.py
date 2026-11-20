"""Cache three date-bound headless publication schedules without replacing root programs."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='242f35fe2c4c2c7ade4755d274acb954906d69e9'
PACKAGE_SHA='ba94d914345c9974dcf48e72beae3d8a8799cab1004265725a748e274fd5506b'
NAMES=('weekend60_schedule_20261120.py', 'weekend60_run_20261120.py', 'weekend60_run_20261121.py', 'weekend60_run_20261122.py', 'local_file_input.py', 'publish_eligible60_materials_20261119.py', 'publication_response_finish_guard.py', 'publication_background_policy.py', 'distribute_eligible60_materials_20261119.py', 'eligible60_publication_workflow.py', 'retry_eligible60_prepost_20261119.py', 'stage_eligible60_materials_v6.py', 'material_distribution_worker_check.py', 'verified_publication_lock_recovery.py', 'finish_first24_nov14_on_nov16.py', 'retry_first24_original_prepost_on_nov16.py', 'publish_staged_first24_nov14.py', 'stage_next_materials_20261114_v1.py', 'publish_all_distributed_nov13.py', 'publish_unplanned_fortysix_nov14.py', 'publication_content_20261119.py', 'reel_audience_prompt_hook_20261119.py', 'pending_video_comment_lookup_20261119.py', 'reel_audience_dialog_recovery.py')
VERIFY=("import sys,inspect;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import weekend60_schedule_20261120 as r;"
        "assert r.VERSION=='1.0-weekend60-nov20-22-beijing1710-real-off' and r.TIME=='17:10' and r.DAYS==('2026-11-20','2026-11-21','2026-11-22');"
        "assert len(r.app.EXPECTED)==60 and len(r.app.BLOCKED)==34 and {'fb17','fb23','fb40','fb43'}<=r.app.BLOCKED;"
        "assert r.content.CONTENT['sha256']=='ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894';"
        "import reel_audience_dialog_recovery as a,local_file_input as f;assert a.VERSION=='1.1-contenteditable-caption-audience-recovery';"
        "assert 'upload.inbox_for' in inspect.getsource(f._source);r.app.first.workflow.require_versions();"
        "print('VERIFIED: Fri/Sat/Sun separate60 allocations;one-shot17:10+08:00 schedules;real footage AI OFF;source-bound date and SHA;headless;safe retries and exact-video comments;manual issues skipped. No video uploaded yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/weekend60-nov20-22-beijing1710-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
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
    print('将依次选择周五11月20日、周六21日、周日22日三个素材文件夹，各分配60条并保留原件，跳过34个停用账号。分别注册每天北京时间17:10的一次性后台发布和评论任务；全部实拍、关闭AI标签，沿用已确认正文和更正后的评论，手动验证先跳过。设置阶段不提前上传视频。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'weekend60_schedule_20261120.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('三天分配或定时注册尚未全部完成；原素材及固定进度保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
