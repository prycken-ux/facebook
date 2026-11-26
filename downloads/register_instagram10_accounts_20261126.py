"""Register the ten user-supplied IG identities in the existing E: workspace.

No browser is opened/closed, no credentials are read, and nothing is published.
"""
import contextlib,copy,csv,hashlib,io,json,os,re,sys,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
VERSION='1.0-user-supplied-ten-ig-account-mapping'
USERNAMES=('ted47868','jenniferriffin45','ha.rper9090','ivy800550','sophia5095091','daisybreeze8838','ethan400560','dylan159851','zachary29692','alixla2762')
MAPPING={f'ins{i:02d}':username for i,username in enumerate(USERNAMES,1)}
CONTENT_SHA='ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894'
ROOT=Path(r'E:\IG-AutoUpload')

def now():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def safe(root,path):
    root=Path(root).absolute();path=Path(path).absolute();path.relative_to(root)
    for p in (path,*path.parents):
        if (p.exists() or p.is_symlink()) and (p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400)):raise ValueError('路径包含链接，未修改：'+str(p))
    return path

def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
def atomic_bytes(path,blob):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as h:
        temporary=Path(h.name);h.write(blob);h.flush();os.fsync(h.fileno())
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)

@contextlib.contextmanager
def lock(root):
    if sys.platform!='win32':yield;return
    import ctypes
    k=ctypes.WinDLL('kernel32',use_last_error=True);ptr=ctypes.c_void_p;u32=ctypes.c_uint32
    k.CreateMutexW.argtypes=[ptr,ctypes.c_int,ctypes.c_wchar_p];k.CreateMutexW.restype=ptr
    k.WaitForSingleObject.argtypes=[ptr,u32];k.WaitForSingleObject.restype=u32
    k.ReleaseMutex.argtypes=[ptr];k.CloseHandle.argtypes=[ptr]
    handle=k.CreateMutexW(None,False,'Local\\Instagram10Setup-'+hashlib.sha256(str(root).casefold().encode()).hexdigest()[:24]);owned=False
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        code=k.WaitForSingleObject(handle,0)
        if code not in {0,0x80}:raise RuntimeError('Instagram配置任务仍在运行，未并发修改')
        owned=True;yield
    finally:
        if owned:k.ReleaseMutex(handle)
        k.CloseHandle(handle)

def plan(root):
    root=safe(Path(root).absolute(),Path(root).absolute()).resolve()
    if root.name.casefold()!='ig-autoupload' or (root/'upload_config.json').exists() or (root/'account_registry.json').exists():raise ValueError('仅允许原IG-AutoUpload工作区，未接管FB或其他目录')
    if len(MAPPING)!=10 or len({s.casefold() for s in MAPPING.values()})!=10 or any(not re.fullmatch(r'[A-Za-z0-9._]{1,30}',s) for s in MAPPING.values()):raise ValueError('账号名单异常')
    path=safe(root,root/'instagram_accounts.json');owner=read(safe(root,root/'workspace-owner.json'));original=read(path)
    if owner.get('schema')!='instagram-browser-workspace-v1' or owner.get('root')!=str(root) or owner.get('accounts')!=list(MAPPING):raise ValueError('10账号工作区登记不符，请使用原E盘目录')
    rows=original.get('accounts')
    if original.get('schema')!='instagram-browser-accounts-v1' or original.get('root')!=str(root) or not isinstance(rows,list) or len(rows)!=10 or any(not isinstance(r,dict) for r in rows) or {r.get('account') for r in rows}!=set(MAPPING):raise ValueError('原IG账号配置不符，未覆盖')
    new=copy.deepcopy(original)
    for row in new['accounts']:
        slot=row['account'];expected=MAPPING[slot]
        for field,prefix in [('profile_dir','profiles/'),('inbox','videos/'),('published','videos/'),('review','videos/'),('failed','videos/')]:
            required=prefix+slot+('' if field=='profile_dir' else '/'+field)
            if row.get(field)!=required:raise ValueError('原编号资料/素材目录已变化，未重新绑定：'+slot+'/'+field)
            if not safe(root,root/required).is_dir():raise ValueError('编号目录不存在，请先完成原设置：'+required)
        changed=row.get('expected_username')!=expected or row.get('profile_url')!='https://www.instagram.com/'+expected+'/'
        if changed and row.get('publishing_enabled') is True:raise ValueError('账号已启用发布且映射不同，未在运行中更改身份：'+slot)
        if changed:
            history=row.setdefault('identity_mapping_history',[])
            if not isinstance(history,list):raise ValueError('映射历史格式异常')
            if row.get('expected_username') or row.get('profile_url'):
                history.append(dict(expected_username=row.get('expected_username'),profile_url=row.get('profile_url'),identity_verified=row.get('identity_verified',False),replaced_at=now(),reason='user-supplied-all-ten-instagram-profiles-20261126'))
            row.update(expected_username=expected,profile_url='https://www.instagram.com/'+expected+'/',identity_verified=False,publishing_enabled=False,login_state='user_reported_logged_in')
            for old in ('verified_username','identity_verified_at','identity_evidence','verified_actor_id'):
                if old in row:row.setdefault('superseded_identity_evidence',{})[old]=row.pop(old)
        elif not row.get('identity_verified'):
            row.update(publishing_enabled=False,login_state='user_reported_logged_in')
        row.update(identity_mapping_source='user-supplied-all-ten-instagram-profiles-20261126',user_reported_logged_in=True,automatic_first_comment=True)
        row.setdefault('user_reported_login_on','2026-11-26')
    new.update(workflow='logged_in_browser',reuse_facebook_videos=False)
    # Keep all existing caption/comment bytes and paths. Do not overwrite edits.
    for field in ('common_caption.txt','common_comment.txt'):safe(root,root/field)
    return root,path,original,new

