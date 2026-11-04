"""Permanently remove only the three unsuccessful personal onboarding accounts."""
import ast,copy,hashlib,json,re,shutil,ssl,stat,sys,urllib.request
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import add_fb_accounts as legacy
from diagnose_personal_identity import close_selected_window

ACCOUNTS=('fb24','fb25','fb26')
BATCH_ID='personal-20261104-three'
MANIFEST='additional_personal_accounts.json'
MATCH=re.compile(r'(?<![A-Za-z0-9])fb(?:24|25|26)(?![A-Za-z0-9])',re.I)
DROP=object()
CONTROLLERS={'connect_three_personal_20261104.py','start_three_personal_20261104.py'}
PROGRESS='remove-three-personal-in-progress.json'
OWNED_FILE=re.compile(r'(?:(?:identity|login|session|profile)-)?fb(?:24|25|26)(?:-personal)?\.[^.]+$',re.I)


def scrub(value):
    if isinstance(value,dict):
        if value.get('account') in ACCOUNTS or value.get('batch_id')==BATCH_ID:return DROP
        strings=value.get('accounts')
        if isinstance(strings,list) and strings and all(isinstance(v,str) for v in strings) and all(v in ACCOUNTS for v in strings):return DROP
        result={}
        for key,item in value.items():
            if key in ACCOUNTS or key==BATCH_ID:continue
            cleaned=scrub(item)
            if cleaned is not DROP:result[key]=cleaned
        if isinstance(strings,list) and all(isinstance(v,str) for v in strings) and isinstance(value.get('count'),int):
            result['count']=len(result.get('accounts',[]))
        return result
    if isinstance(value,list):
        result=[]
        for item in value:
            cleaned=scrub(item)
            if cleaned is not DROP:result.append(cleaned)
        return result
    if isinstance(value,str) and (MATCH.search(value) or value==BATCH_ID):return DROP
    return value


def checked(path):
    path=Path(path);root=upload.ROOT.resolve()
    path.resolve().relative_to(root)
    if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
        raise ValueError('检测到链接或重解析路径，未删除：'+str(path.relative_to(upload.ROOT)))
    return path


def documents_and_paths():
    root=upload.ROOT;manifest_path=root/MANIFEST
    config=upload.read_json(root/'upload_config.json',None);registry=upload.read_json(root/'account_registry.json',None)
    manifest=upload.read_json(manifest_path,None)
    if (not isinstance(config,dict) or not isinstance(config.get('targets'),list)
            or not isinstance(registry,dict) or not isinstance(registry.get('accounts'),list)
            or not isinstance(manifest,dict) or manifest.get('schema')!='additional-personal-logins-v1'
            or not isinstance(manifest.get('slots'),dict) or not isinstance(manifest.get('batches'),dict)):
        raise ValueError('原账号配置或新增登记格式异常，未执行清理')
    batch=manifest['batches'].get(BATCH_ID)
    present={a for a in ACCOUNTS if a in manifest['slots']}
    if batch is not None:
        if not isinstance(batch,dict) or batch.get('count')!=3 or batch.get('accounts')!=list(ACCOUNTS):
            raise ValueError('本次新增批次并非指定fb24、fb25、fb26，未删除其他账号')
    for account in present:
        slot=manifest['slots'][account]
        if not isinstance(slot,dict) or slot.get('batch_id')!=BATCH_ID:raise ValueError(account+'已属于其他新增批次，未删除')
    # Validate and plan all content changes before closing windows or deleting.
    paths=[]
    for account in ACCOUNTS:
        paths.extend([root/'profiles'/account,root/'videos'/account,root/'新增账号登录'/(account+' 登录.lnk')])
    for name in CONTROLLERS:paths.append(root/name)
    for base in (root/'backups',root/'logs',root/'__pycache__'):
        if not base.exists():continue
        for path in base.rglob('*'):
            if (path.name in ACCOUNTS or path.name in {a+' 登录.lnk' for a in ACCOUNTS}
                    or path.name in CONTROLLERS or any(path.name.startswith(Path(n).stem+'.') and path.suffix=='.pyc' for n in CONTROLLERS)
                    or path.is_file() and OWNED_FILE.fullmatch(path.name)):
                paths.append(path)
    existing=sorted({checked(p) for p in paths if p.exists()},key=lambda p:len(p.parts))
    selected=[]
    for path in existing:
        if not any(parent==path or parent in path.parents for parent in selected):selected.append(path)
    json_paths=list(root.glob('*.json'))+list(root.glob('*.json.tmp'))
    for base in (root/'backups',root/'logs'):
        if base.exists():json_paths.extend(base.rglob('*.json'));json_paths.extend(base.rglob('*.json.tmp'))
    updates=[]
    for path in sorted(set(json_paths)):
        if path==root/'logs'/PROGRESS:continue
        if any(parent==path or parent in path.parents for parent in selected):continue
        checked(path);raw=path.read_bytes()
        try:value=json.loads(raw.decode('utf-8-sig'))
        except (ValueError,UnicodeError):
            if any(a.encode() in raw for a in ACCOUNTS) or BATCH_ID.encode() in raw:
                raise ValueError('包含指定账号信息的JSON无法核验，未开始删除：'+str(path.relative_to(root)))
            continue
        cleaned=scrub(value)
        if cleaned is DROP:selected.append(path)
        elif cleaned!=value:updates.append((path,raw,cleaned))
    if batch is None and (selected or updates):
        progress=upload.read_json(root/'logs'/PROGRESS,{})
        if progress!=dict(batch_id=BATCH_ID,accounts=list(ACCOUNTS)):
            raise ValueError('未找到这次新增批次的归属记录，未根据编号删除可能属于其他批次的资料')
    return selected,updates


