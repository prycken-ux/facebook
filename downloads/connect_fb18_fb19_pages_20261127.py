"""Register the user's ten new fb18/fb19 Pages; no browser, upload or comment send."""
import copy,hashlib,json,ntpath,os,re,shutil,subprocess,sys,tempfile,uuid
from datetime import date,datetime
from pathlib import Path

if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve())) if len(sys.argv)>1 else None
import fb_upload as upload
import add_fb_accounts as accounts

DAY='2026-11-27'
REPORT='logs/connect-fb18-fb19-pages-20261127.json'
PAGES=(
 ('fb18', 'page01', 'Genesis Franco', '61596537516729'),
 ('fb18', 'page02', 'George Hamilton', '61596767336826'),
 ('fb18', 'page03', 'George Bishop', '61596809964895'),
 ('fb18', 'page04', 'Gary McKinney', '61596831623934'),
 ('fb18', 'page05', 'Gary Dominguez', '61596840203585'),
 ('fb19', 'page01', 'Cefruthi Brosheldplurd', '61596461206832'),
 ('fb19', 'page02', 'Cespuslocro Neftgangping', '61596745082806'),
 ('fb19', 'page03', 'Ceftswoskami Shomprublu', '61596826679349'),
 ('fb19', 'page04', 'Cetbrildgladru Swumblartflo', '61596838498947'),
 ('fb19', 'page05', 'Bruspaliglo Guremti', '61596951625627'),
)
PROCESSES=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$rows=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | ForEach-Object {
 [pscustomobject]@{pid=[long]$_.ProcessId;parent=[long]$_.ParentProcessId;created=$_.CreationDate.ToUniversalTime().ToString('o');name=[string]$_.Name;exe=[string]$_.ExecutablePath;command=[string]$_.CommandLine}
})
ConvertTo-Json -InputObject @($rows) -Compress
'''

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def safe(root,path):
 root=Path(root).absolute();path=Path(path).absolute();path.relative_to(root)
 for p in (path,*path.parents):
  if (p.exists() or p.is_symlink()) and (p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400)):raise ValueError('目录或文件包含链接，保留原内容：'+str(path))
 path.resolve().relative_to(root.resolve());return path

def read(path,required=True):
 path=Path(path)
 if not path.exists():
  if required:raise ValueError('缺少原配置，未自行重建：'+path.name)
  return None
 if not path.is_file() or path.stat().st_size>8_000_000:raise ValueError('原配置文件格式/大小异常：'+path.name)
 return json.loads(path.read_bytes().decode('utf-8-sig'))

def atomic_bytes(path,blob):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as h:
  temp=Path(h.name);h.write(blob);h.flush();os.fsync(h.fileno())
 try:temp.replace(path)
 finally:temp.unlink(missing_ok=True)

def atomic_json(path,value):atomic_bytes(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())

def win_args(line):
 """Decode Windows CRT arguments without executing or shell-expanding them."""
 result=[];i=0
 while i<len(line):
  while i<len(line) and line[i] in ' \t':i+=1
  if i==len(line):break
  word=[];quoted=False
  while i<len(line) and (quoted or line[i] not in ' \t'):
   slashes=0
   while i<len(line) and line[i]=='\\':slashes+=1;i+=1
   if i<len(line) and line[i]=='"':
    word.extend('\\'*(slashes//2))
    if slashes%2:word.append('"');i+=1
    elif quoted and i+1<len(line) and line[i+1]=='"':word.append('"');i+=2
    else:quoted=not quoted;i+=1
   else:
    word.extend('\\'*slashes)
    if i<len(line) and (quoted or line[i] not in ' \t'):word.append(line[i]);i+=1
  if quoted:raise ValueError('Python进程参数无法完整核对，未修改FB配置')
  result.append(''.join(word))
 return result

def blockers(rows,root,pid):
 if not isinstance(rows,list):raise ValueError('无法取得FB进程列表')
 norm=lambda p:ntpath.normcase(ntpath.normpath(str(p)))
 rootkey=norm(root);ig=norm(ntpath.join(ntpath.dirname(str(root)),'IG-AutoUpload'));venvs={norm(ntpath.join(str(root),'.venv','Scripts',name)) for name in ['python.exe','pythonw.exe']};found=[]
 def inside(value,base):return norm(value)==base or norm(value).startswith(base+'\\')
 lookup={};parsed={}
 for row in rows:
  if not isinstance(row,dict) or type(row.get('pid')) is not int or not isinstance(row.get('command'),str) or not isinstance(row.get('exe'),str):raise ValueError('Python进程检查结果异常')
  if row['pid'] in lookup:raise ValueError('Python进程编号重复，未修改配置')
  if not row['command'] and not row['exe']:raise ValueError('有无法核对归属的Python进程，暂未修改配置')
  lookup[row['pid']]=row;args=win_args(row['command'])[1:];parsed[row['pid']]=args[1:] if args[:1]==['-u'] else args
 if pid not in lookup:raise ValueError('无法定位本次接入进程，未修改配置')
 allowed={pid};current=lookup[pid];current_args=parsed[pid]
 own_shape=len(current_args)>=2 and norm(current_args[-1])==rootkey and ((len(current_args)==3 and current_args[0]=='-c' and 'connect_fb18_fb19_pages_20261127.py' in current_args[1]) or ntpath.basename(current_args[0]).lower()=='connect_fb18_fb19_pages_20261127.py')
 # Windows venv redirectors can remain as waiting Python ancestors. Exempt
 # only this exact contiguous launch chain, never a sibling or a reused PID.
 if own_shape:
  for _ in range(8):
   parent=lookup.get(current.get('parent'))
   if parent is None or parent['pid'] in allowed or parsed[parent['pid']]!=current_args:break
   try:
    if datetime.fromisoformat(parent['created'].replace('Z','+00:00'))>datetime.fromisoformat(current['created'].replace('Z','+00:00')):break
   except (KeyError,ValueError,TypeError):break
   allowed.add(parent['pid']);current=parent
 for row in rows:
  if row['pid'] in allowed:continue
  args=parsed[row['pid']]
  # IG deliberately uses the FB interpreter but ends every command in its own
  # workspace. Exempt only an actual IG script or the known IG bootstrap shape.
  if len(args)>=2 and norm(args[-1])==ig:
   script=inside(args[0],ig) and args[0].lower().endswith('.py')
   bootstrap=len(args)==3 and args[0]=='-c' and any(name in args[1] for name in ['start_ig10_publish_20261127.py','start_ig01_demo_record_20261127.py','register_instagram10_accounts_20261126.py'])
   if script or bootstrap:continue
  if norm(row['exe']) in venvs or any(inside(arg,rootkey) or rootkey in arg.replace('/','\\').casefold() for arg in args):found.append(dict(pid=row['pid'],name=row.get('name','python')))
 return found

def inspect_workers(root):
 if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
 result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',PROCESSES],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,creationflags=0x08000000)
 if result.returncode:raise RuntimeError('无法核对当前FB任务，未修改配置')
 return blockers(json.loads(result.stdout.decode('utf-8-sig')),str(root),os.getpid())

def check_workers(root,inspector):
 found=inspector(root)
 if found:raise RuntimeError('仍有FB发布/分配/检查任务，稍后重跑此接入指令；未关闭任务。PID：'+','.join(str(r['pid']) for r in found))

def content_policy(root):
 value=read(safe(root,root/'publication_preferences.json'));updates=value.get('content_updates') if isinstance(value,dict) else None
 if not isinstance(updates,list):raise ValueError('缺少当前统一正文和评论规则，未套用历史文案')
 selected=None;seen=set();today=max(DAY,date.today().isoformat())
 for item in updates:
  p=item.get('payload',{}) if isinstance(item,dict) else {};checksum=item.get('sha256') if isinstance(item,dict) else None
  if checksum!=digest(p) or checksum in seen or p.get('schema')!='publication-content-v1' or any(not isinstance(p.get(k),str) or not p[k].strip() or len(p[k])>5000 for k in ['caption','comment']):raise ValueError('统一正文/评论版本校验失败')
  seen.add(checksum);date.fromisoformat(p['effective_from'])
  if p['effective_from']<=today:selected=item
 if selected is None:raise ValueError('尚无已生效的统一正文/评论规则')
 common=safe(root,root/'common_caption_today.txt')
 if not common.is_file() or common.read_text(encoding='utf-8-sig').strip()!=selected['payload']['caption']:raise ValueError('统一正文文件与当前授权版本不一致，未修改')
 pauses=read(safe(root,root/'publication_account_exclusions.json'),False)
 if pauses is not None:
  p=pauses.get('payload',{})
  if pauses.get('sha256')!=digest(p) or p.get('schema')!='publication-account-exclusions-v1' or not isinstance(p.get('excluded_accounts'),list):raise ValueError('当前停用名单校验失败')
  if {'fb18','fb19'}&set(p['excluded_accounts']):raise ValueError('本次账号在当前停用名单中，未自动恢复或接入发布')
 return selected

def plan(config):
 if not isinstance(config,dict) or not isinstance(config.get('targets'),list) or any(not isinstance(r,dict) for r in config['targets']):raise ValueError('原FB上传配置格式异常')
 pairs=[(r.get('account'),r.get('target')) for r in config['targets']]
 if len(set(pairs))!=len(pairs):raise ValueError('原配置有重复目标编号，未修改')
 owners={}
 for account in ['fb18','fb19']:
  rows=[r for r in config['targets'] if (r.get('account'),r.get('target'))==(account,'personal')]
  if len(rows)!=1 or rows[0].get('type')!='personal':raise ValueError(account+'缺少唯一的原个人号配置，未猜用其他登录资料')
  upload.validate_entry(rows[0]);owners[account]=rows[0]
 updated=copy.deepcopy(config);added=[]
 for account,target,name,number in PAGES:
  current=[r for r in updated['targets'] if (r.get('account'),r.get('target'))==(account,target)]
  for other in updated['targets']:
   if upload.target_key(other.get('url',''))=='id:'+number and other not in current:raise ValueError('主页ID已登记在其他目标，未重复添加：'+account+'/'+target)
  if current:
   row=current[0]
   if row.get('type')!='page' or row.get('name')!=name or upload.target_key(row.get('url',''))!='id:'+number:raise ValueError('目标已用于其他主页，未覆盖：'+account+'/'+target)
   upload.validate_entry(row)
  else:
   row=dict(account=account,target=target,type='page',name=name,url='https://www.facebook.com/profile.php?id='+number,enabled=False,workflow='page_flow_configured',ai_label=owners[account].get('ai_label',True),excluded_files=[])
   upload.validate_entry(row);updated['targets'].append(row);added.append((account,target))
 return updated,added

def comment_targets(settings):
 if settings is None:return None
 if not isinstance(settings,dict) or settings.get('schema')!='per-video-post-comment-v1' or settings.get('future_only') is not True or not isinstance(settings.get('targets'),list):raise ValueError('原逐视频评论配置格式异常，未覆盖或重置开关')
 result=copy.deepcopy(settings);seen=set()
 for row in result['targets']:
  if not isinstance(row,dict) or (row.get('account'),row.get('target')) in seen:raise ValueError('原评论配置含重复或无效目标')
  seen.add((row.get('account'),row.get('target')));upload.target_key(row.get('url',''))
 for a,t,_,number in PAGES:
  current=[r for r in result['targets'] if (r.get('account'),r.get('target'))==(a,t)]
  if current and upload.target_key(current[0]['url'])!='id:'+number:raise ValueError('原评论目标已绑定其他主页，未覆盖：'+a+'/'+t)
  if not current:result['targets'].append(dict(account=a,target=t,url='https://www.facebook.com/profile.php?id='+number))
 return result

def connect(root,inspector=inspect_workers):
 root=Path(root).absolute();safe(root,root)
 if root.resolve()!=upload.ROOT.resolve() or root.resolve()!=accounts.ROOT.resolve() or upload.CONFIG.resolve()!=root/'upload_config.json':raise ValueError('不是原FB上传目录，未修改其他工具')
 if upload.VERSION!='2.47':raise ValueError('原FB上传核心版本不匹配，未覆盖原程序')
 for account in ['fb18','fb19']:
  if not safe(root,root/'profiles'/account).is_dir():raise ValueError('缺少'+account+'原登录资料，未建立空白资料代替')
 check_workers(root,inspector)
 with accounts.locked():
  check_workers(root,inspector);config_path=safe(root,root/'upload_config.json');before=config_path.read_bytes();config=json.loads(before.decode('utf-8-sig'));updated,added=plan(config);policy=content_policy(root)
  folders=[safe(root,root/'videos'/a/t/f) for a,t,_,_ in PAGES for f in ['inbox','completed','failed']]
  for folder in folders:
   if folder.exists() and not folder.is_dir():raise ValueError('目标目录已有同名文件，未覆盖：'+str(folder))
  report_path=safe(root,root/REPORT);old_report=read(report_path,False);comment_path=safe(root,root/'post_comment_config.json');old_comments=read(comment_path,False);new_comments=comment_targets(old_comments)
  payload=dict(schema='fb-managed-pages-registration-v1',date=DAY,accounts=['fb18','fb19'],page_count=10,targets=[dict(account=a,target=t,name=n,url='https://www.facebook.com/profile.php?id='+number,inbox='videos/'+a+'/'+t+'/inbox',profile='profiles/'+a) for a,t,n,number in PAGES],caption_policy='inherit-latest-authorized-FB-content-at-new-batch-creation',observed_content_revision=policy['sha256'],comment_policy='same-original-comment-after-exact-video-and-own-comment-reload-verification',existing_per_video_comment_targets_merged=new_comments is not None,identity_verification='required-before-publication',registration_only=True,original_personal_targets_preserved=True,original_frozen_batches_preserved=True)
  report=dict(payload=payload,sha256=digest(payload));changes={}
  if added:changes[config_path]=updated
  if new_comments!=old_comments:changes[comment_path]=new_comments
  if old_report!=report:changes[report_path]=report
  originals={p:p.read_bytes() if p.is_file() else None for p in [config_path,comment_path,report_path]}
  if originals[config_path]!=before:raise RuntimeError('配置正在变化，未覆盖其他修改')
  for folder in folders:folder.mkdir(parents=True,exist_ok=True)
  if config_path.read_bytes()!=before:raise RuntimeError('配置正在变化，未覆盖其他修改')
  backup=None
  if changes:
   backup=safe(root,root/'backups'/('connect-fb18-fb19-pages-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]));backup.mkdir(parents=True)
   for path,blob in originals.items():
    if blob is not None:(backup/path.name).write_bytes(blob)
  attempted=[]
  try:
   check_workers(root,inspector)
   if any((p.read_bytes() if p.is_file() else None)!=old for p,old in originals.items()):raise RuntimeError('配置正在变化，未覆盖其他修改')
   for path,value in changes.items():
    attempted.append(path);atomic_json(path,value)
    if read(path)!=value:raise RuntimeError('配置写入后核对失败：'+path.name)
   if read(config_path)!=updated:raise RuntimeError('配置写入后核对失败')
   if read(report_path)!=report:raise RuntimeError('主页登记报告写入后核对失败')
  except BaseException:
   for path in reversed(attempted):
    if originals[path] is None:path.unlink(missing_ok=True)
    else:atomic_bytes(path,originals[path])
   raise
  print('fb18、fb19各5个公共主页已登记；本次新增 '+str(len(added))+' 个，本组共10个。',flush=True)
  for account,target,name,number in PAGES:
   print(account+'/'+target+' '+name+' https://www.facebook.com/profile.php?id='+number,flush=True);print('素材目录：'+str(root/'videos'/account/target/'inbox'),flush=True)
  print('统一正文和评论沿用当前授权版本：'+policy['sha256'],flush=True)
  if backup:print('原配置备份：'+str(backup),flush=True)
  print('登记报告：'+str(report_path),flush=True)
  print('保留原个人号、登录资料、素材、历史视频/评论记录和旧批次。',flush=True)
  print('本次仅登记并建立目录，尚未核验新主页身份、上传视频或发送评论。后续新批次发布时逐页核验身份，并使用原视频/首评防重规则。',flush=True)
  return updated

def main():
 if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
 if len(sys.argv)!=2:raise ValueError('请指定原E:\\FB-AutoUpload目录')
 connect(Path(sys.argv[1]));return 0

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
 try:raise SystemExit(main())
 except KeyboardInterrupt:print('已停止；可重跑同一接入指令，原配置及已登记目标保留。',flush=True);raise SystemExit(130)
 except Exception as error:print('STOP：'+str(error),flush=True);raise SystemExit(1)
