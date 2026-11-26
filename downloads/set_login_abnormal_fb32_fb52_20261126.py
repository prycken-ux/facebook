"""Persist the user's fb32/fb52 login-abnormal stop rule without changing jobs."""
import copy,hashlib,json,os,re,shutil,sys,tempfile,time,uuid
from datetime import datetime,timezone
from pathlib import Path
VERSION='1.0-user-login-abnormal-fb32-fb52'
ACCOUNTS={'fb32','fb52'}
BASE_EXCLUDED={f'fb{n:02d}' for n in (17,23,25,27,28,29,30,33,34,35,36,38,39,40,41,42,43,44,48,50,53,56,57,58,59,61,64,65,67,69,71,72,73,74)}

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def read(path,default):return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else copy.deepcopy(default)
def safe(root,path):
    path=Path(path);path.absolute().relative_to(root.absolute());current=path
    while current!=root.parent:
        if current.exists() and (current.is_symlink() or bool(getattr(current.lstat(),'st_file_attributes',0)&0x400)):raise ValueError('设置路径包含链接，未修改。')
        if current==root:break
        current=current.parent
    return path

def save(path,value):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:
        temporary=Path(handle.name);handle.write((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode());handle.flush();os.fsync(handle.fileno())
    try:
        for attempt in range(20):
            try:os.replace(temporary,path);break
            except PermissionError:
                if attempt==19:raise
                time.sleep(.05)
    finally:temporary.unlink(missing_ok=True)

def apply(root):
    supplied=Path(root).absolute();safe(supplied,supplied);root=supplied.resolve()
    if not safe(root,root/'upload_config.json').is_file():raise ValueError('请指定原FB-AutoUpload目录，未创建新账号或发布任务。')
    policy_path=safe(root,root/'publication_account_exclusions.json');old=read(policy_path,None)
    if old is not None and (not isinstance(old,dict) or not isinstance(old.get('payload'),dict)
            or old.get('sha256')!=digest(old['payload']) or old['payload'].get('schema')!='publication-account-exclusions-v1'
            or not isinstance(old['payload'].get('excluded_accounts'),list)
            or any(not re.fullmatch(r'fb\d{2,}',str(a)) for a in old['payload']['excluded_accounts'])):raise ValueError('原停用名单校验失败，未覆盖设置。')
    payload=copy.deepcopy(old['payload']) if old else dict(schema='publication-account-exclusions-v1',effective_from='2026-11-26')
    excluded=BASE_EXCLUDED|ACCOUNTS|set(payload.get('excluded_accounts',[]))
    payload.update(excluded_accounts=sorted(excluded),skip_material_allocation=True,skip_verification=True,skip_publication=True,skip_video_retries=True,skip_comment_retries=True)
    overrides=payload.setdefault('account_status_overrides',{})
    if not isinstance(overrides,dict):raise ValueError('原账号状态设置异常，未覆盖。')
    at=datetime.now(timezone.utc).isoformat()
    for account in sorted(ACCOUNTS):
        previous=overrides.get(account,{})
        if not isinstance(previous,dict):raise ValueError('原账号状态记录异常，未覆盖。')
        value=dict(previous,status='login_abnormal',reason='user-confirmed-login-abnormal',publishing_enabled=False,auto_resume=False)
        value.setdefault('disabled_at',at);overrides[account]=value
    new=dict(payload=payload,sha256=digest(payload))
    registry_path=safe(root,root/'additional_personal_accounts.json');registry=read(registry_path,None);updated=copy.deepcopy(registry)
    if registry is not None:
        if not isinstance(registry,dict) or registry.get('schema')!='additional-personal-logins-v1' or not isinstance(registry.get('slots'),dict):raise ValueError('原账号登记格式异常，未修改任何设置。')
        for account in sorted(ACCOUNTS):
            slot=updated['slots'].get(account)
            if slot is None:continue
            if not isinstance(slot,dict):raise ValueError('原账号登记异常，未修改任何设置。')
            if 'publishing_ready_before_login_abnormal' not in slot:slot['publishing_ready_before_login_abnormal']=slot.get('publishing_ready',False)
            slot.update(publishing_ready=False,login_status='login_abnormal',publishing_disabled_reason='user-confirmed-login-abnormal',automatic_retry_enabled=False)
            slot.setdefault('publishing_disabled_at',at)
    changes=[]
    if new!=old:changes.append((policy_path,new))
    if updated!=registry:changes.append((registry_path,updated))
    backup=None
    if changes:
        backup=safe(root,root/'backups'/('login-abnormal-fb32-fb52-'+uuid.uuid4().hex));safe(root,backup.parent).mkdir(exist_ok=True);backup.mkdir()
        for path,value in changes:
            if path.exists():shutil.copy2(path,backup/path.name)
        save(backup/'change.json',dict(version=VERSION,accounts=sorted(ACCOUNTS),reason='user-confirmed-login-abnormal',at=at,files=[path.name for path,value in changes]))
        # Disable registration readiness first. Neither write changes an actor,
        # existing publication ledger, signed job, source video or credential.
        for path,value in sorted(changes,key=lambda item:item[0]==policy_path):save(path,value)
    actual=read(policy_path,{})
    if actual.get('sha256')!=digest(actual.get('payload',{})) or not ACCOUNTS<=set(actual.get('payload',{}).get('excluded_accounts',[])):raise ValueError('写入后停用设置核验失败，请查看备份。')
    print('已设置：fb32、fb52 = 登录异常；后续不分配、不验证、不发布、不补发/补评；不会自动恢复。',flush=True)
    print('当前停用账号：'+str(len(excluded))+'个；历史素材、发布记录和登录资料保留。',flush=True)
    if backup:print('设置备份：'+str(backup),flush=True)
    else:print('原设置已一致，无需重复修改。',flush=True)
    print('后续任务需读取更新后的名单；本操作不终止当前进程，也不启动发布。',flush=True)
    return 0

if __name__=='__main__':
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
        raise SystemExit(apply(Path(sys.argv[1])))
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
