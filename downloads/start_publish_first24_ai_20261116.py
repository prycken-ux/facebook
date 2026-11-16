"""Cache a verified new publisher without changing a currently running batch."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='20300525ebecc0a136b7553628290ceac94c718f'
PACKAGE_SHA='cdc1f45fa3206f3f18bf72d334f7baf1a56869cd99bb6cd5104f9d8f38bb932c'
NAMES=('publish_first24_ai_materials_20261116.py','ai_first24_workflow_20261116.py','retry_ai_prepost_first24_20261116.py','finish_first24_nov14_on_nov16.py','retry_first24_original_prepost_on_nov16.py','publish_staged_first24_nov14.py','stage_next_materials_20261114_v1.py','verified_publication_lock_recovery.py','stage_next_materials_20261116_v2.py','material_distribution_worker_check.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import publish_first24_ai_materials_20261116 as r;"
        "assert r.DAY=='2026-11-16' and len(r.EXPECTED)==44 and len(r.ALLOWED)==24 and r.PAUSED==set();"
        "assert 'fb17' in r.ALLOWED and all(int(a[2:])<=24 for a in r.ALLOWED);"
        "assert r.VERSION=='1.0-nov16-imported-first24-ai-on' and r.ai.VERSION=='1.0-explicit-ai-on-scoped-publication';"
        "assert r.ai.GRANT==r.extra.GRANT and r.ai.AUTH=='user-confirmed-containing-ai-20261116-v1';"
        "r.first.workflow.require_versions();"
        "print('INSTALL VERIFIED: exact44 current new videos INCLUDING fb17; AI LABEL ON for initial uploads and retries; original captions and comments; saved progress. No video uploaded yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/nov16-first24-ai-on-publication-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
    if hashlib.sha256(data).hexdigest()!=PACKAGE_SHA:raise ValueError('Checksum mismatch; stopped')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist())!=len(NAMES) or set(archive.namelist())!=set(NAMES):raise ValueError('本批发布工具范围异常。')
        updates={name:archive.read(name) for name in NAMES}
    for code in updates.values():ast.parse(code.decode('utf-8-sig'))
    return updates


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的新PowerShell窗口运行。')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-16':raise ValueError('本入口仅用于11月16日已确认含AI的这批新素材，AI标签开启。')
    if not (root/'upload_config.json').is_file():raise ValueError('缺少原上传配置。')
    updates=download();folder=root/'material-staging/tools'/PACKAGE_SHA[:16]
    for item in (root/'material-staging',root/'material-staging/tools',folder):
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):raise ValueError('工具缓存目录是链接。')
        item.mkdir(exist_ok=True)
    for name,data in updates.items():
        path=folder/name
        if path.is_symlink():raise ValueError('工具缓存文件是链接。')
        if path.exists():
            if path.read_bytes()!=data:raise ValueError('同指纹工具内容异常，未覆盖。')
            continue
        with tempfile.NamedTemporaryFile(dir=folder,delete=False) as handle:temporary=Path(handle.name);handle.write(data)
        try:temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
    subprocess.run([sys.executable,'-c',VERIFY,str(folder),str(root)],check=True)
    print('今天新素材：fb01–fb24及对应公共主页，共44条（包含fb17）。本批按含AI处理，AI标签开启；沿用原正文和评论。默认后台发布，失败安全补发，已提交结果先核实。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'publish_first24_ai_materials_20261116.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('本批已停止，所有发布进度保留；请查看上方原因。')
    if result.returncode==3:print('本批仍有失败、待核实或评论未完成；按逐条结果核对，不重复上传结果不明的视频。',flush=True)
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
