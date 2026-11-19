"""Cache a verified material distributor without modifying the publisher."""
import ast,hashlib,io,ssl,subprocess,sys,tempfile,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

COMMIT='37eb724ffb21468ee2c3e9376a6316d9a5e6c0da'
PACKAGE_SHA='cb574bd8d4beafe993c23ee2fa842919ab82d64e8fce187296261b6f591e7b2b'
NAMES=('retry_nov18_twelve_prepost_on_nov19.py', 'publish_eligible62_materials_20261118.py', 'publication_response_finish_guard.py', 'publication_background_policy.py', 'distribute_eligible62_materials_20261118.py', 'eligible62_publication_workflow.py', 'retry_eligible62_prepost_20261118.py', 'stage_eligible62_materials_v5.py', 'material_distribution_worker_check.py', 'verified_publication_lock_recovery.py', 'finish_first24_nov14_on_nov16.py', 'retry_first24_original_prepost_on_nov16.py', 'publish_staged_first24_nov14.py', 'stage_next_materials_20261114_v1.py', 'publish_all_distributed_nov13.py', 'publish_unplanned_fortysix_nov14.py')
VERIFY=("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);import retry_nov18_twelve_prepost_on_nov19 as r;"
        "assert r.VERSION=='1.0-nov18-twelve-extra-once-skip40-43' and len(r.SPEC)==12;"
        "assert r.SKIP_RETRY=={'fb40','fb43'} and not ({a for a,t in r.SPEC}&(r.app.PAUSED|r.SKIP_RETRY));"
        "assert len(r.app.PAUSED)==32 and len(r.app.EXPECTED)==62;"
        "assert r.SOURCE_PREFIX=='244766c38beaa3ad';r.first.workflow.require_versions();"
        "assert r.app.background_policy.VERSION=='1.0-headless-auto-manual-verification-only';"
        "assert r.app.response_guard.VERSION=='1.0-completed-response-capture-bounded-diagnostics';"
        "print('INSTALL VERIFIED: twelve exact Nov18 pre-Post failures only,one extra attempt each;skip32 paused and fb40/fb43;headless,original real AI OFF and captions/comments;old pending submissions retained. No video uploaded yet.',flush=True)")



def download():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    with urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/'+COMMIT+'/downloads/nov18-twelve-prepost-extra-nov19-v1.zip',context=context,timeout=30) as response:data=response.read(2*1024*1024+1)
    if hashlib.sha256(data).hexdigest()!=PACKAGE_SHA:raise ValueError('Checksum mismatch; stopped')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist())!=len(NAMES) or set(archive.namelist())!=set(NAMES):raise ValueError('本批发布工具范围异常。')
        updates={name:archive.read(name) for name in NAMES}
    for code in updates.values():ast.parse(code.decode('utf-8-sig'))
    return updates


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的新PowerShell窗口运行。')
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
    print('本次仅对11月18日明确发布前失败的12条原视频各追加一次尝试。跳过32个停用账号及fb40、fb43；47条旧待核实视频不重新上传。后台运行，登录验证先跳过，新成功视频按原评论处理。请保持窗口打开，可最小化。',flush=True)
    result=subprocess.run([sys.executable,'-u',str(folder/'retry_nov18_twelve_prepost_on_nov19.py'),str(root)])
    if result.returncode not in {0,3,130}:raise RuntimeError('本次补发仍有未完成项；原素材、视频/评论记录和补发进度均保留，请查看上方原因。')
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停本窗口，保留全部进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
