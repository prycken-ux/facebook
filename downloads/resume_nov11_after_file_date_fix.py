"""Verified Windows entry: Nov-11 real footage, upload pass, one retry, comments."""
import ast,hashlib,importlib.util,io,shutil,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='b714aab21b018155bd288d862b6b276e3791d9b9'
PACKAGE_SHA='bcd61e76ea89ddc66ae1d82629884e97ff260069a6f507d426ac35b878570484'
NAMES=('local_file_input.py','normal_chrome_batch.py','scheduled_priority_workflow.py','publish_existing_20261111.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);"
        "import fb_upload as u,local_file_input as f,normal_chrome_batch as n,scheduled_priority_workflow as w,publish_existing_20261111 as t;"
        "assert u.VERSION=='2.47';w.require_versions();"
        "assert f.BATCH_DATE_VERSION==n.BATCH_DATE_VERSION==w.BATCH_DATE_VERSION=='1.0-frozen-batch-date-binding';"
        "assert t.DATE=='2026-11-11';assert t.SCOPE=='nov11-existing-configured-targets-first-v1';"
        "print('INSTALL VERIFIED: frozen batch date now reaches local file validation. Original jobs and pointer preserved; no publication yet.',flush=True)")


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
        print('文件自检日期修复已安装并核验，原程序已备份：',backup,flush=True)


def start(root,real_footage=False):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-11':
        raise ValueError('此指令仅发布北京时间11月11日今天的新批次')
    if not real_footage:raise ValueError('今天全批视频尚未确认全部实拍，未启动')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置，未启动')
    updates=unpack(download(COMMIT,'nov11-local-file-batch-date-fix-v1.zip',PACKAGE_SHA,2*1024*1024+1))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    ast.parse(helper.decode('utf-8-sig'))
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace);namespace['recover_locks'](root)
    install(root,updates)
    print('日期传递问题已修复；继续11月11日原有账号的同一批次，暂缓新增或未登记目标；先发布、再安全补发视频、再评论和补评。请保持窗口打开。',flush=True)
    result=subprocess.run([sys.executable,str(root/'publish_existing_20261111.py'),str(root),'--real-footage'])
    if result.returncode not in {0,3}:raise RuntimeError('今天批次已停止；保留全部发布和发送记录，重跑同一命令继续原批次')
    if result.returncode==3:print('仍有失败、待核实或未完成评论；详见逐条结果。视频成功与评论成功分别统计。',flush=True)
    return result.returncode


def main():
    confirmed='--real-footage' in sys.argv[2:]
    if not confirmed:
        print('启动前确认11月11日这批视频：全部实拍、不含AI生成或显著修改画面时，请输入REAL；其他输入停止。',flush=True)
        confirmed=input('今天这批是否全部实拍（REAL）：').strip().upper()=='REAL'
    return start(Path(sys.argv[1]),confirmed)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:print('已停止，保留全部记录；重跑继续今天原批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
