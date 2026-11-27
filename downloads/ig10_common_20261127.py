"""IG-only state, identity mappings and immutable Nov27 batch contracts."""
import contextlib,hashlib,json,os,re,tempfile,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
import ig_state_io
DAY='2026-11-27';BJ=timezone(timedelta(hours=8));VIDEO_SECONDS=180;COMMENT_SECONDS=180
USERS=('ted47868','jenniferriffin45','ha.rper9090','ivy800550','sophia5095091','daisybreeze8838','ethan400560','dylan159851','zachary29692','alixla2762')
MAPPING={f'ins{i:02d}':u for i,u in enumerate(USERS,1)}
CAPTION='If this book speaks to you, you can find the same one from the video here.Get your copy here:https://www.amazon.com/gp/product/B0GYJ55PH6?maas=maas_adg_2C08551FB464224E2CDB58F74A72570A_afap_abs&ref_=aa_maas&tag=maas Shop on shopify: https://prycken.com/'
COMMENT='Get your own copy here:https://www.amazon.com/gp/product/B0GYJ55PH6?maas=maas_adg_B2F4D52E550EDAC7E6A92C0290F501F6_afap_abs&ref_=aa_maas&tag=maas'
FB_CONTENT_SHA='ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894'
AUTH='user-authorized-ig10-original-fb-caption-comment-real-off-20261127-v1'
EXT={'.mp4','.mov','.m4v'}

def stamp():return datetime.now(timezone.utc).isoformat()
def today():return datetime.now(timezone.utc).astimezone(BJ).date().isoformat()
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def norm(s):return re.sub(r'\s+',' ',str(s).replace('\xa0',' ')).strip()
def linked(p):return p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400)
def safe(root,path):
 root=Path(root).absolute();path=Path(path).absolute();path.relative_to(root)
 for p in (path,*path.parents):
  if (p.exists() or p.is_symlink()) and linked(p):raise ValueError('路径包含链接，保留：'+str(path))
 path.resolve().relative_to(root.resolve())
 return path

