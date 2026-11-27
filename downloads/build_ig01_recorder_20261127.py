"""Immutable demo-only capsule. Publishing entry is never invoked."""
import base64,hashlib,json,zlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
NAMES=['ig10_common_20261127.py','ig10_allocate_20261127.py','ig10_browser_20261127.py','ig10_engine_20261127.py','ig10_profile_release.ps1','ig_state_io.py','ig_windows_job.py','record_ig01_demo_20261127.py']
TEMPLATE='''import base64,hashlib,importlib,os,sys,uuid,zlib
from pathlib import Path
FILES=__FILES__
FINGERPRINT=__FP__
def unpack(root):
 cache=root/'tools'/('ig-demo-'+FINGERPRINT[:16])
 for p in (cache,*cache.parents):
  if (p.exists() or p.is_symlink()) and (p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400)):raise ValueError('Linked recorder cache preserved')
 cache.mkdir(parents=True,exist_ok=True)
 for name,item in FILES.items():
  raw=zlib.decompress(base64.b85decode(item['data']));p=cache/name
  if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Embedded recorder checksum mismatch')
  if p.exists():
   if p.is_symlink() or p.read_bytes()!=raw:raise ValueError('Recorder cache changed; preserved')
  else:
   tmp=cache/(name+'.'+uuid.uuid4().hex+'.tmp')
   try:tmp.write_bytes(raw);tmp.replace(p)
   finally:tmp.unlink(missing_ok=True)
 return cache
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
 try:
  root=Path(sys.argv[1]).absolute()
  if root.name.casefold()!='ig-autoupload' or not root.is_dir():raise ValueError('Use the existing E:\\\\IG-AutoUpload workspace')
  cache=unpack(root);sys.path.insert(0,str(cache));importlib.invalidate_caches()
  from record_ig01_demo_20261127 import run
  raise SystemExit(run(root))
 except KeyboardInterrupt:print('Recording interrupted; inspect logs/demo-recordings for captured steps.');raise SystemExit(2)
 except Exception as error:print('STOP: '+str(error),flush=True);raise SystemExit(1)
'''
def build():
 files={n:dict(sha256=hashlib.sha256((HERE/n).read_bytes()).hexdigest(),data=base64.b85encode(zlib.compress((HERE/n).read_bytes(),9)).decode()) for n in NAMES};fp=hashlib.sha256(json.dumps({k:v['sha256'] for k,v in files.items()},sort_keys=True,separators=(',',':')).encode()).hexdigest();text=TEMPLATE.replace('__FILES__',repr(files)).replace('__FP__',repr(fp));path=HERE/'start_ig01_demo_record_20261127.py';path.write_text(text,encoding='utf-8');compile(text,str(path),'exec');assert path.stat().st_size<=131072;print('Recorder capsule',path.stat().st_size,'bytes; fingerprint',fp,'; SHA256',hashlib.sha256(path.read_bytes()).hexdigest());return path
if __name__=='__main__':build()
