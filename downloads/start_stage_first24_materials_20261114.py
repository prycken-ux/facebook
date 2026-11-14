"""Start an independent staging-only tool without touching publication modules/locks."""
import ast,hashlib,os,ssl,subprocess,sys,tempfile,urllib.request
from pathlib import Path

COMMIT='c10921bd04f22723d11d4cb2a899d6afa188ffd2'
MODULE_SHA='2a2ca80237992456670946efaf8175fdcdd7ec489985e28231cd2ba16653a212'
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
    print('请选择刚才含44条新视频的总文件夹：本批仅分配fb01–fb24及对应公共主页；fb25及以后不分配，每个目标1条，复制并保留原件。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(path),'prepare',str(root),'--scope','existing24'])
    if result.returncode not in {0,130}:raise RuntimeError('暂存准备未完成，当前发布任务未改动；请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已取消本窗口暂存任务，原发布任务继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
