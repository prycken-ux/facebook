"""Verified Windows launcher: Nov14 continuation of the exact original Nov13 material."""
import ast,hashlib,importlib.util,io,shutil,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='fca9054890d52f79b606a0e6b5fc31fea8ff32e1'
PACKAGE_SHA='c83a932cc440d0e0c7a22c917d343ada11611d412ccf7ee4a08bf5b6c2badc23'
NAMES=('personal_owner_routes.py','recovery_numeric_identity.py','page_reel_ai_compat.py','distribute_video_materials.py','archive_nov12_materials_20261113.py','capture_current_publication.py','publish_distributed_nov13_first24.py','personal_owner_registration.py','publish_all_distributed_nov13.py','resume_nov13_two_waves_on_nov14.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);"
        "import resume_nov13_two_waves_on_nov14 as r;f=r.first;"
        "assert f.upload.VERSION=='2.47';f.workflow.require_versions();"
        "assert r.RUN_DAY=='2026-11-14' and r.SOURCE_DAY=='2026-11-13';"
        "assert f.DAY==f.MATERIAL_DAY=='2026-11-13';"
        "assert f.personals.VERSION=='1.0-me-bound-personal-aliases';"
        "assert f.capture.VERSION=='1.0-frozen-job-passive-publication-evidence';"
        "assert r.original.NEW=={'fb%02d'%n for n in range(25,75)};"
        "print('INSTALL VERIFIED: Nov14 continuation of original Nov13 material only; independent continuation manifests, original guards preserved. No video uploaded yet.',flush=True)")


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
        print('11月13日原批次的跨日续跑程序已安装并核验，原程序已备份：',backup,flush=True)


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-14':
        raise ValueError('此指令仅授权11月14日续跑11月13日原视频，不包含今天新素材')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置，未启动')
    updates=unpack(download(COMMIT,'nov14-resume-nov13-two-waves-v1.zip',PACKAGE_SHA,2*1024*1024+1))
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    ast.parse(helper.decode('utf-8-sig'))
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace)
    namespace['recover_locks'](root)
    install(root,updates)
    print('按本地最新进度续跑11月13日原视频：成功保留，已提交未知先只读核实，剩余老账号继续，之后自动接新50账号及评论。原视频和已确认实拍标签不变，不重新提问名称或AI，不分配或归档11月14日的新素材。请保持窗口打开。',flush=True)
    result=subprocess.run([sys.executable,str(root/'resume_nov13_two_waves_on_nov14.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('原批次续跑已停止；保留全部进度，重跑同一命令继续这批原素材')
    if result.returncode==3:print('仍有失败、待核实或未完成评论；详见逐条结果。视频和评论分开统计，不会重复上传待核实视频。',flush=True)
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停，保留全部记录；重跑继续指定的原视频。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