def read(path,default=None,required=False):return ig_state_io.read(path,default,required=required,max_bytes=32_000_000)
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 if path.is_symlink():raise ValueError('状态文件是链接，未覆盖')
 with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as h:
  temporary=Path(h.name);h.write((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode());h.flush();os.fsync(h.fileno())
 try:
  for i in range(80):
   try:temporary.replace(path);break
   except PermissionError:
    if i==79:raise
    time.sleep(.025)
 finally:temporary.unlink(missing_ok=True)

def file_info(p):
 p=Path(p)
 for part in (p,*p.parents):
  if (part.exists() or part.is_symlink()) and linked(part):raise ValueError('素材路径是链接')
 before=p.stat()
 if not p.is_file() or before.st_nlink!=1:raise ValueError('素材不是普通单链接文件')
 h=hashlib.sha256()
 with p.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
 after=p.stat()
 if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('素材仍在变化，请复制完成后再运行')
 if not after.st_size:raise ValueError('视频为空')
 return dict(size=after.st_size,sha256=h.hexdigest())

def copy_exact(source,destination,info):
 if destination.exists():
  if file_info(destination)!=info:raise ValueError('已有目标文件内容不同，未覆盖：'+str(destination))
  return
 if file_info(source)!=info:raise ValueError('原视频内容变化')
 destination.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as h:
  temp=Path(h.name)
  with Path(source).open('rb') as inp:
   for part in iter(lambda:inp.read(1024*1024),b''):h.write(part)
  h.flush();os.fsync(h.fileno())
 try:
  if file_info(temp)!=info:raise ValueError('复制指纹核验失败')
  if destination.exists():raise ValueError('复制中出现另一个目标文件，未覆盖')
  temp.replace(destination)
 finally:temp.unlink(missing_ok=True)

@contextlib.contextmanager
def lock(root,label='publisher'):
 if os.name!='nt':
  import fcntl
  path=root/'logs'/('ig-'+label+'.lock');path.parent.mkdir(exist_ok=True)
  with path.open('a+b') as h:
   try:fcntl.flock(h.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
   except OSError:raise RuntimeError('已有IG任务在运行，未重复启动')
   try:yield
   finally:fcntl.flock(h.fileno(),fcntl.LOCK_UN)
  return
 import ctypes
 k=ctypes.WinDLL('kernel32',use_last_error=True);ptr=ctypes.c_void_p;u32=ctypes.c_uint32
 k.CreateMutexW.argtypes=[ptr,ctypes.c_int,ctypes.c_wchar_p];k.CreateMutexW.restype=ptr
 k.WaitForSingleObject.argtypes=[ptr,u32];k.WaitForSingleObject.restype=u32;k.ReleaseMutex.argtypes=[ptr];k.CloseHandle.argtypes=[ptr]
 h=k.CreateMutexW(None,False,'Local\\IG10-'+label+'-'+hashlib.sha256(str(root).casefold().encode()).hexdigest()[:24]);owned=False
 if not h:raise ctypes.WinError(ctypes.get_last_error())
 try:
  if k.WaitForSingleObject(h,0) not in {0,0x80}:raise RuntimeError('已有IG任务运行，未重复启动')
  owned=True;yield
 finally:
  if owned:k.ReleaseMutex(h)
  k.CloseHandle(h)

def workspace(root):
 root=safe(Path(root).absolute(),Path(root).absolute()).resolve()
 if root.name.casefold()!='ig-autoupload' or (root/'upload_config.json').exists():raise ValueError('仅允许原E盘IG-AutoUpload工作区')
 owner=read(safe(root,root/'workspace-owner.json'),required=True);cfg=read(safe(root,root/'instagram_accounts.json'),required=True)
 if owner.get('schema')!='instagram-browser-workspace-v1' or owner.get('root')!=str(root) or owner.get('accounts')!=list(MAPPING):raise ValueError('IG工作区所有权/编号不符')
 rows=cfg.get('accounts',[])
 if cfg.get('schema')!='instagram-browser-accounts-v1' or cfg.get('root')!=str(root) or len(rows)!=10 or {r.get('account') for r in rows}!=set(MAPPING):raise ValueError('IG账号配置不完整')
 for row in rows:
  a=row['account'];u=MAPPING[a]
  if row.get('expected_username')!=u or row.get('profile_url')!='https://www.instagram.com/'+u+'/':raise ValueError('IG编号对应关系已变化，未猜选账号：'+a)
  for field in ['profile_dir','inbox','published','review','failed']:
   expected='profiles/'+a if field=='profile_dir' else 'videos/'+a+'/'+field
   if row.get(field)!=expected or not safe(root,root/expected).is_dir():raise ValueError('IG资料/视频目录不符：'+a+'/'+field)
 for name,text in [('common_caption.txt',CAPTION),('common_comment.txt',COMMENT)]:
  if safe(root,root/name).read_text(encoding='utf-8-sig').strip()!=text:raise ValueError('原FB正文/首评版本已变化，未覆盖或自行改写：'+name)
 (root/'logs').mkdir(exist_ok=True)
 return root

def checked(path):
 value=read(path,required=True)
 if value.get('sha256')!=digest(value.get('payload',{})):raise ValueError('IG清单指纹异常')
 return value

def submission(row):return bool(row.get('post_intent_at') or row.get('submit_click_returned_at') or row.get('permalink') or row.get('video_status') in {'published','needs_review','posting'})
def state(root):
 path=safe(root,root/'logs/ig-publication-state.json');marker=safe(root,root/'logs/ig-ledger-created.json')
 if not path.exists():
  if marker.exists():raise ValueError('IG原发布账本缺失，未当作全部未开始')
  save(path,{})
  save(marker,dict(schema='ig-ledger-created-v1',created_at=stamp()))
 value=read(path,required=True)
 if not isinstance(value,dict):raise ValueError('IG账本格式异常')
 return value

def update(root,key,**fields):
 current=state(root);row=current.setdefault(key,{})
 for k in ('account','username','video_sha256'):
  if k in fields and k in row and row[k]!=fields[k]:raise ValueError('任务身份绑定变化')
 row.update(fields,updated_at=stamp());save(root/'logs/ig-publication-state.json',current);return row

def canonical(url):
 from urllib.parse import urlparse
 if not isinstance(url,str):return None
 try:p=urlparse(url)
 except ValueError:return None
 m=re.fullmatch(r'/(p|reel)/([A-Za-z0-9_-]{5,32})/?',p.path)
 return 'https://www.instagram.com/'+m[1]+'/'+m[2]+'/' if p.scheme=='https' and p.hostname in {'instagram.com','www.instagram.com'} and m else None

def shortcode(url):
 u=canonical(url);return u.rstrip('/').split('/')[-1] if u else None
