"""Visible, single-account IG demonstration recorder; never invokes publication."""
import collections,ctypes,hashlib,json,os,re,socket,subprocess,sys,time,urllib.request,uuid,zipfile
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import ig10_common_20261127 as c
import ig10_allocate_20261127 as allocation
import ig10_engine_20261127 as engine
import ig10_browser_20261127 as ui
MAX_SECONDS=1200
PROTECTED=['ig-publication-state.json','ig-comment-state.json','ig-first-trial-20261127.json']

HOOK=r'''(() => {
 if(window.__igDemoInstalled)return;window.__igDemoInstalled=true;
 const clean=s=>(s||'').replace(/\s+/g,' ').trim().slice(0,160);
 const badPage=()=>!/^(www\.)?instagram\.com$/.test(location.hostname)||/\/accounts\/login|\/challenge|\/checkpoint|\/two_factor/.test(location.pathname)||!!document.querySelector('input[type="password"]');
 const emit=data=>{if(badPage())return;Promise.resolve(window.__igDemoEvent(data)).catch(()=>{});};
 const describe=e=>({tag:e.tagName,role:e.getAttribute('role'),label:clean(e.getAttribute('aria-label')),placeholder:clean(e.getAttribute('placeholder')),type:e.getAttribute('type'),checked:e.getAttribute('aria-checked')||(e.type==='checkbox'?e.checked:null),expanded:e.getAttribute('aria-expanded'),text:/^(INPUT|TEXTAREA)$/.test(e.tagName)||e.isContentEditable?'':clean(e.innerText),svg_labels:Array.from(e.querySelectorAll('svg[aria-label]')).slice(0,3).map(x=>clean(x.getAttribute('aria-label')))});
 const target=e=>e.target instanceof Element?e.target.closest('button,a,[role="button"],[role="link"],[role="switch"],[role="checkbox"],[role="combobox"],select,input,textarea,[contenteditable="true"]')||e.target.closest('svg')||e.target:null;
 const finalAction=e=>{const words=[e.innerText,e.getAttribute('aria-label'),...Array.from(e.querySelectorAll('svg[aria-label]')).map(x=>x.getAttribute('aria-label'))].map(clean);const isMenu=!!e.closest('[role="menu"],[role="menuitem"]');return words.some(x=>/^(Share(?: post| reel)?|分享|共享|分享视频|分享帖子|发布|發佈|Publish(?: post| reel)?)$/i.test(x)||(!isMenu&&/^(Post|发送|Send|張貼)$/i.test(x)));};
 window.addEventListener('click',event=>{
  const e=target(event);if(!e||e.closest('#ig-demo-panel'))return;
  if(finalAction(e)){event.preventDefault();event.stopImmediatePropagation();emit({kind:'blocked_publish',target:describe(e)});return;}
  emit({kind:'click',target:describe(e)});
 },true);
 window.addEventListener('submit',event=>{if(badPage())return;event.preventDefault();event.stopImmediatePropagation();emit({kind:'blocked_submit'});},true);
 window.addEventListener('change',event=>{const e=target(event);if(!e)return;const data={kind:'change',target:describe(e)};if(e.type==='file')data.files=Array.from(e.files||[]).map(f=>({name:f.name,size:f.size,type:f.type}));emit(data);},true);
 let last=0;window.addEventListener('input',event=>{const e=target(event);if(!e||e.type==='password'||Date.now()-last<1000)return;last=Date.now();emit({kind:'field_edit',target:describe(e)});},true);
 const panel=()=>{if(!document.body||document.getElementById('ig-demo-panel')||badPage())return;const el=document.createElement('div');el.id='ig-demo-panel';el.style.cssText='position:fixed;right:14px;bottom:85px;z-index:2147483647;background:#202534;color:white;border:1px solid #89a2ff;border-radius:8px;padding:12px;font:14px sans-serif;max-width:290px;box-shadow:0 2px 12px #444';const text=document.createElement('div');text.id='ig-demo-note';text.textContent='IG操作录制中：请演示到分享前。分享/发布会被拦截。';const stop=document.createElement('button');stop.textContent='结束记录并打包';stop.style.cssText='margin-top:8px;padding:7px 12px;cursor:pointer';stop.onclick=event=>{event.preventDefault();event.stopPropagation();text.textContent='正在打包。完成后请取消编辑并关闭本账号窗口。';stop.disabled=true;emit({kind:'finish'});};el.append(text,stop);document.body.append(el);};
 window.addEventListener('DOMContentLoaded',panel);setInterval(panel,700);panel();
})();'''
CONTROLS=r'''() => {const dialogs=Array.from(document.querySelectorAll('[role="dialog"]')).filter(e=>e.getClientRects().length);const scope=dialogs.length?dialogs[dialogs.length-1]:document;return Array.from(scope.querySelectorAll('button,a,[role="button"],[role="link"],[role="switch"],[role="checkbox"],[role="combobox"],select,input,textarea,[contenteditable="true"],svg[aria-label]')).filter(e=>!e.closest('#ig-demo-panel')&&e.getClientRects().length).slice(0,250).map(e=>{const r=e.getBoundingClientRect();const text=/^(INPUT|TEXTAREA)$/.test(e.tagName)||e.isContentEditable?'':(e.innerText||'').replace(/\s+/g,' ').trim().slice(0,140);return {tag:e.tagName,role:e.getAttribute('role'),label:e.getAttribute('aria-label'),placeholder:e.getAttribute('placeholder'),type:e.getAttribute('type'),accept:e.type==='file'?e.accept:null,text,checked:e.getAttribute('aria-checked')||(e.type==='checkbox'?e.checked:null),expanded:e.getAttribute('aria-expanded'),svg_labels:Array.from(e.querySelectorAll('svg[aria-label]')).slice(0,3).map(x=>x.getAttribute('aria-label')),bounds:{x:Math.round(r.x),y:Math.round(r.y),width:Math.round(r.width),height:Math.round(r.height)}};});}'''

