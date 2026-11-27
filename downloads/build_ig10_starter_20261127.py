"""Reproducible self-contained, immutable IG-only Windows starter capsule."""
import base64,hashlib,json,zlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
NAMES=['ig10_common_20261127.py','ig10_allocate_20261127.py','ig10_browser_20261127.py','ig10_engine_20261127.py','ig10_profile_release.ps1','ig_state_io.py','ig_windows_job.py']
TEMPLATE='''"""Nov27 Instagram10: runtime folder choice, exact accounts, ins01 publication/comment trial."""
import base64,hashlib,importlib,json,os,subprocess,sys,time,uuid,zlib
from pathlib import Path
FILES=__FILES__
FINGERPRINT=__FP__

def unpack(root):
 cache=root/'tools'/('ig10-'+FINGERPRINT[:16])
 for p in (cache,*cache.parents):
  if (p.exists() or p.is_symlink()) and (p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400)):raise ValueError('Linked tool cache preserved')
 cache.mkdir(parents=True,exist_ok=True)
 for name,entry in FILES.items():
  path=cache/name;raw=zlib.decompress(base64.b85decode(entry['data']))
  if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Embedded IG tool checksum mismatch: '+name)
  if path.exists():
   if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Existing IG cache checksum mismatch; kept files: '+str(path))
  else:
   temp=cache/(name+'.'+uuid.uuid4().hex+'.tmp')
   try:
    temp.write_bytes(raw)
    if path.exists():
     if path.read_bytes()!=raw:raise ValueError('Concurrent IG cache conflict')
    else:temp.replace(path)
   finally:temp.unlink(missing_ok=True)
 return cache

def viewer(root):
 log=str(root/'logs/ig-2026-11-27-run.log').replace("'","''")
 code="[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false); $Host.UI.RawUI.WindowTitle='IG 11-27 publication progress'; Get-Content -LiteralPath '"+log+"' -Encoding UTF8 -Tail 15 -Wait"
 encoded=base64.b64encode(code.encode('utf-16le')).decode()
 try:subprocess.Popen(['powershell.exe','-NoProfile','-NoExit','-EncodedCommand',encoded],creationflags=0x00000010)
 except OSError as e:print('Live log window could not open; read the run log: '+str(e),flush=True)

def main(root):
 if root.name.casefold()!='ig-autoupload' or not root.is_dir():raise ValueError('Use the existing E:\\\\IG-AutoUpload workspace')
 for p in (root,*root.parents):
  if p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400):raise ValueError('Linked IG workspace preserved')
 cache=unpack(root);sys.path.insert(0,str(cache));importlib.invalidate_caches()
 import ig10_common_20261127 as c
 import ig10_allocate_20261127 as allocate
 from playwright.sync_api import sync_playwright
 c.workspace(root)
 if os.environ.get('IG10_PROBE_ONLY')=='1':print('IG10 VERIFIED: exact10 mappings; original caption/comment; real footage; AI OFF; 180s; no browser opened.');return 0
 if os.name!='nt':raise ValueError('The publication entry runs on the original Windows computer')
 # An already running publisher owns the immutable batch. Never create another uploader.
 try:
  with c.lock(root,'publisher'):pass
 except RuntimeError:
  print('Existing IG publisher retained. Opening its progress log.',flush=True);viewer(root);return 0
 print('IG分配修复版：请选择素材总文件夹；会扫描子目录，统一分配10条，保留原件。',flush=True)
 path,batch=allocate.allocate(root)
 run=uuid.uuid4().hex;ack=root/'logs'/('ig-launch-'+run+'.json');launch=root/'logs'/('ig-launch-'+run+'.log')
 env=dict(os.environ,IG10_ROLE='coordinator',IG10_BATCH=str(path),IG10_RUN=run,PYTHONIOENCODING='utf-8');env.pop('IG10_KEY',None);env.pop('IG10_STARTED',None)
 with launch.open('ab') as out:
  child=subprocess.Popen([sys.executable,'-u',str(cache/'ig10_engine_20261127.py'),str(root)],env=env,cwd=str(root),stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,creationflags=0x08000000)
 until=time.monotonic()+20
 while time.monotonic()<until:
  if ack.exists():
   state=c.read(ack,required=True)
   if state.get('phase') in {'started','already_running'}:
    print('IG background monitor acknowledged. Trial ins01 video and refreshed own comment first; other nine follow only after proof.',flush=True)
    print('State: '+str(root/'logs/ig-2026-11-27-status.json'),flush=True);print('Log: '+str(root/'logs/ig-2026-11-27-run.log'),flush=True);viewer(root);return 0
   raise RuntimeError('IG monitor failed: '+state.get('message','')+'; '+str(launch))
  if child.poll() is not None:raise RuntimeError('IG monitor exited before acknowledgement; '+str(launch)+'; '+launch.read_text(encoding='utf-8-sig',errors='replace')[-2000:])
  time.sleep(.2)
 # Do not kill a monitor whose acknowledgement is delayed and do not start a second one.
 raise RuntimeError('IG monitor acknowledgement delayed; no duplicate launch. Inspect '+str(launch))

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
 try:raise SystemExit(main(Path(sys.argv[1]).absolute()))
 except KeyboardInterrupt:print('Folder selection cancelled; no new publication started.',flush=True);raise SystemExit(2)
 except Exception as error:print('STOP: '+str(error),flush=True);raise SystemExit(1)
'''
def build():
 files={name:dict(sha256=hashlib.sha256((HERE/name).read_bytes()).hexdigest(),data=base64.b85encode(zlib.compress((HERE/name).read_bytes(),9)).decode()) for name in NAMES}
 fp=hashlib.sha256(json.dumps({name:entry['sha256'] for name,entry in files.items()},sort_keys=True,separators=(',',':')).encode()).hexdigest()
 text=TEMPLATE.replace('__FILES__',repr(files)).replace('__FP__',repr(fp));p=HERE/'start_ig10_publish_20261127.py';p.write_text(text,encoding='utf-8');compile(text,str(p),'exec');assert p.stat().st_size<=131072
 print('Capsule',p.stat().st_size,'bytes; fingerprint',fp,'; SHA256',hashlib.sha256(p.read_bytes()).hexdigest())
 return p
if __name__=='__main__':build()
