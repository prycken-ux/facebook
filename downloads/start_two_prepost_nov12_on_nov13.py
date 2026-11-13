"""Verified Windows launcher: one extra retry for Donna/Cyrus pre-Post failures only."""
import ast,hashlib,importlib.util,io,shutil,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='7fe65d9765c41a83ee9bea8bf0d80bb8aef6521e'
PACKAGE_SHA='7f3bacab3b915d2f9f877db08c81d8d05e385a564cc2a6088c519bb4b04075ac'
NAMES=('personal_owner_routes.py','recovery_numeric_identity.py','page_reel_ai_compat.py','retry_named_nov12_on_nov13.py','retry_two_prepost_nov12_on_nov13.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);"
        "import retry_two_prepost_nov12_on_nov13 as r;"
        "assert r.base.upload.VERSION=='2.47';r.base.workflow.require_versions();"
        "assert r.base.personal.VERSION=='1.0-me-bound-personal-aliases';"
        "assert r.base.numeric.VERSION=='1.0-numeric-actor-with-guided-picker';"
        "assert r.base.editor.VERSION=='1.0-styled-ai-controls';"
        "assert r.DAY=='2026-11-13' and r.PARENT_PREFIX=='024ae954';"
        "assert set(r.SPEC)=={('fb02','page01'),('fb23','personal')};"
        "assert r.SPEC[('fb02','page01')][:2]==('1111(1)-2.mp4','Donna Merrill');"
        "assert r.SPEC[('fb23','personal')]==('1111-3.mp4','Cyrus Marlene','c39afc3832d8');"
        "print('INSTALL VERIFIED: two exact before-Post failures only, one extra attempt each. No comments. No video uploaded yet.',flush=True)")


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
        print('两个发布前失败目标的补发程序已安装并核验，原程序已备份：',backup,flush=True)


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-13':
        raise ValueError('此指令仅授权11月13日补发Donna Merrill和Cyrus Marlene的两条发布前失败视频')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置，未启动')
    updates=unpack(download(COMMIT,'nov13-two-prepost-video-only-extra-once-v1.zip',PACKAGE_SHA,2*1024*1024+1))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    ast.parse(helper.decode('utf-8-sig'))
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace)
    namespace['recover_locks'](root)
    install(root,updates)
    print('现在仅再次尝试Donna Merrill（fb02/page01，1111(1)-2.mp4）和Cyrus Marlene（fb23/personal，1111-3.mp4），各一次。不发送评论；其他成功、待核实及未匹配目标保持原样。请保持窗口打开。',flush=True)
    result=subprocess.run([sys.executable,str(root/'retry_two_prepost_nov12_on_nov13.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('两条失败视频补发已停止；保留全部记录，重跑同一命令继续本次两条原视频')
    if result.returncode==3:print('这两条仍有失败或待核实，详见逐条结果。本次没有发送评论。',flush=True)
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停，保留全部记录；重跑继续指定的原视频。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
