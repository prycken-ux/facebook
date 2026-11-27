"""Allocate ten independent IG clips while retaining every source original."""
import hashlib,re,shutil,time
from pathlib import Path
import ig10_common_20261127 as c
POINTER='material-staging/ig10-20261127-pending.json'

def natural(value):return tuple((0,int(p)) if p.isdecimal() else (1,p.casefold()) for p in re.split('(\\d+)',value))
def choose():
 import subprocess
 code=r'''Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$d=New-Object Windows.Forms.FolderBrowserDialog;$d.Description='Choose TODAY Instagram video folder (10 separate videos)';$d.ShowNewFolderButton=$false
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

def previous_hashes(root):
 hashes=set()
 for p in (root/'material-staging').glob('*/*/manifest.json'):
  value=c.checked(c.safe(root,p));hashes.update(j['video_sha256'] for j in value['payload']['jobs'])
 # Only immutable FB distribution fingerprints, never its accounts/credentials/state.
 fb=root.parent/'FB-AutoUpload'
 for p in (fb/'logs/material-distribution').glob('*/*.json'):
  if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:-eligible\d+|-reserved50)?\.json',p.name):continue
  value=c.checked(c.safe(fb,p))
  for row in value['payload'].get('assignments',[]):
   hashes.update(f['sha256'] for f in row.get('files',[]) if Path(f.get('name','')).suffix.lower() in c.EXT)
 return hashes

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
    used=previous_hashes(root);selected=[];seen=set();infos={};grouped=any((source/a).is_dir() for a in c.MAPPING);pool=[]
    if grouped and not all((source/a).is_dir() for a in c.MAPPING):raise ValueError('素材编号分组不完整，需要ins01～ins10各一组')
    if not grouped:pool=sorted(source.iterdir(),key=lambda p:(natural(p.name),p.name))
    for a,u in c.MAPPING.items():
     group=(source/a/'inbox') if grouped and (source/a/'inbox').is_dir() else source/a
     files=sorted(group.iterdir(),key=lambda p:(natural(p.name),p.name)) if grouped else pool
     chosen=None
     for file in files:
      if not file.is_file() or file.suffix.lower() not in c.EXT:continue
      if file not in infos:infos[file]=c.file_info(file)
      info=infos[file]
      if info['sha256'] in used or info['sha256'] in seen:continue
      chosen=(file,info);break
     if chosen is None:raise ValueError('IG新素材不足10条，或编号'+a+'没有未分配视频；正式目录未复制')
     file,info=chosen;seen.add(info['sha256']);name=c.DAY.replace('-','')+'-'+token[:8]+'-'+a+'-'+file.name
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
