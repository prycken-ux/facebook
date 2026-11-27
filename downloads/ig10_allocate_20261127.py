"""Allocate ten independent IG clips while retaining every source original."""
import hashlib,os,re,shutil,time,uuid,zipfile
from pathlib import Path
import ig10_common_20261127 as c
POINTER='material-staging/ig10-20261127-pending.json'

def natural(value):return tuple((0,int(p)) if p.isdecimal() else (1,p.casefold()) for p in re.split('(\\d+)',value))
def choose():
 import subprocess
 code=r'''Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$d=New-Object Windows.Forms.FolderBrowserDialog;$d.Description='请选择今天IG素材的总文件夹（自动扫描子文件夹并分配到10个账号）';$d.ShowNewFolderButton=$false
try{if($d.ShowDialog() -eq [Windows.Forms.DialogResult]::OK){[Console]::WriteLine($d.SelectedPath)}}finally{$d.Dispose()}
'''
 p=subprocess.run(['powershell.exe','-STA','-NoProfile','-Command',code],capture_output=True,timeout=600,creationflags=0x08000000)
 if p.returncode:raise RuntimeError('素材目录选择未完成')
 value=p.stdout.decode('utf-8-sig').strip()
 if not value:raise KeyboardInterrupt
 return Path(value)

def source_folder(root,path):
 path=Path(path).absolute()
 for part in (path,*path.parents):
  if (part.exists() or part.is_symlink()) and c.linked(part):raise ValueError('素材总目录包含链接')
 path=path.resolve()
 if any(p.casefold()=='fb-autoupload' for p in path.parts):raise ValueError('请选择IG独立素材，不使用FB目录')
 if not path.is_dir():raise ValueError('素材总目录不存在')
 if any(path.is_relative_to((root/n).resolve()) for n in ('profiles','logs','backups','material-staging','tools')):raise ValueError('请选择视频总目录，不选资料或日志目录')
 return path

def prior_hashes_by_platform(root):
 hashes={'ig':set(),'fb':set()}
 for p in (root/'material-staging').glob('*/*/manifest.json'):
  value=c.checked(c.safe(root,p));hashes['ig'].update(j['video_sha256'] for j in value['payload']['jobs'])
 # Read only immutable FB allocation fingerprints; preserve independent material.
 fb=root.parent/'FB-AutoUpload'
 for p in (fb/'logs/material-distribution').glob('*/*.json'):
  if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:-eligible\d+|-reserved50)?\.json',p.name):continue
  value=c.checked(c.safe(fb,p))
  for row in value['payload'].get('assignments',[]):
   hashes['fb'].update(f['sha256'] for f in row.get('files',[]) if Path(f.get('name','')).suffix.lower() in c.EXT)
 return hashes

def previous_hashes(root):
 values=prior_hashes_by_platform(root);return values['ig']|values['fb']

SKIP_DIRS={'profiles','logs','backups','material-staging','tools','shortcuts','published','review','failed','fb-autoupload','$recycle.bin','system volume information','.git'}
OTHER_VIDEO={'.mkv','.webm','.avi','.wmv','.flv','.ts','.mts','.m2ts','.3gp','.mpeg','.mpg'}