def safe_url(url):
 p=urlparse(url)
 if p.scheme!='https' or p.hostname not in {'instagram.com','www.instagram.com'} or p.username or p.password or p.port:raise ValueError('只记录本账号Instagram页面')
 if re.search('/accounts/login|/challenge|/checkpoint|/two_factor',p.path,re.I):raise ValueError('登录或安全验证页暂停记录')
 return 'https://www.instagram.com'+p.path

def clean_event(data):
 if not isinstance(data,dict) or data.get('kind') not in {'click','change','field_edit','blocked_publish','blocked_submit','finish'}:return None
 out={'kind':data['kind']};target=data.get('target')
 if isinstance(target,dict):
  if target.get('type')=='password':return None
  out['target']={k:str(target[k])[:160] if target[k] is not None else None for k in ['tag','role','label','placeholder','type','text','checked','expanded'] if k in target}
  out['target']['svg_labels']=[str(x)[:100] for x in target.get('svg_labels',[])[:3]]
 if data.get('kind')=='change' and isinstance(data.get('files'),list):
  out['files']=[dict(name=str(f.get('name','')).replace(chr(92),'/').split('/')[-1][:180],size=f.get('size') if isinstance(f.get('size'),int) else None,type=str(f.get('type',''))[:80]) for f in data['files'][:3] if isinstance(f,dict)]
 return out

def blocked_request(method,url,body=''):
 if method.upper() in {'GET','HEAD','OPTIONS'}:return False
 p=urlparse(url)
 if p.hostname not in {'instagram.com','www.instagram.com'}:return False
 if re.search(r'/api/v1/(media/|web/comments/|direct_v2/|friendships/)',p.path):return True
 if 'graphql' in p.path:
  values=parse_qs(body or '');name=' '.join(values.get('fb_api_req_friendly_name',[])+values.get('operationName',[]))
  if not name:
   try:name=str(json.loads(body or '{}').get('operationName',''))
   except (ValueError,AttributeError):pass
  if re.search(r'mutation|publish|configure|create.*media|comment.*create',name,re.I):return True
 return False

def known_desktop():
 if os.name!='nt':return None
 buf=ctypes.create_unicode_buffer(260);shell=ctypes.WinDLL('shell32',use_last_error=True);f=shell.SHGetFolderPathW;f.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_wchar_p];f.restype=ctypes.c_long
 return Path(buf.value) if f(None,0x10,None,0,buf)==0 and buf.value else None

def desktop(root):
 try:found=known_desktop()
 except (OSError,AttributeError):found=None
 if found is not None and found.is_dir():return found
 candidate=Path(os.environ.get('USERPROFILE',str(root)))/'Desktop'
 return candidate if candidate.is_dir() else root/'logs'

