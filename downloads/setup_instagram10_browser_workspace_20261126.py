"""Create ten isolated Instagram browser entries and media folders; never publish."""
import contextlib,copy,csv,hashlib,json,os,shutil,subprocess,sys,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
VERSION='1.0-instagram-ins01-ins10-browser-workspace'
ACCOUNTS=tuple(f'ins{i:02}' for i in range(1,11))
CONFIG='instagram_accounts.json'
OWNER='workspace-owner.json'
CAPTION='If this book speaks to you, you can find the same one from the video here.Get your copy here:https://www.amazon.com/gp/product/B0GYJ55PH6?maas=maas_adg_2C08551FB464224E2CDB58F74A72570A_afap_abs&ref_=aa_maas&tag=maas Shop on shopify: https://prycken.com/'
COMMENT='Get your own copy here:https://www.amazon.com/gp/product/B0GYJ55PH6?maas=maas_adg_B2F4D52E550EDAC7E6A92C0290F501F6_afap_abs&ref_=aa_maas&tag=maas'
CONTENT_SHA='ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894'

SHORTCUT_SCRIPT=r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$p=[Console]::In.ReadToEnd() | ConvertFrom-Json
$shell=New-Object -ComObject WScript.Shell
function Matches($Link,$Item) {
 [string]::Equals([string]$Link.TargetPath,[string]$Item.target,[StringComparison]::OrdinalIgnoreCase) -and [string]$Link.Arguments -eq [string]$Item.arguments
}
# Validate every existing link before saving any. Unknown shortcuts are never replaced.
foreach($item in $p.items){
 if(Test-Path -LiteralPath $item.path){
  $info=Get-Item -LiteralPath $item.path -Force
  if(($info.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw ('快捷方式是链接，保留：'+$item.path)}
  $link=$shell.CreateShortcut([string]$item.path)
  if(-not (Matches $link $item)){
   $previous=@($p.previous | Where-Object {[string]::Equals([string]$_.path,[string]$item.path,[StringComparison]::OrdinalIgnoreCase)})
   if($previous.Count -ne 1 -or -not (Matches $link $previous[0])){throw ('存在不同用途的快捷方式，未覆盖：'+$item.path)}
  }
 }
}
if($p.check_only){Write-Output '已有快捷方式检查通过';exit 0}
foreach($item in $p.items){
 $link=$shell.CreateShortcut([string]$item.path)
 if((Test-Path -LiteralPath $item.path) -and (Matches $link $item)){continue}
 $link.TargetPath=[string]$item.target;$link.Arguments=[string]$item.arguments
 $link.WorkingDirectory=[string]$item.working;$link.Description=[string]$item.description
 $link.Save()
}
Write-Output ('快捷方式已就绪：'+$p.items.Count)
'''

def read(path,default=None):return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else copy.deepcopy(default)
def safe(base,path):
    base=Path(base).absolute();path=Path(path).absolute();path.relative_to(base);p=path
    while True:
        if p.exists() and (p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400)):raise ValueError('目录或文件包含链接，未覆盖：'+str(p))
        if p==base:break
        p=p.parent
    return path

def atomic(path,value):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as h:
        temporary=Path(h.name);h.write((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)

@contextlib.contextmanager
def setup_lock(root):
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
        if code not in {0,0x80}:raise RuntimeError('已有Instagram目录设置任务运行，请等待原任务结束')
        owned=True;yield
    finally:
        if owned:k.ReleaseMutex(handle)
        k.CloseHandle(handle)

def find_chrome():
    for variable in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
        if os.environ.get(variable):
            candidate=Path(os.environ[variable])/'Google/Chrome/Application/chrome.exe'
            if candidate.is_file():return candidate
    found=shutil.which('chrome.exe')
    if found:return Path(found)
    raise ValueError('没有找到Google Chrome，请先确认已安装')

def desktop_folder():
    r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',"[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false);[Environment]::GetFolderPath('Desktop')"],capture_output=True,check=True,timeout=20,creationflags=0x08000000)
    path=Path(r.stdout.decode('utf-8-sig').strip())
    if not path.is_absolute() or not path.is_dir():raise ValueError('没有取得当前用户的桌面路径')
    return path

def shortcut_items(root,desktop,chrome):
    result=[]
    for account in ACCOUNTS:
        profile=root/'profiles'/account;inbox=root/'videos'/account/'inbox'
        result.append(dict(path=str(root/'shortcuts'/(account+' Instagram.lnk')),target=str(chrome),working=str(root),description=account+' 独立Instagram登录窗口',arguments=subprocess.list2cmdline(['--user-data-dir='+str(profile),'--profile-directory=Default','--no-first-run','--no-default-browser-check','--new-window','https://www.instagram.com/'])))
        result.append(dict(path=str(root/'shortcuts'/(account+' 待发布素材.lnk')),target=str(inbox),arguments='',working=str(inbox),description=account+' Instagram待发布视频目录'))
    result += [dict(path=str(desktop/'Instagram账号.lnk'),target=str(root/'shortcuts'),arguments='',working=str(root),description='ins01至ins10独立Instagram窗口与素材入口'),dict(path=str(desktop/'Instagram素材.lnk'),target=str(root/'videos'),arguments='',working=str(root),description='10个Instagram账号的独立视频文件夹')]
    return result

def write_shortcuts(items,previous,check_only=False):
    packet=dict(items=items,previous=previous,check_only=check_only)
    r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',SHORTCUT_SCRIPT],input=json.dumps(packet,ensure_ascii=False).encode(),capture_output=True,timeout=60,creationflags=0x08000000)
    if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode('utf-8-sig',errors='replace')[-2500:])

def initial_config(root):
    rows=[]
    for account in ACCOUNTS:
        rows.append(dict(account=account,expected_username='faithdjurner96' if account=='ins01' else None,profile_url='https://www.instagram.com/faithdjurner96/' if account=='ins01' else None,
            profile_dir='profiles/'+account,inbox='videos/'+account+'/inbox',published='videos/'+account+'/published',review='videos/'+account+'/review',failed='videos/'+account+'/failed',
            login_state='not_verified',identity_verified=False,publishing_enabled=False,caption_file='common_caption.txt',comment_file='common_comment.txt',automatic_first_comment=True))
    return dict(schema='instagram-browser-accounts-v1',setup_version=VERSION,root=str(root),workflow='logged_in_browser',reuse_facebook_videos=False,caption_source_revision=CONTENT_SHA,accounts=rows)

def prepare(root,chrome=None,desktop=None,writer=write_shortcuts):
    supplied=Path(root).absolute();safe(supplied,supplied);root=supplied.resolve()
    if root.name.casefold()=='fb-autoupload' or (root/'upload_config.json').exists() or (root/'account_registry.json').exists():raise ValueError('请选择独立IG目录，未修改FB项目')
    chrome=Path(chrome) if chrome is not None else find_chrome();desktop=Path(desktop) if desktop is not None else desktop_folder()
    if not chrome.is_file() or not desktop.is_dir():raise ValueError('Chrome或桌面路径不存在')
    root.mkdir(parents=True,exist_ok=True)
    with setup_lock(root):
        config_path=safe(root,root/CONFIG);owner_path=safe(root,root/OWNER);config=read(config_path);owner=read(owner_path)
        if owner is not None and (owner.get('schema')!='instagram-browser-workspace-v1' or owner.get('root')!=str(root) or owner.get('accounts')!=list(ACCOUNTS)):raise ValueError('已有Instagram工作区范围或所有权记录不符，未覆盖')
        if config is not None:
            if owner is None or config.get('schema')!='instagram-browser-accounts-v1' or config.get('root')!=str(root) or not isinstance(config.get('accounts'),list) or len(config['accounts'])!=10 or {r.get('account') for r in config['accounts']}!=set(ACCOUNTS):raise ValueError('已有账号配置不属于本工具的10个编号，未覆盖')
            for row in config['accounts']:
                if row.get('profile_dir')!='profiles/'+row['account'] or row.get('inbox')!='videos/'+row['account']+'/inbox':raise ValueError('已有账号资料路径已调整，未覆盖或重新绑定')
        paths=[root/'profiles',root/'videos',root/'logs',root/'shortcuts']
        for account in ACCOUNTS:
            profile=root/'profiles'/account;paths.extend([profile]+[root/'videos'/account/name for name in ('inbox','published','review','failed')])
            if owner is None and profile.exists() and any(profile.iterdir()):raise ValueError('存在未登记浏览器资料，未接管：'+str(profile))
        for path in paths:safe(root,path)
        for name in ('common_caption.txt','common_comment.txt','accounts_to_register.csv','使用说明.txt'):safe(root,root/name)
        items=shortcut_items(root,desktop,chrome)
        for item in items:
            path=Path(item['path']);safe(root if path.is_relative_to(root) else desktop,path)
        previous=owner.get('shortcuts',[]) if owner else []
        writer(items,previous,check_only=True)
        # Persist a claim first so an interrupted setup can safely resume.
        if owner is None:
            owner=dict(schema='instagram-browser-workspace-v1',version=VERSION,root=str(root),accounts=list(ACCOUNTS),created_at=datetime.now(timezone.utc).isoformat(),shortcuts=[]);atomic(owner_path,owner)
        for path in paths:path.mkdir(parents=True,exist_ok=True)
        if config is None:config=initial_config(root);atomic(config_path,config)
        for name,value in [('common_caption.txt',CAPTION),('common_comment.txt',COMMENT)]:
            path=root/name
            if not path.exists():path.write_text(value+'\n',encoding='utf-8-sig')
        mapping=root/'accounts_to_register.csv'
        if not mapping.exists():
            with mapping.open('w',encoding='utf-8-sig',newline='') as h:
                w=csv.writer(h);w.writerow(['account','username','profile_url'])
                for row in config['accounts']:w.writerow([row['account'],row.get('expected_username') or '',row.get('profile_url') or ''])
        guide=root/'使用说明.txt'
        if not guide.exists():guide.write_text('Instagram独立窗口与素材目录\n\n1. 桌面打开“Instagram账号”，逐个双击ins01至ins10的Instagram快捷方式，在对应窗口登录账号。无需登录Chrome同步。\n2. ins01预留给faithdjurner96；其余编号登录后记录各自用户名。每个编号使用独立资料目录，首次需要重新登录。\n3. 视频放到videos\\insXX\\inbox；published为已发布，review为待核实，failed为失败目录。快捷方式只打开浏览器或目录，不发布、不自动移动视频。\n4. 本次沿用FB正文和原首评，分别保存在common_caption.txt和common_comment.txt；重跑初始化保留已有改动。\n5. 配置中的账号均尚未核验、不启用自动发布。登录完成并核实编号对应关系后，再配置实际发布流程。\n6. FB程序、素材和浏览器资料不会被本工具修改；不要将FB素材自动混到IG目录。\n',encoding='utf-8-sig')
        writer(items,previous,check_only=False)
        if owner.get('shortcuts')!=items:owner['shortcuts']=items;atomic(owner_path,owner)
        result=dict(version=VERSION,root=str(root),account_count=10,profile_count=10,browser_shortcuts=10,media_shortcuts=10,desktop_entries=[str(desktop/'Instagram账号.lnk'),str(desktop/'Instagram素材.lnk')],instagram_accounts_verified_by_setup=0,automatic_publication_started=False,setup_at=datetime.now(timezone.utc).isoformat())
        atomic(root/'logs/setup-ins01-10.json',result)
    print('已建立ins01～ins10：10个独立Chrome资料目录、10组视频目录、10个窗口快捷方式和10个素材快捷方式。',flush=True)
    print('桌面入口：Instagram账号、Instagram素材。',flush=True)
    print('待发布目录：'+str(root/'videos')+'\\ins01～ins10\\inbox',flush=True)
    print('首次请分别打开编号窗口登录；ins01预留faithdjurner96，其余编号登录后补充用户名。',flush=True)
    print('本次仅建立入口和目录，未核验登录、未启用或发布视频。设置报告：'+str(root/'logs/setup-ins01-10.json'),flush=True)
    return result

if __name__=='__main__':
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows电脑PowerShell运行')
        prepare(Path(sys.argv[1] if len(sys.argv)>1 else r'E:\IG-AutoUpload'))
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
