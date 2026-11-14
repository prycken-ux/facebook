"""Enable persistent windowless Chrome and continue the existing exact batch."""
import ast,hashlib,io,json,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

PACKAGE_COMMIT='6312bb2c02de7fa5faeda6563b0bf858a7e013f3'
PACKAGE_SHA='7a98f7bf58e161c51255080771f6a3d0051ccd41e0ef0e5b32b2f2fb584fd768'
NAMES=('browser_background_mode.py','normal_chrome_batch.py','chrome_profile_guard.py','diagnose_personal_identity.py')
SETTINGS='browser_run_settings.json'
RESUME_COMMIT='1f4fd2e87b0a7836f29fb7b154c4bc017161b785'
RESUME_SHA='52327255439d42eb3bde36d0fb78526d16dfca3ff15c3af18bcef3d5c9071a33'
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);import browser_background_mode as b,normal_chrome_batch as n;"
        "import chrome_profile_guard,diagnose_personal_identity;"
        "assert b.VERSION=='1.0-windowless-normal-chrome' and b.mode(sys.argv[1])=='background';"
        "assert n.NORMAL_CHROME_VERSION=='1.0-batch-scoped-local-cdp';"
        "assert n.background is b and '--headless=new' in b.arguments('background');"
        "print('INSTALL VERIFIED: windowless Chrome; existing profile, proxy settings and batch receipts retained. No video uploaded yet.',flush=True)")


def download(commit,name,sha,limit=131073):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+commit+'/downloads/'+name,context=context,timeout=30) as response:data=response.read(limit)
    if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Checksum mismatch; stopped')
    return data


def unpack(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist())!=len(NAMES) or set(archive.namelist())!=set(NAMES):raise ValueError('后台模式更新包范围不一致')
        updates={name:archive.read(name) for name in NAMES}
    for content in updates.values():ast.parse(content.decode('utf-8-sig'))
    return updates


def atomic(path,data):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:temporary=Path(handle.name);handle.write(data)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def clear_caches(root):
    import importlib.util
    for name in NAMES:Path(importlib.util.cache_from_source(str(root/name))).unlink(missing_ok=True)


def install(root,updates):
    sys.path.insert(0,str(root))
    from add_fb_accounts import locked
    with locked():
        backup=root/'backups'/('browser-background-mode-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
        for name in (*NAMES,SETTINGS):
            if (root/name).is_symlink():raise ValueError('运行文件是链接，未覆盖：'+name)
        originals={name:(root/name).read_bytes() if (root/name).is_file() else None for name in (*NAMES,SETTINGS)}
        for name,content in originals.items():
            if content is not None:(backup/name).write_bytes(content)
        changed=[]
        try:
            for name in NAMES:atomic(root/name,updates[name]);changed.append(name)
            atomic(root/SETTINGS,json.dumps(dict(schema='facebook-browser-run-mode-v1',mode='background'),ensure_ascii=False).encode('utf-8'));changed.append(SETTINGS)
            clear_caches(root)
            subprocess.run([sys.executable,'-c',VERIFY,str(root)],check=True)
        except BaseException:
            for name in reversed(changed):
                if originals[name] is None:(root/name).unlink(missing_ok=True)
                else:atomic(root/name,originals[name])
            clear_caches(root);raise
        print('已保存后台发布模式；原程序和原设置备份：',backup,flush=True)


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-14':
        raise ValueError('本次续跑入口仅用于11月14日继续11月13日原素材')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原发布配置')
    updates=unpack(download(PACKAGE_COMMIT,'windowless-chrome-mode-v1.zip',PACKAGE_SHA,1024*1024+1))
    resume=download(RESUME_COMMIT,'start_resume_nov13_on_nov14.py',RESUME_SHA);ast.parse(resume.decode('utf-8-sig'))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    namespace={'__name__':'verified_lock_library'};exec(compile(helper,'verified-lock-library','exec'),namespace);namespace['recover_locks'](root)
    install(root,updates)
    print('即将无窗口续跑原视频和评论。可最小化本窗口，请勿关闭；需要人工登录或验证的账号保留待处理，不自动弹出前台窗口。不要同时打开正在发布账号的登录快捷方式。',flush=True)
    code="import sys;sys.argv=['verified-nov14-resume',sys.argv[1]];exec(compile("+repr(resume.decode('utf-8-sig'))+",'verified-nov14-resume','exec'),{'__name__':'__main__'})"
    result=subprocess.run([sys.executable,'-u','-c',code,str(root)],stdin=subprocess.DEVNULL)
    if result.returncode not in {0,3,130}:raise RuntimeError('后台续跑已停止，保留全部进度，请查看上方原因')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停，保留全部发布进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
