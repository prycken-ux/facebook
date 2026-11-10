"""Verified Windows start for one user-logged-in personal publication target."""
import ast,hashlib,importlib.util,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime
from pathlib import Path

COMMIT='ddc5c285ddebabfdb689f0222df1abbaea3ae6f7'
PACKAGE_SHA='ef4ff7ca0669fb37fff150cf8090f340b6aa72d79391009a7190726deb047c99'
NAMES=('add_personal_accounts.py','connect_one_personal_20261110.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);"
        "import fb_upload as u,add_personal_accounts as a,scheduled_material_batch as b,connect_one_personal_20261110 as c;"
        "assert u.VERSION=='2.47';assert callable(u.ensure_personal_identity);assert a.RESERVATION_VERSION=='1.1-minimum-account-number';"
        "assert b.RESUME_WORKFLOW_VERSION=='1.0-preserve-attempted-jobs';"
        "assert b.NEW_PERSONAL_ACCOUNTS_VERSION=='1.0-verified-onboarding';"
        "assert c.BATCH_ID=='personal-20261110-one';assert c.MINIMUM_NUMBER==27;assert c.ONBOARDING_VERSION=='1.1-new-one-normal-chrome';"
        "assert c.normal.NORMAL_CHROME_VERSION=='1.0-batch-scoped-local-cdp';"
        "print('INSTALL VERIFIED: one personal login, exact owner verification, publication integration. No video uploaded.',flush=True)")


def download(commit,name,expected,limit=131073):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(base+commit+'/downloads/'+name,context=context,timeout=25) as response:data=response.read(limit)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Checksum mismatch')
            return data
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    raise RuntimeError('校验下载失败，未新增账号')


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
    if upload.VERSION!='2.47':raise ValueError('需使用当前2.47核心，未覆盖发布核心')
    with locked():
        backup=root/'backups'/('one-personal-install-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
        originals={name:(root/name).read_bytes() if (root/name).is_file() else None for name in NAMES}
        for name,content in originals.items():
            if content is not None:(backup/name).write_bytes(content)
        changed=[]
        try:
            for name in NAMES:write_atomic(root,root/name,updates[name]);changed.append(name)
            clear_caches(root);subprocess.run([sys.executable,'-c',VERIFY,str(root)],check=True)
        except BaseException:
            for name in reversed(changed):
                if originals[name] is None:(root/name).unlink(missing_ok=True)
                else:write_atomic(root,root/name,originals[name])
            clear_caches(root);raise
        print('新增个人号接入程序已安装并核验；原程序备份：',backup,flush=True)


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if not all((root/name).is_file() for name in ('upload_config.json','account_registry.json')):raise ValueError('缺少原账号配置，未新增账号')
    updates=unpack(download(COMMIT,'one-new-personal-account-20261110-v1.zip',PACKAGE_SHA,2*1024*1024+1))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    ast.parse(helper.decode('utf-8-sig'))
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace);namespace['recover_locks'](root)
    install(root,updates)
    print('开始新增1个全新个人号，从fb27或之后的空闲编号开始；不恢复已删除的fb24-fb26。按顺序本人登录，再在PowerShell填写本人主页名称和网址；S跳过、Q暂停。',flush=True)
    result=subprocess.run([sys.executable,str(root/'connect_one_personal_20261110.py')])
    if result.returncode not in {0,3,130}:raise RuntimeError('新增账号接入停止，保留输出；重跑继续本次1个编号')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停；重跑继续本次1个编号，保留已有登录。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
