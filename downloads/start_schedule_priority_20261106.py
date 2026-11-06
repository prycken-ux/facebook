"""Verified Windows entry: Nov-6 registration: exact new caption, skip four, Beijing 17:00 full workflow."""
import ast,hashlib,importlib.util,io,shutil,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='5cf2c34289b915a39af85da8c23be406ae98b146'
PACKAGE_SHA='74bf3caf0b70cb9a38e30dab92acdfefc042665d7f0a6fd5cd8f60e97371a8aa'
NAMES=('publication_preferences.py','scheduled_material_batch.py','publish_priority_batch.py','automatic_batch_retry.py','actual_reels_comment_lookup.py','confirm_all_nov05_20261106.py','scheduled_priority_workflow.py')
VERIFY=("import sys,inspect;sys.path.insert(0,sys.argv[1]);"
        "import fb_upload as u,safe_video_comments as c,scheduled_material_batch as b,automatic_batch_retry as r;"
        "import publication_preferences as q,scheduled_priority_workflow as t,normal_chrome_batch as n,local_file_input as f,actual_reels_comment_lookup as a;"
        "assert u.VERSION=='2.47';assert u.IMMEDIATE_COMMENT_VERSION=='1.0-receipt-first-reload';"
        "assert c.COMMENT_WORKFLOW_VERSION=='1.4-exact-post-lookup';"
        "assert b.RESUME_WORKFLOW_VERSION=='1.0-preserve-attempted-jobs';assert b.PUBLICATION_PREFERENCES_VERSION==q.VERSION;"
        "assert q.VERSION=='1.0-exact-caption-excluded-accounts';assert q.EXCLUDED==['fb16','fb17','fb18','fb21'];"
        "assert r.AUTO_RETRY_VERSION=='1.1-immediate-aware';assert r.VISIBILITY_RETRY_VERSION=='1.0-stage-bound-visibility';"
        "assert r.FILE_CHOOSER_RETRY_VERSION=='1.0-stage-bound-missing-chooser';"
        "assert n.LOCAL_FILE_INPUT_COMPATIBILITY==f.VERSION;assert f.VERSION=='1.0-verified-local-file-paths';"
        "assert a.REELS_ENTRY_VERSION=='1.0-owner-route-fallback';assert t.VERSION=='1.0-frozen-priority-task';"
        "assert t.SETUP_DATE=='2026-11-06';"
        "print('INSTALL VERIFIED: exact-caption and skip-rule workflow; one 17:00 task. No settings or uploads started.',flush=True)")


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
        print('优先发布流程已安装并核验，原程序已备份：',backup,flush=True)


def start(root,real_footage=False):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-06':
        raise ValueError('此指令仅发布北京时间11月6日今天的新批次')
    if not real_footage:raise ValueError('今天全批视频尚未确认全部实拍，未启动')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置，未启动')
    updates=unpack(download(COMMIT,'nov06-preferences-scheduled-priority-v1.zip',PACKAGE_SHA,2*1024*1024+1))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    ast.parse(helper.decode('utf-8-sig'))
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace);namespace['recover_locks'](root)
    install(root,updates)
    print('开始注册今天北京时间17:00的发布、一次安全补发及评论计划，并保存统一正文和跳过账号规则；全部实拍，不含AI。注册时不上传。',flush=True)
    result=subprocess.run([sys.executable,str(root/'scheduled_priority_workflow.py'),'setup','--real-footage'])
    if result.returncode not in {0,3}:raise RuntimeError('今天17点计划未完成注册；请查看上方STOP原因，原发布记录保留')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        confirmed='--real-footage' in sys.argv[2:]
        raise SystemExit(start(Path(sys.argv[1]),confirmed))
    except KeyboardInterrupt:print('已停止，保留全部记录；重跑继续今天原批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
