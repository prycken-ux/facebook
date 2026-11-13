"""Verified install of the reusable one-video-per-target folder distributor."""
import ast
import hashlib
import importlib.util
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

COMMIT='702c6268057d5ef69c40ce8b870c97d6fc3520ac'
MODULE_SHA='029836f26d39464ca63e10d104de1254ad4c08655711b84a5e9f7116f5499398'
MODULE='distribute_video_materials.py'
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);"
        "import fb_upload as u,add_fb_accounts as a,distribute_video_materials as d;"
        "assert d.SCHEMA=='one-video-per-target-distribution-v1';assert callable(d.choose_source);"
        "assert d.SCOPED_TARGETS_VERSION=='1.1-two-wave-scopes';assert d.TARGET_SCOPES=={'all','existing24','reserved50'};"
        "assert all(callable(getattr(u,n,None)) for n in ('read_json','save_json','validate_entry','job_key'));"
        "assert callable(a.write_shortcuts);print('INSTALL VERIFIED: one video per target, retained originals and resumable copy journal.',flush=True)")


def download(commit,name,expected):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(base+commit+'/downloads/'+name,context=context,timeout=30) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Checksum mismatch')
            ast.parse(data.decode('utf-8-sig'))
            return data
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    raise RuntimeError('分配工具下载校验失败，原文件未修改。')


def atomic(path,data):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:
        temporary=Path(handle.name);handle.write(data)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def clear_cache(root):
    Path(importlib.util.cache_from_source(str(root/MODULE))).unlink(missing_ok=True)


def install(root,data):
    ast.parse(data.decode('utf-8-sig'))
    sys.path.insert(0,str(root))
    import add_fb_accounts as legacy
    with legacy.locked():
        backup=root/'backups'/('material-distribution-install-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True)
        path=root/MODULE
        original=path.read_bytes() if path.is_file() else None
        if original is not None:(backup/MODULE).write_bytes(original)
        shortcut=root/'自动分配视频.lnk'
        if shortcut.exists():shutil.copy2(shortcut,backup/shortcut.name)
        try:
            atomic(path,data);clear_cache(root)
            subprocess.run([sys.executable,'-c',VERIFY,str(root)],check=True)
        except BaseException:
            if original is None:path.unlink(missing_ok=True)
            else:atomic(path,original)
            clear_cache(root)
            raise
        legacy.write_shortcuts([dict(path=str(shortcut),chrome=sys.executable,working=str(root),
            description='按已保存账号范围，每个发布目标分配1条视频；保留原素材',
            arguments=subprocess.list2cmdline([str(path),'--root',str(root),'--pause']))])
    print('自动分配视频入口已创建：',shortcut,flush=True)
    print('本次首次运行请选择素材总文件夹，以后双击此入口即可使用保存的目录。',flush=True)
    print('需要更换总素材目录时，重跑本安装指令重新选择。',flush=True)


def start(root,scope=None):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
    if scope not in {None,'all','existing24','reserved50'}:raise ValueError('素材分配范围无效。')
    if not all((root/n).is_file() for n in ('upload_config.json','account_registry.json','add_fb_accounts.py')):
        raise ValueError('缺少原上传配置或账号模块，未安装。')
    data=download(COMMIT,MODULE,MODULE_SHA)
    helper=download('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(helper,'verified-lock-library','exec'),namespace);namespace['recover_locks'](root)
    install(root,data)
    command=[sys.executable,str(root/MODULE),'--root',str(root),'--choose']
    if scope:command.extend(['--scope',scope])
    return subprocess.run(command).returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        extra=sys.argv[2:]
        if extra and (len(extra)!=2 or extra[0]!='--scope'):raise ValueError('请使用--scope existing24、reserved50或all。')
        raise SystemExit(start(Path(sys.argv[1]),extra[1] if extra else None))
    except KeyboardInterrupt:print('已取消，保留原素材及已有分配进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