def fingerprints(root):
 return {n:hashlib.sha256((root/'logs'/n).read_bytes()).hexdigest() if (root/'logs'/n).exists() else None for n in PROTECTED}

def assigned(root):
 pointer=c.read(root/allocation.POINTER,required=True)
 if not pointer.get('complete'):raise RuntimeError('本批原素材分配尚未完成，录制工具不重新分配')
 batch=allocation.validate(root,c.safe(root,root/pointer['manifest']))
 if pointer.get('sha256')!=batch['sha256']:raise ValueError('原IG分配指纹不符')
 job=batch['payload']['jobs'][0]
 if job['account']!='ins01' or job['username']!='ted47868':raise ValueError('录制只针对原ins01/ted47868')
 return batch,job

def visible_args(root,job,port):
 args=[v for v in engine.browser_args(root,job,port) if not v.startswith('--headless')]
 return args[:-1]+['--new-window','about:blank']

def launch(pw,root,job):
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 endpoint='http://127.0.0.1:'+str(port)
 proc=subprocess.Popen(visible_args(root,job,port),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000 if os.name=='nt' else 0)
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));until=time.monotonic()+30
 while time.monotonic()<until:
  try:
   with opener.open(endpoint+'/json/version',timeout=1) as r:info=json.load(r)
   if str(info.get('webSocketDebuggerUrl','')).startswith('ws://127.0.0.1:'):break
  except (OSError,ValueError):pass
  if proc.poll() not in {None,0}:raise RuntimeError('录制浏览器启动失败')
  time.sleep(.2)
 else:raise RuntimeError('录制浏览器30秒内未就绪，未自动执行发布')
 browser=pw.chromium.connect_over_cdp(endpoint,timeout=15000);context=browser.contexts[0];page=context.pages[0] if context.pages else context.new_page();page.set_default_timeout(5000)
 return browser,context,page

class Recorder:
 def __init__(self,root,job,batch):
  self.root=root;self.job=job;self.batch=batch;self.id=uuid.uuid4().hex;self.folder=c.safe(root,root/'logs/demo-recordings'/self.id);self.folder.mkdir(parents=True)
  self.events=[];self.frames=[];self.pending=collections.deque();self.active=False;self.ended=False;self.due=None;self.start=time.monotonic();self.page=None;self.before=fingerprints(root);self.warnings=[]
 def event(self,source,data):
  if not self.active or self.ended or source.get('page') is not self.page or source.get('frame') is not self.page.main_frame:return
  try:safe_url(self.page.url)
  except ValueError:return
  data=clean_event(data)
  if data is None:return
  self.pending.append(dict(data,at=c.stamp(),elapsed_seconds=round(time.monotonic()-self.start,2)))
 def route(self,route):
  r=route.request
  body=''
  if 'graphql' in urlparse(r.url).path and r.method.upper() not in {'GET','HEAD','OPTIONS'}:
   try:body=r.post_data or ''
   except (UnicodeError,ValueError):body=''
  if blocked_request(r.method,r.url,body):
   self.pending.append(dict(kind='blocked_network_publish',path=urlparse(r.url).path,at=c.stamp()));route.abort('blockedbyclient')
  else:route.continue_()
 def install(self,context,page):
  self.page=page;context.expose_binding('__igDemoEvent',self.event);context.add_init_script(HOOK);context.route('**/*',self.route)
 def capture(self,label):
  if len(self.frames)>=80:return
  url=safe_url(self.page.url)
  if ui.visible(self.page.locator('input[type="password"]')) is not None:raise ValueError('登录页不记录截图或输入')
  names=self.page.evaluate(ui.OWN_PROFILE_NAV)
  if names and names!=[self.job['username']]:raise ValueError('当前账号导航与ins01不符，暂停记录')
  n=len(self.frames)+1;name=f'{n:03d}-{label}';controls=self.page.evaluate(CONTROLS)
  c.save(self.folder/(name+'.json'),dict(url=url,at=c.stamp(),controls=controls));self.page.screenshot(path=str(self.folder/(name+'.png')),timeout=5000)
  self.frames.append(dict(step=n,label=label,url=url,controls=name+'.json',screenshot=name+'.png',at=c.stamp()))
 def drain(self):
  finish=False
  while self.pending:
   event=self.pending.popleft()
   if len(self.events)<800:self.events.append(event)
   if event['kind']=='finish':finish=True
   else:self.due=time.monotonic()+.35
  return finish
 def export(self,reason):
  if not self.ended:self.drain()
  self.ended=True;self.active=False;after=fingerprints(self.root)
  value=dict(schema='ig01-manual-demo-v1',account='ins01',username=self.job['username'],batch_sha256=self.batch['sha256'],assigned_video=self.job['video'],video_sha256=self.job['video_sha256'],recording_id=self.id,reason=reason,at=c.stamp(),events=self.events,frames=self.frames,warnings=self.warnings,ledger_before=self.before,ledger_after=after,publication_ledgers_unchanged=after==self.before,automatic_publication_invoked=False)
  c.save(self.folder/'recording.json',value)
  text=['IG ins01人工演示记录','账号：'+self.job['username'],'原分配视频：'+self.job['video'],'结束原因：'+reason,'发布/评论账本保持：'+str(after==self.before),'操作记录 '+str(len(self.events))+'；截图 '+str(len(self.frames)),'本工具拦截最终分享；没有调用自动发布入口。']
  text += [str(i+1)+'. '+x['kind']+' '+str(x.get('target',{}).get('label') or x.get('target',{}).get('text') or x.get('path','')) for i,x in enumerate(self.events)]
  (self.folder/'步骤说明.txt').write_text('\n'.join(text),encoding='utf-8-sig')
  path=desktop(self.root)/('IG-demo-record-20261127-'+self.id[:8]+'.zip')
  with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as z:
   for p in sorted(self.folder.iterdir()):
    if p.is_file() and p.suffix.lower() in {'.json','.txt','.png'} and not p.is_symlink():z.write(p,p.name)
  print('记录包已保存：'+str(path),flush=True);print('请上传这个zip。请取消编辑/舍弃演示草稿并关闭ins01窗口；浏览器关闭后工具退出。',flush=True)
  return path