def scan_source(root,source):
 """Scan the chosen total folder recursively; no per-slot source requirement."""
 report=dict(source=str(source),date=c.DAY,scanned_at=c.stamp(),supported_extensions=sorted(c.EXT),files=[],skipped_directories=[],scan_errors=[])
 print('正在扫描IG素材总目录及子目录：'+str(source),flush=True)
 candidates=[]
 def walk_error(error):report['scan_errors'].append(dict(path=str(error.filename),reason=str(error)))
 for folder,dirs,names in os.walk(source,topdown=True,followlinks=False,onerror=walk_error):
  base=Path(folder);keep=[]
  for name in sorted(dirs,key=natural):
   p=base/name
   try:
    if name.casefold() in SKIP_DIRS or c.linked(p):report['skipped_directories'].append(str(p.relative_to(source)))
    else:keep.append(name)
   except OSError as error:report['scan_errors'].append(dict(path=str(p),reason=str(error)))
  dirs[:]=keep
  for name in names:
   p=base/name
   if p.suffix.lower() in c.EXT|OTHER_VIDEO:candidates.append(p)
 candidates.sort(key=lambda p:(natural(str(p.relative_to(source))),str(p.relative_to(source))))
 seen={};eligible=[];history=prior_hashes_by_platform(root)
 for index,p in enumerate(candidates,1):
  row=dict(path=str(p),relative_path=str(p.relative_to(source)),extension=p.suffix.lower());report['files'].append(row)
  if index==1 or index%10==0:print('正在核对IG素材：'+str(index)+' / '+str(len(candidates)),flush=True)
  if p.suffix.lower() not in c.EXT:row.update(reason='unsupported_format');continue
  if re.match(r'^\d{8}-[a-f0-9]{8}-ins\d{2}-',p.name) and p.is_relative_to(root/'videos'):
   row.update(reason='existing_assigned_copy');continue
  try:
   if c.linked(p):row.update(reason='linked_file');continue
   info=c.file_info(p)
  except (OSError,ValueError) as error:row.update(reason='unreadable_or_changing_file',detail=str(error));continue
  row.update(**info)
  if info['sha256'] in history['ig']:row.update(reason='previous_ig_allocation');continue
  if info['sha256'] in history['fb']:row.update(reason='previous_fb_allocation');continue
  if info['sha256'] in seen:row.update(reason='duplicate_content',duplicate_of=seen[info['sha256']]);continue
  seen[info['sha256']]=str(p);row.update(reason='eligible')
  parts=[x.casefold() for x in p.relative_to(source).parts[:-1]]
  row['preferred_account']=next((x for x in parts if x in c.MAPPING),None);eligible.append((p,info,row))
 counts={name:sum(r['reason']==name for r in report['files']) for name in ['eligible','duplicate_content','previous_ig_allocation','previous_fb_allocation','unsupported_format','linked_file','existing_assigned_copy','unreadable_or_changing_file']}
 report.update(counts=counts,video_files_seen=len(candidates),eligible_unique=len(eligible),scan_complete=not report['scan_errors'],allocation_possible=len(eligible)>=10)
 # Reserve a matching slot's first clip before using surplus clips for empty slots.
 reserved={};taken=set()
 for a in c.MAPPING:
  match=next((v for v in eligible if v[2]['preferred_account']==a and v[1]['sha256'] not in taken),None)
  if match:reserved[a]=match;taken.add(match[1]['sha256'])
 for a in c.MAPPING:
  if a in reserved:continue
  match=next((v for v in eligible if v[1]['sha256'] not in taken),None)
  if match:reserved[a]=match;taken.add(match[1]['sha256'])
 report['proposed_assignments']=[dict(account=a,source_video=str(v[0]),video_sha256=v[1]['sha256']) for a,v in reserved.items()]
 summary='扫描视频 '+str(len(candidates))+' 个；可分配独立素材 '+str(len(eligible))+' 个；内容重复 '+str(counts['duplicate_content'])+'；IG历史 '+str(counts['previous_ig_allocation'])+'；FB历史 '+str(counts['previous_fb_allocation'])+'；格式不支持 '+str(counts['unsupported_format'])+'；读取异常 '+str(counts['unreadable_or_changing_file'])
 print(summary,flush=True)
 scan=root/'logs/ig-material-scan-20261127.json';c.save(scan,report)
 lines=['IG素材扫描（复制和发布之前）',str(source),summary,'跳过历史/系统目录 '+str(len(report['skipped_directories']))+' 个','目录读取异常 '+str(len(report['scan_errors']))+' 个']
 lines += [r['reason']+' | '+r['relative_path']+(' | '+r.get('detail','') if r.get('detail') else '') for r in report['files']]
 text=root/'logs/ig-material-scan-20261127.txt';text.write_text('\n'.join(lines),encoding='utf-8-sig')
 if len(reserved)<10:
  desktop=Path(os.environ.get('USERPROFILE',str(root)))/'Desktop'
  if not desktop.is_dir():desktop=root/'logs'
  archive=desktop/('IG-material-scan-20261127-'+uuid.uuid4().hex[:8]+'.zip')
  with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:z.write(scan,scan.name);z.write(text,text.name)
  raise ValueError('扫描后可分配素材不足10条（当前 '+str(len(eligible))+' 条），正式目录未复制，未启动发布。'+summary+'。扫描报告：'+str(archive))
 return [(a,*reserved[a][:2]) for a in c.MAPPING],report

