"""Nov-5 retry and comments for only the two user-confirmed failed Nov-4 videos."""
import ast,hashlib,importlib.util,io,shutil,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='4a964a7a9e47d20c222f79ee16808e978858532f'
PACKAGE_SHA='7b7d040d5f10ab36d73c6df268471ca7b58aa4a49119de333f1e963df62cc589'
NAMES=('retry_nov04_two_and_comment_20261105.py',)
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);"
        "import fb_upload as u,safe_video_comments as c,normal_chrome_batch as n,local_file_input as f,actual_reels_comment_lookup as a;"
        "import retry_nov04_two_and_comment_20261105 as r,scheduled_material_batch as b;"
        "assert u.VERSION=='2.47';assert u.IMMEDIATE_COMMENT_VERSION=='1.0-receipt-first-reload';"
        "assert c.COMMENT_WORKFLOW_VERSION=='1.4-exact-post-lookup';assert f.VERSION=='1.0-verified-local-file-paths';"
        "assert n.LOCAL_FILE_INPUT_COMPATIBILITY==f.VERSION;assert r.base.PREFIX=='d6707ad5';assert r.GRANT=='nov04-two-user-confirmed-absent-20261105';"
        "assert a.LOOKUP_VERSION=='1.1-fragments-jsonld-noninteractive';"
        "assert b.RESUME_WORKFLOW_VERSION=='1.0-preserve-attempted-jobs';"
        "print('INSTALL VERIFIED: only fb11/personal and fb13/page01; retry then comments. No video uploaded.',flush=True)")


def download(commit,name,expected,limit=131073):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(base+commit+'/downloads/'+name,context=context,timeout=25) as response:data=response.read(limit)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Checksum mismatch')
            return data
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    raise RuntimeError('校验下载失败，未启动指定两条补发')


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
        raise ValueError('需使用现有2.47发布核心，未覆盖核心程序')
    with locked():
        backup=root/'backups'/('nov04-two-retry-install-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
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
        print('指定两条补发与评论程序已安装核验，程序备份：',backup,flush=True)


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-05':
        raise ValueError('此指令仅用于11月5日补发11月4日指定两个账号原视频')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置，未启动')
    updates=unpack(download(COMMIT,'nov04-two-retry-comments-v1.zip',PACKAGE_SHA,2*1024*1024+1))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    ast.parse(helper.decode('utf-8-sig'))
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace);namespace['recover_locks'](root)
    install(root,updates)
    print('开始处理指定两条原视频：fb11/personal Alice Luther、fb13/page01 Prycken BK；先补发，再给成功视频补评论。其余按你的确认保留成功。',flush=True)
    result=subprocess.run([sys.executable,str(root/'retry_nov04_two_and_comment_20261105.py')])
    if result.returncode not in {0,3,130}:raise RuntimeError('指定两条补发已停止；全部发布、补发和评论发送意图均保留')
    if result.returncode==3:print('仍有指定视频或评论未确认成功；详见上方结果，不会自动重复提交待核实内容。',flush=True)
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已停止；视频状态及已有评论发送意图保留。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
