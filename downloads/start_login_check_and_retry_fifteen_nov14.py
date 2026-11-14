"""Verified Windows launcher: guided owner login checks followed by the same fifteen-job grant."""
import ast,hashlib,importlib.util,io,shutil,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='546b867022cd37c74108e34173ce6b96a4d549ac'
PACKAGE_SHA='229e3775658a9485a6bcd6123bf5af57fc63c4995ab7ab6caa06f3b9b40dc038'
NAMES=('diagnose_login_and_resume_fifteen_nov14.py',)
VERIFY=("import sys,hashlib;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import diagnose_login_and_resume_fifteen_nov14 as r;f=r.first;"
        "assert f.upload.VERSION=='2.47';f.workflow.require_versions();"
        "assert r.DAY=='2026-11-14' and r.ACCOUNTS==('fb09','fb17','fb37','fb38','fb55');"
        "assert r.base.GRANT=='nov13-fifteen-prepost-explicit-retry-on-nov14-v1' and len(r.base.SPEC)==15;"
        "assert hashlib.sha256((Path(sys.argv[1])/'retry_nov13_prepost_fifteen_on_nov14.py').read_bytes()).hexdigest()=='6c678d42d4dd08bddf034b90aeac76d2123887bb167b10782fa057c92bcbd4b7';"
        "assert f.normal.background.VERSION=='1.0-windowless-normal-chrome';"
        "print('INSTALL VERIFIED: owner-guided login checks, same original fifteen-job grant, no extra video retry permission. No video uploaded yet.',flush=True)")



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
        print('本人登录检查与原15条补发衔接程序已安装并核验，原程序已备份：',backup,flush=True)


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-14':
        raise ValueError('此指令仅授权11月14日续跑11月13日原视频，不包含今天新素材')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置，未启动')
    updates=unpack(download(COMMIT,'nov14-manual-login-fifteen-v1.zip',PACKAGE_SHA,2*1024*1024+1))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    ast.parse(helper.decode('utf-8-sig'))
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace)
    namespace['recover_locks'](root)
    install(root,updates)
    print('先对比后台与前台登录；需要本人处理时只打开对应编号的原Chrome。按提示完成后回PowerShell按回车；S跳过，Q暂停。若仅后台失败，可输入F选择本轮仅该账号用最小化普通Chrome补发。不会重新填写名称或AI，也不改绑账号。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(root/'diagnose_login_and_resume_fifteen_nov14.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('指定原视频补发已停止；保留全部进度，重跑同一命令继续未处理目标')
    if result.returncode==3:print('仍有失败、待核实或未完成评论；详见逐条结果。视频和评论分开统计，不会重复上传待核实视频。',flush=True)
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停，保留全部记录；重跑继续指定的原视频。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
