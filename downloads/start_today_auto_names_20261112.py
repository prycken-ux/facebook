"""Verified Windows entry: Nov-11 real footage, upload pass, one retry, comments."""
import ast,hashlib,importlib.util,io,shutil,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='47af44ed3e9f9e0973f1347f05dad15d4aa58783'
PACKAGE_SHA='133d84cdbc880fef4bba15331a54a2bc1b356ffe858bfdf7bca2c60d9aa91296'
NAMES=('personal_owner_routes.py','personal_owner_registration.py','publish_today_20261112.py','page_reel_ai_compat.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);"
        "import fb_upload as u,publish_today_20261112 as r,personal_owner_routes as p;"
        "assert u.VERSION=='2.47';r.old.workflow.require_versions();"
        "assert p.VERSION=='1.0-me-bound-personal-aliases';assert r.DAY=='2026-11-12';"
        "assert r.ALLOWED=={'fb%02d'%n for n in range(1,25)};assert len(r.SKIP)==50;"
        "assert r.personal.editor.VERSION=='1.0-styled-ai-controls';assert r.personal.NAME_REUSE_VERSION=='1.0-verified-owner-name-cache';"
        "print('INSTALL VERIFIED: Nov12 new videos only, original accounts and Pages, skip fb25-fb74, no old personal retries. No video uploaded yet.',flush=True)")


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
        print('今天新视频发布流程已安装并核验，原程序已备份：',backup,flush=True)


NAME_MODULE='personal_owner_registration.py'
BASE_NAME_SHA='178bb165deee73d6a0849aab4da875a9f275b762ef956935e8f6562a32693ebd'
VERIFY_NAMES=("import sys;sys.path.insert(0,sys.argv[1]);import personal_owner_registration as p;"
              "assert p.NAME_REUSE_VERSION=='1.0-verified-owner-name-cache';assert callable(p.cached_name);"
              "print('NAME CACHE VERIFIED: exact verified owner, no repeated name entry.',flush=True)")


def install_names_only(root,data):
    # Only replace this already-imported helper's source. Do not acquire,
    # clear, or mutate the running uploader's locks/config/state/browser.
    ast.parse(data.decode('utf-8-sig'))
    path=root/NAME_MODULE
    original=path.read_bytes() if path.is_file() else None
    if original is None:raise ValueError('原名称识别模块缺失，未在发布期间新建另一套接入程序。')
    if original!=data:
        if hashlib.sha256(original).hexdigest()!=BASE_NAME_SHA:raise ValueError('名称模块已有不同更新，未在发布期间覆盖。')
        backup=root/'backups'/('owner-name-cache-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True);(backup/NAME_MODULE).write_bytes(original)
        try:
            write_atomic(root,path,data)
            Path(importlib.util.cache_from_source(str(path))).unlink(missing_ok=True)
            subprocess.run([sys.executable,'-c',VERIFY_NAMES,str(root)],check=True)
        except BaseException:
            write_atomic(root,path,original)
            Path(importlib.util.cache_from_source(str(path))).unlink(missing_ok=True)
            raise
    print('名称自动复用已安装；发布记录、账号配置和当前浏览器均未改动。',flush=True)


def start(root,real_footage=False):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-12':
        raise ValueError('此指令仅在北京时间11月12日发布今天新视频')
    if not real_footage:raise ValueError('今天新素材尚未确认全部实拍，未启动')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置，未启动')
    updates=unpack(download(COMMIT,'nov12-original-accounts-auto-names-v2.zip',PACKAGE_SHA,2*1024*1024+1))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    ast.parse(helper.decode('utf-8-sig'))
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace)
    try:namespace['recover_locks'](root)
    except Exception as error:
        if not any((root/'logs'/name).exists() for name in ('batch.lock','upload.lock')):raise
        print('保留现有发布占用记录：',str(error).split('\n',1)[0],flush=True)
        install_names_only(root,updates['personal_owner_registration.py'])
        print('当前任务保持原样，本次没有启动第二个发布进程。新名称识别在下次启动时生效。',flush=True)
        return 0
    install(root,updates)
    print('开始处理11月12日今天的新视频；仅fb01–fb24及其已登记公共主页，跳过fb25–fb74。昨天fb17/fb18/fb21原视频不补发。先发布，再安全重试，最后评论及补评。本人名称按已核验数字ID自动复用，不再要求手动填写。请保持窗口打开。',flush=True)
    result=subprocess.run([sys.executable,str(root/'publish_today_20261112.py'),str(root),'--real-footage'])
    if result.returncode not in {0,3,130}:raise RuntimeError('今天发布流程已停止；保留全部发布和发送记录，重跑同一命令继续今天原清单')
    if result.returncode==3:print('仍有失败、待核实或未完成评论；详见逐条结果。视频成功与评论成功分别统计。',flush=True)
    return result.returncode


def main():
    confirmed='--real-footage' in sys.argv[2:]
    if not confirmed:
        print('启动前确认11月12日今天这批新素材：全部实拍、不含AI生成或显著修改画面时，请输入REAL；其他输入停止。',flush=True)
        confirmed=input('今天素材是否全部实拍（REAL）：').strip().upper()=='REAL'
    return start(Path(sys.argv[1]),confirmed)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:print('已停止，保留全部记录；重跑继续今天原批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