def validate(root,path):
 value=c.checked(c.safe(root,path));p=value['payload'];jobs=p.get('jobs',[])
 if p.get('schema')!='ig-ten-material-v1' or p.get('date')!=c.DAY or p.get('authorization')!=c.AUTH or p.get('ai_label') is not False or p.get('real_footage_confirmed') is not True or p.get('caption')!=c.CAPTION or p.get('comment')!=c.COMMENT or [j['account'] for j in jobs]!=list(c.MAPPING):raise ValueError('不是本次27号10账号原素材/原文案授权')
 for j in jobs:
  if j['username']!=c.MAPPING[j['account']]:raise ValueError('分配的账号对应关系不符')
  expected=c.digest(dict(platform='instagram',account=j['account'],username=j['username'],video_sha256=j['video_sha256'],caption=c.CAPTION))
  if j['key']!=expected or not re.fullmatch('[a-f0-9]{64}',j['video_sha256']):raise ValueError('IG视频任务键不符')
  for f,folder in [('video','inbox'),('published_video','published')]:
   file=c.safe(root,root/j[f])
   if file.parent!=root/'videos'/j['account']/folder or file.suffix.lower() not in c.EXT:raise ValueError('IG分配视频目录不符')
 return value

def allocate(root,source=None):
 root=c.workspace(root)
 with c.lock(root,'allocation'):
  pointer=c.safe(root,root/POINTER);saved=c.read(pointer,{})
  if saved:
   path=c.safe(root,root/saved['manifest']);value=validate(root,path)
   if value['sha256']!=saved.get('sha256'):raise ValueError('原IG分配指针异常')
   if source is not None and str(Path(source).resolve())!=value['payload']['source']:raise ValueError('本批已有分配，不换源或重排')
  else:
   if c.today()!=c.DAY:raise ValueError('新分配只用于11月27日，既有批次可按原清单续跑')
   source=source_folder(root,source or choose());token=hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]
   path=c.safe(root,root/'material-staging'/c.DAY/(token+'-ins10')/'manifest.json')
   if path.exists():
    value=validate(root,path)
   else:
    choices,scan=scan_source(root,source);selected=[]
    for a,file,info in choices:
     u=c.MAPPING[a];name=c.DAY.replace('-','')+'-'+token[:8]+'-'+a+'-'+file.name
     key=c.digest(dict(platform='instagram',account=a,username=u,video_sha256=info['sha256'],caption=c.CAPTION))
     selected.append(dict(account=a,username=u,key=key,source_video=str(file),source_name=file.name,video='videos/'+a+'/inbox/'+name,published_video='videos/'+a+'/published/'+name,video_sha256=info['sha256'],video_size=info['size']))
    p=dict(schema='ig-ten-material-v1',date=c.DAY,source=str(source),source_id=token,authorization=c.AUTH,ai_label=False,real_footage_confirmed=True,caption=c.CAPTION,comment=c.COMMENT,fb_content_revision=c.FB_CONTENT_SHA,jobs=selected,copy_mode='retain-source',created_at=c.stamp())
    value=dict(payload=p,sha256=c.digest(p));c.save(path,value)
   c.save(pointer,dict(manifest=str(path.relative_to(root)),sha256=value['sha256'],complete=False))
  ledger=c.state(root)
  required=sum(j['video_size'] for j in value['payload']['jobs'] if not c.submission(ledger.get(j['key'],{})) and not (root/j['video']).exists())
  if shutil.disk_usage(root).free<required+64*1024**2:raise ValueError('IG目录磁盘空间不足，原件与计划保留')
  for j in value['payload']['jobs']:
   row=ledger.get(j['key'],{});dest=c.safe(root,root/j['video']);archive=c.safe(root,root/j['published_video'])
   if not c.submission(row):
    if archive.exists():raise ValueError('本视频已在published目录但账本未证明状态，保留待核实')
    c.copy_exact(Path(j['source_video']),dest,dict(size=j['video_size'],sha256=j['video_sha256']))
   print('已分配：'+j['account']+' / '+j['username']+' <- '+j['source_name'],flush=True)
  c.save(pointer,dict(manifest=str(path.relative_to(root)),sha256=value['sha256'],complete=True))
  c.save(root/'logs/ig-allocation-20261127.json',dict(batch_sha256=value['sha256'],jobs=value['payload']['jobs'],complete=True,publication_started=False))
  print('Instagram分配完成：10个账号各1条；原素材保留。',flush=True)
  return path,value
