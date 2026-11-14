"""Start an independent staging-only tool without touching publication modules/locks."""
import ast,hashlib,os,ssl,subprocess,sys,tempfile,urllib.request
from pathlib import Path

COMMIT='d8d78e7d0ff63e840aa3f7cf2e84ad96f8246129'
MODULE_SHA='f48e96039109e83dd9f2c22d94beaefd57a54c451d62a27aa51839924fef83cb'
MODULE='stage_next_materials_20261114_v1.py'


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的另一个PowerShell窗口运行。')
    if not (root/'upload_config.json').is_file() or not (root/'account_registry.json').is_file():raise ValueError('缺少原账号登记文件。')
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/'+MODULE,context=context,timeout=30) as response:data=response.read(131073)
    if hashlib.sha256(data).hexdigest()!=MODULE_SHA:raise ValueError('Checksum mismatch; stopped')
    ast.parse(data.decode('utf-8-sig'))
    folder=root/'material-staging'/'tools'/MODULE_SHA[:16]
    for item in (root/'material-staging',root/'material-staging'/'tools',folder):
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):raise ValueError('独立工具缓存目录是链接，未安装。')
        item.mkdir(exist_ok=True)
    path=folder/MODULE
    if path.is_symlink():raise ValueError('工具缓存文件是链接，未覆盖。')
    if path.exists():
        if path.read_bytes()!=data:raise ValueError('同指纹工具缓存内容异常，未覆盖。')
    else:
        with tempfile.NamedTemporaryFile(dir=folder,delete=False) as handle:temporary=Path(handle.name);handle.write(data)
        try:temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
    print('独立暂存工具已核验。当前发布任务继续运行；本入口不修改发布程序、上传锁、正式inbox或发布记录。',flush=True)
    print('请选择今天的素材总文件夹：全部已登记及已预留账号和公共主页，每个目标1条，按文件名自然顺序，复制并保留原件。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(path),'prepare',str(root)])
    if result.returncode not in {0,130}:raise RuntimeError('暂存准备未完成，当前发布任务未改动；请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已取消本窗口暂存任务，原发布任务继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
