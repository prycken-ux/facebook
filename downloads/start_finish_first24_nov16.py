"""Cache a verified new publisher without changing a currently running batch."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='cd3b2920b75fef077c6a2a49583d481d27a66a9d'
PACKAGE_SHA='c86212d556e3de33173252da5a0ea5645c7ebeca4114d4be274392a223c70a8e'
NAMES=('finish_first24_nov14_on_nov16.py','retry_first24_original_prepost_on_nov16.py','publish_staged_first24_nov14.py','stage_next_materials_20261114_v1.py','verified_publication_lock_recovery.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import finish_first24_nov14_on_nov16 as r;"
        "assert r.DAY=='2026-11-16' and r.MATERIAL_DAY=='2026-11-14' and r.staged.PAUSED=={'fb17'};"
        "assert len(r.staged.EXPECTED)==44 and len(r.staged.ALLOWED)==23 and len(r.repair.SPEC)==10;"
        "assert all(a=='fb09' and t.startswith('page') for a,t in r.repair.SPEC);"
        "assert r.VERSION=='1.0-nov16-frozen-stage-and-prepost-only';r.first.workflow.require_versions();"
        "print('INSTALL VERIFIED: Nov16 bounded original pre-Post repair, exact Nov14 stage, archived expired queues, original comments. fb17 paused. No video uploaded yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/nov16-first24-repair-and-nov14-stage-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
    if hashlib.sha256(data).hexdigest()!=PACKAGE_SHA:raise ValueError('Checksum mismatch; stopped')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist())!=len(NAMES) or set(archive.namelist())!=set(NAMES):raise ValueError('本批发布工具范围异常。')
        updates={name:archive.read(name) for name in NAMES}
    for code in updates.values():ast.parse(code.decode('utf-8-sig'))
    return updates


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的新PowerShell窗口运行。')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-16':raise ValueError('本入口仅用于11月16日补发原批次及11月14日已暂存素材。')
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
    print('先补发明确发布前失败的原视频，再处理11月14日已暂存44条素材（fb17暂跳过，共43条）。沿用原文案和评论。检测到旧任务运行时会停止并提示，不强制结束、不一直空等。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'finish_first24_nov14_on_nov16.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('本批已停止，所有发布进度保留；请查看上方原因。')
    if result.returncode==3:print('本批仍有失败、待核实或评论未完成；按逐条结果核对，不重复上传结果不明的视频。',flush=True)
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