def apply(root):
    root=Path(root).absolute()
    with lock(root):
        root,path,original,new=plan(root)
        logs=safe(root,root/'logs');backups=safe(root,root/'backups');logs.mkdir(exist_ok=True);backups.mkdir(exist_ok=True)
        report_path=safe(root,logs/'register-ins01-ins10-20261126.json');csv_path=safe(root,root/'accounts-confirmed-by-user-20261126.csv')
        backup=None
        if original!=new:
            backup=safe(root,backups/('account-mapping-'+uuid.uuid4().hex));backup.mkdir()
            atomic_bytes(backup/'instagram_accounts-before.json',path.read_bytes())
            atomic_bytes(backup/'change.json',encoded(dict(version=VERSION,changed_at=now(),mappings=MAPPING,profiles_untouched=True,publication_started=False)))
            atomic_bytes(path,encoded(new))
        stream=io.StringIO(newline='');writer=csv.writer(stream);writer.writerow(['account','username','profile_url','inbox'])
        for slot,username in MAPPING.items():writer.writerow([slot,username,'https://www.instagram.com/'+username+'/',str(root/'videos'/slot/'inbox')])
        csv_blob=stream.getvalue().encode('utf-8-sig')
        if not csv_path.exists() or csv_path.read_bytes()!=csv_blob:atomic_bytes(csv_path,csv_blob)
        actual=read(path)
        if actual!=new:raise RuntimeError('写入后配置核对失败，请查看备份')
        report=dict(version=VERSION,registered_at=now(),mapping=MAPPING,configured_accounts=10,login_confirmation='user_reported_only',browser_identity_checked_by_this_tool=False,identity_verified_by_this_tool=0,publication_started=False,browser_windows_changed=False,credentials_read=False,facebook_untouched=True,backup=str(backup) if backup else None)
        atomic_bytes(report_path,encoded(report))
    for slot,username in MAPPING.items():print(slot+' -> '+username,flush=True)
    print('已登记10个Instagram账号；保留原登录窗口、素材、正文和首评。',flush=True)
    print('ins01已按本次名单使用ted47868；faithdjurner96不在本次10账号名单。',flush=True)
    print('登录状态来自你的确认；本工具未核验窗口实际身份，未启动视频或评论发布。',flush=True)
    print('素材目录：'+str(root/'videos')+'\\ins01～ins10\\inbox',flush=True)
    print('登记报告：'+str(report_path),flush=True)
    return report

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows电脑PowerShell运行')
        apply(Path(sys.argv[1] if len(sys.argv)>1 else str(ROOT)))
    except Exception as error:print('STOP：'+(str(error) or type(error).__name__),flush=True);raise SystemExit(1)
