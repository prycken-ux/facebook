"""Verified Windows launcher: Nov13 originals first, then all fifty new accounts."""
import ast,hashlib,importlib.util,io,shutil,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='fb75f140366f83f3fff376bc160cbf7e6eaa425e'
PACKAGE_SHA='1cb7523994daca63fedb70d161eb45b9c32de5aa979622511b5347e7c87ac975'
NAMES=('personal_owner_routes.py','recovery_numeric_identity.py','page_reel_ai_compat.py','distribute_video_materials.py','archive_nov12_materials_20261113.py','capture_current_publication.py','publish_distributed_nov13_first24.py','personal_owner_registration.py','publish_all_distributed_nov13.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);"
        "import publish_all_distributed_nov13 as a;r=a.first;"
        "assert r.upload.VERSION=='2.47';r.workflow.require_versions();"
        "assert r.personals.VERSION=='1.0-me-bound-personal-aliases';"
        "assert r.numeric.VERSION=='1.0-numeric-actor-with-guided-picker';"
        "assert r.editor.VERSION=='1.0-styled-ai-controls';"
        "assert a.registration.NAME_REUSE_VERSION=='1.0-verified-owner-name-cache';"
        "assert r.capture.VERSION=='1.0-frozen-job-passive-publication-evidence';"
        "assert r.materials.SCOPED_TARGETS_VERSION=='1.1-two-wave-scopes';"
        "assert r.DAY=='2026-11-13' and r.ALLOWED=={'fb%02d'%n for n in range(1,25)};"
        "assert a.NEW=={'fb%02d'%n for n in range(25,75)};"
        "assert a.BATCH_ID=='personal-20261112-fifty-fb25-fb74';"
        "print('INSTALL VERIFIED: Nov13 new assigned videos, old accounts and Pages first, then owned fb25-fb74, retry and comments in both waves. No video uploaded yet.',flush=True)")


def download(commit,name,expected,limit=131073):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(base+commit+'/downloads/'+name,context=context,timeout=25) as response:data=response.read(limit)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Checksum mismatch')
            return data
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    raise RuntimeError('校验下载失败，未启动今天批次')


def unpack(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist())!=len(NAMES) or set(archive.namelist())!=set(NAMES):raise ValueError('更新包文件范围不一致')
        updates={name:archive.read(name) for name in NAMES}
    for content in updates.values():ast.parse(content.decode('utf-8-sig'))
    return updates


def write_atomic(root,path,data):
    with tempfile.NamedTemporaryFile(dir=root,delete=False) as handle:temporary=Path(handle.name);handle.write(data)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def clear_caches(root):
    for name in NAMES:
        path=Path(importlib.util.cache_from_source(str(root/name)))
        if path.is_file():path.unlink()


def install(root,updates):
    sys.path.insert(0,str(root))
    from add_fb_accounts import locked
    import fb_upload as upload
    if upload.VERSION!='2.47' or getattr(upload,'IMMEDIATE_COMMENT_VERSION','')!='1.0-receipt-first-reload':
        raise ValueError('需使用今天已校验的2.47发布核心，未覆盖核心程序')
    with locked():
        backup=root/'backups'/('priority-batch-install-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
        originals={name:(root/name).read_bytes() if (root/name).is_file() else None for name in NAMES}
        for name,content in originals.items():
            if content is not None:(backup/name).write_bytes(content)
        changed=[]
        try:
            for name in NAMES:write_atomic(root,root/name,updates[name]);changed.append(name)
            clear_caches(root)
            subprocess.run([sys.executable,'-c',VERIFY,str(root)],check=True)
        except BaseException:
            for name in reversed(changed):
                if originals[name] is None:(root/name).unlink(missing_ok=True)
                else:write_atomic(root,root/name,originals[name])
            clear_caches(root);raise
        print('今天两批新视频发布流程已安装并核验，原程序已备份：',backup,flush=True)


def start(root,real_footage=False):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-13':
        raise ValueError('此指令仅授权11月13日按两批顺序发布今天分配的全部新视频')
    if not real_footage:raise ValueError('今天新素材尚未确认全部实拍，未启动')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置，未启动')
    updates=unpack(download(COMMIT,'nov13-distributed-two-waves-all-accounts-v1.zip',PACKAGE_SHA,2*1024*1024+1))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    ast.parse(helper.decode('utf-8-sig'))
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace)
    namespace['recover_locks'](root)
    install(root,updates)
    print('开始今天全部新视频：先fb01–fb24及公共主页，第一批本轮发布、补发和评论处理后，自动接着fb25–fb74。只选今天分配记录中的原视频，同目录旧视频归档。两批均用原实拍文案和评论，失败安全补试；新账号自动核实已有登录和本人名称。请保持窗口打开。',flush=True)
    result=subprocess.run([sys.executable,str(root/'publish_all_distributed_nov13.py'),str(root),'--real-footage'])
    if result.returncode not in {0,3,130}:raise RuntimeError('今天两批流程已停止；保留归档、发布及评论记录，重跑同一命令继续今天原清单')
    if result.returncode==3:print('仍有失败、待核实或未完成评论；详见逐条结果。视频和评论分开统计，不会重复上传待核实视频。',flush=True)
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        raise SystemExit(start(Path(sys.argv[1]),'--real-footage' in sys.argv[2:]))
    except KeyboardInterrupt:print('已暂停，保留全部记录；重跑继续指定的原视频。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