def execute():
    with legacy.locked():
        selected,updates=documents_and_paths()
        if not selected and not updates:
            (upload.ROOT/'logs'/PROGRESS).unlink(missing_ok=True)
            print('fb24、fb25、fb26本次新增资料已清理完成，没有重复删除。',flush=True);return 0
        for account in ACCOUNTS:
            print('正在正常关闭独立账号窗口：',account,flush=True)
            close_selected_window(account)
        for path,original,value in updates:
            if path.read_bytes()!=original:raise ValueError('资料在核对期间发生变化，停止删除：'+path.name)
        # This temporary ownership marker contains no credentials and is
        # deleted after verification; it permits interrupted cleanup to resume.
        upload.save_json(upload.ROOT/'logs'/PROGRESS,dict(batch_id=BATCH_ID,accounts=list(ACCOUNTS)))
        # Remove all active and backed-up registrations before removing local
        # files. Atomic JSON replacement preserves unrelated accounts.
        for path,original,value in updates:upload.save_json(path,value)
        for path in selected:
            if not path.exists():continue
            checked(path)
            if path.is_dir():shutil.rmtree(path)
            else:path.unlink()
        remaining,changes=documents_and_paths()
        if remaining or changes:raise RuntimeError('仍有指定账号资料未清理完成，请保留输出并重跑本命令')
        (upload.ROOT/'logs'/PROGRESS).unlink(missing_ok=True)
        print('已永久清理本地fb24、fb25、fb26：登录资料、缓存、账号目录、登录入口、预留登记及相关JSON备份中的账号信息。',flush=True)
        print('本次未创建账号资料备份；其他账号的配置及发布、评论记录保留。',flush=True)
    return 0


def recover_locks():
    if not any((upload.ROOT/'logs'/name).exists() for name in ('batch.lock','upload.lock')):return
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    expected='2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3'
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(base+'d8c998c705801c948a230c0504fcb65653ae8086/downloads/recover_resume_new_batch.py',context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Lock helper checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));break
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    else:raise RuntimeError('锁核验组件下载失败，未删除账号资料')
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(data,'verified-lock-library','exec'),namespace);namespace['recover_locks'](upload.ROOT)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if sys.platform!='win32' or upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原Windows上传电脑运行')
        recover_locks();raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止；部分清理可能已完成，重跑本命令继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