def run(root):
 from playwright.sync_api import sync_playwright
 root=c.workspace(root);batch,job=assigned(root)
 if os.environ.get('IG_DEMO_PROBE_ONLY')=='1':print('IG DEMO VERIFIED: ins01/ted47868; record only; no automatic publication; original ledgers preserved.');return 0
 with c.lock(root,'publisher'),c.lock(root,'manual-recorder'):
  recorder=Recorder(root,job,batch)
  try:
   engine.release_profile(root,job,'record-'+recorder.id,time.monotonic(),lambda *a,**k:print(a[1],flush=True))
   with sync_playwright() as pw:
    browser,context,page=launch(pw,root,job);recorder.install(context,page);page.goto(ui.BASE+'/',wait_until='domcontentloaded',timeout=30000);ui.actor(page,job['username']);recorder.active=True;page.evaluate(HOOK)
    print('已开始自动记录ins01的操作。请选择已分配视频：'+str(root/job['video']),flush=True)
    print('手动演示创建、裁剪、文案及高级设置；停在最终分享前，点右下角“结束记录并打包”。',flush=True)
    recorder.capture('开始')
    while browser.is_connected() and not page.is_closed() and time.monotonic()-recorder.start<MAX_SECONDS:
     page.wait_for_timeout(150)
     if recorder.drain():
      recorder.capture('结束');recorder.export('用户点击结束记录');break
     if recorder.due and time.monotonic()>=recorder.due:
      recorder.capture('操作后');recorder.due=None
    if not recorder.ended:recorder.export('浏览器关闭或录制达到20分钟')
    # Keep publication guards until the user cancels and closes this manual page.
    until=time.monotonic()+300
    while browser.is_connected() and not page.is_closed() and time.monotonic()<until:page.wait_for_timeout(250)
  except KeyboardInterrupt:
   if not recorder.ended:recorder.export('用户在PowerShell结束记录')
  except Exception as error:
   recorder.warnings.append(str(error))
   if not recorder.ended:recorder.export('录制停止，见warnings')
   print('录制异常：'+str(error),flush=True);return 3
  return 0

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
 try:raise SystemExit(run(Path(sys.argv[1]).resolve()))
 except Exception as error:print('STOP：'+str(error),flush=True);raise SystemExit(1)
