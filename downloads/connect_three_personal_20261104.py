"""Three user-owned personal logins, verified registration and publication wiring."""
import copy,hashlib,shutil,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
import add_personal_accounts as accounts
import add_fb_accounts as legacy
import fb_upload as upload
import scheduled_material_batch as batch
from diagnose_personal_identity import close_selected_window

BATCH_ID='personal-20261104-three'
METHOD='verified-personal-onboarding-v1'


def prepare():
    chrome=legacy.find_chrome()
    with legacy.locked():
        selected=accounts.reserve(3,BATCH_ID)
        folder=accounts.ROOT/accounts.SHORTCUTS;folder.mkdir(exist_ok=True)
        items=accounts.shortcut_items(selected,chrome)
        existing=[Path(item['path']) for item in items if Path(item['path']).is_file()]
        if existing:
            backup=accounts.ROOT/'backups'/('three-personal-shortcuts-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
            for path in existing:shutil.copy2(path,backup/path.name)
        legacy.write_shortcuts(items)
    print('这次新增的3个个人号：',', '.join(selected),'；重复运行会继续这3个编号。',flush=True)
    return selected


def binding(config,registry,manifest,account):
    slot=manifest['slots'].get(account)
    if not isinstance(slot,dict) or slot.get('batch_id')!=BATCH_ID:raise ValueError('账号不属于这次新增的3个个人号')
    if not (accounts.ROOT/'profiles'/account).is_dir():raise ValueError('原独立浏览器资料缺失，未创建空白资料代替')
    if slot['state']=='pending':return slot,None
    mapping=slot.get('mapping')
    configured=[r for r in config['targets'] if r.get('account')==account]
    known=[r for r in registry['accounts'] if r.get('account')==account]
    if not isinstance(mapping,dict) or len(configured)!=1 or len(known)!=1:raise ValueError('已登记的新账号配置不唯一')
    for row in configured+known:
        if any(row.get(k)!=mapping.get(k) for k in ('account','target','type','name','url','workflow')):
            raise ValueError('已登记的新账号对应关系变化，未覆盖')
    return slot,configured[0]


def verify(entry):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        context=upload.launch_context(playwright,entry)
        try:
            page=context.new_page();upload.navigate_profile(page,entry['url'])
            upload.require_no_advanced_protection(page)
            proof=upload.ensure_personal_identity(page,entry)
            people={c['value'] for c in context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and c.get('value')}
            if len(people)!=1 or not next(iter(people)).isdecimal():raise ValueError('无法确认当前个人号的主页编号')
            owner=next(iter(people))
            if hashlib.sha256(('personal:'+owner).encode('ascii')).hexdigest()!=proof.get('session_marker'):
                raise ValueError('核验期间个人号身份变化')
            owner_url='https://www.facebook.com/profile.php?id='+owner
        finally:context.close()
    return dict(target_url=owner_url,name=proof['name'],method=proof['method'],
                checked_at=datetime.now(timezone.utc).isoformat())


def activate(account,proof):
    with legacy.locked():
        original=accounts.documents();config,registry,manifest=copy.deepcopy(original)
        slot,row=binding(config,registry,manifest,account)
        if (row is None or proof.get('method') not in {'personal_actor_id_match','personal_me_redirect_match'}
                or proof.get('name')!=row['name'] or upload.target_key(proof.get('target_url',''))!=upload.target_key(row['url'])
                or not proof.get('checked_at')):raise ValueError('本人主页核验与登记目标不一致，未接入发布')
        row.update(enabled=True,identity_verified_at=proof['checked_at'],personal_onboarding_method=METHOD)
        slot.update(publishing_ready=True,identity_verified_at=proof['checked_at'],identity_method=proof['method'])
        paths=[accounts.ROOT/'upload_config.json',accounts.ROOT/accounts.MANIFEST]
        backup=accounts.ROOT/'backups'/('three-personal-connected-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        for path in paths:shutil.copy2(path,backup/path.name)
        upload.save_json(backup/'onboarding-proof.json',dict(account=account,batch_id=BATCH_ID,proof=proof))
        try:
            for path,doc in zip(paths,(config,manifest)):upload.save_json(path,doc)
            if not batch.eligible(row,True):raise ValueError('发布批次仍未识别新账号，恢复原配置')
        except BaseException:
            for path in paths:shutil.copy2(backup/path.name,path)
            raise
    print('已核验并接入视频发布：',account,row['name'],row['url'],flush=True)
    print('视频目录：',upload.inbox_for(row),flush=True)


def ask(prompt):
    value=input(prompt).strip()
    if value.upper()=='Q':raise KeyboardInterrupt
    return value


def connect(account):
    while True:
        with legacy.locked():
            config,registry,manifest=accounts.documents();slot,row=binding(config,registry,manifest,account)
            if row and slot.get('publishing_ready') is True and row.get('personal_onboarding_method')==METHOD and batch.eligible(row,True):
                print('已接入，保留原登录和配置：',account,row['name'],upload.inbox_for(row),flush=True);return True
            saved=copy.deepcopy(row)
        print('\n现在登录：',account,'。请在打开的窗口登录一个新的个人账号，并进入本人主页。',flush=True)
        accounts.open_accounts([account])
        if saved:
            print('已登记本人主页：',saved['name'],saved['url'],flush=True)
            if ask('登录完成后按回车核验；S跳过，Q结束：').upper()=='S':return False
            name,url=saved['name'],saved['url']
        else:
            name=ask('登录完成后填写本人主页名称；S跳过，Q结束：')
            if name.upper()=='S':return False
            url=ask('粘贴该账号本人主页网址（不是视频网址）；Q结束：')
        try:
            if not name or any(ord(c)<32 for c in name):raise ValueError('主页名称必须是非空单行文字')
            url=accounts.canonical_url(url)
            entry=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',
                       name=name,url=url,auto_switch_personal=True)
            upload.validate_entry(entry)
            with legacy.locked():
                config,registry,manifest=accounts.documents();binding(config,registry,manifest,account)
                if any(r.get('account')!=account and upload.target_key(r.get('url',''))==upload.target_key(url)
                       for r in config['targets']+registry['accounts']):raise ValueError('该本人主页已属于其他编号，请登录另一个个人号')
                print('正常关闭',account,'的登录窗口，重新打开并核验本人身份。',flush=True)
                close_selected_window(account);proof=verify(entry)
            accounts.register(account,name,proof['target_url']);activate(account,proof);return True
        except Exception as error:
            print('这条尚未接入：',(str(error) or type(error).__name__).split('\n',1)[0],flush=True)
            choice=ask('回车重新打开并重试；S跳过本账号，Q结束：')
            if choice.upper()=='S':return False


def execute():
    if getattr(batch,'NEW_PERSONAL_ACCOUNTS_VERSION','')!='1.0-verified-onboarding':raise ValueError('新个人号发布识别模块未安装')
    selected=prepare();connected=[];pending=[]
    for account in selected:
        (connected if connect(account) else pending).append(account)
    print('\n这次接入成功：',', '.join(connected) or '暂无','；尚未完成：',', '.join(pending) or '无',flush=True)
    print('以后把MP4和同名TXT放入对应personal/inbox目录，使用新视频发布流程即可选择这些账号。',flush=True)
    print('本次只新增登录和发布配置，没有上传视频；不需要把密码或验证码发到聊天。',flush=True)
    return 0 if not pending else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已暂停；登录资料和已完成接入保留，重跑继续这3个编号。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
