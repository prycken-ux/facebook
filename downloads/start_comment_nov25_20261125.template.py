"""Install verified Nov25 publication and a nonblocking PowerShell waiting queue."""
import ast,hashlib,json,os,ssl,subprocess,sys,time,types,urllib.request,uuid
from pathlib import Path
BASE_URL='https://raw.githubusercontent.com/prycken-ux/facebook/b00862fe3ac4c5f36edc56b22bfc0e8c355abbe5/downloads/start_publish_guarded_nov25_20261125.py'
BASE_SHA='3dbcac0b3b73a9bf79198967e2a49bfb85c899dbacb6a18aedb1c31b9cade92b'
ADDITIONS={}
FINGERPRINT=''

def base_runtime():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    data=urllib.request.urlopen(BASE_URL,context=context,timeout=30).read(131073)
    if hashlib.sha256(data).hexdigest()!=BASE_SHA:raise ValueError('Original package checksum mismatch')
    module=types.ModuleType('verified_original_runtime');exec(compile(data,'verified-original-package','exec'),module.__dict__);base=module.base_runtime();return types.SimpleNamespace(download=lambda:dict(base.download(),**module.ADDITIONS),VERIFY=base.VERIFY,store=base.store)

def start(root):
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
    root=Path(root).resolve()
    if not (root/'upload_config.json').is_file() or not (root/'.venv/Scripts/python.exe').is_file():raise ValueError('原发布配置或Python缺失。')
    manifest={n:hashlib.sha256(b).hexdigest() for n,b in ADDITIONS.items()}
    if hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()!=FINGERPRINT:raise ValueError('Nov25 runtime checksum mismatch')
    base=base_runtime();updates=base.download();updates.update(ADDITIONS)
    for name,data in updates.items():
        if name.endswith('.py'):ast.parse(data.decode('utf-8-sig'))
    folder=root/'material-staging/tools'/('nov25-comments-repair-'+FINGERPRINT[:16])
    for path in (root/'material-staging',root/'material-staging/tools',folder):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):raise ValueError('工具缓存包含链接。')
        path.mkdir(exist_ok=True)
    for name,data in updates.items():base.store(folder,name,data)
    base.store(folder,'runtime-sha256.json',json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in updates.items()},sort_keys=True).encode())
    verify=base.VERIFY.replace("VERIFIED: Nov23 original60","BASE VERIFIED: original60")+";import publish_eligible60_real_20261125 as d;import comment_target_watchdog_20261125 as w;import reel_audience_dialog_recovery as r;import repair_nov25_comments_only as c;assert c.DAY=='2026-11-25';import pending_video_comment_lookup_20261119 as pending;assert pending.TIME_WINDOW_VERSION=='1.1-upload-created-before-post-intent';import nov25_publication_policy as p;assert p.VERSION=='1.0-nov25-post-click-assumption-exact-comments';assert d.DAY=='2026-11-25' and d.AUTH=='user-authorized-nov25-original60-real-off-original-book-caption-comment-v1';assert d.CONTENT_SHA=='ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894';assert w.COMMENT_SECONDS==180 and w.VIDEO_SECONDS==180;assert r.VERSION=='1.1-contenteditable-caption-audience-recovery';print('NOV25 COMMENTS VERIFIED: original comment; exact-video lookup; 180s per comment; video uploads forbidden',flush=True)"
    subprocess.run([sys.executable,'-c',verify,str(folder),str(root)],check=True)
    run=uuid.uuid4().hex;entry=folder/'comment_target_watchdog_20261125.py';queue=folder/'queue_comment_nov25_20261125.ps1'
    status_path=root/'logs'/('nov25-comments-queue-'+run+'.json');output_path=root/'logs'/('nov25-comments-queue-'+run+'.log')
    with output_path.open('ab') as output:
        process=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(queue),'-Root',str(root),'-Entry',str(entry),'-EntrySha',manifest[entry.name],'-Run',run],stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,creationflags=0x08000200,cwd=root)
    for _ in range(150):
        try:status=json.loads(status_path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):status={}
        matching=status.get('run_id')==run;code=process.poll()
        if matching and status.get('phase') in {'waiting_workers','waiting_distribution','starting','started','already_queued','already_running'}:
            print('25号补评论队列已确认：'+status['message'],flush=True)
            print('仅处理25号原视频的原评论；等待视频发布释放账号；不重传视频。实际进度：'+str(root/'logs/eligible60-2026-11-25-comments-repair-run.log'),flush=True)
            print('队列状态：'+str(status_path)+'；启动记录：'+str(output_path),flush=True);return 0
        if (matching and status.get('phase')=='failed') or code is not None:
            detail=output_path.read_bytes()[-5000:].decode('utf-8',errors='replace')
            raise RuntimeError(status.get('message','发布队列未确认启动。')+'\n'+detail+'\n启动记录：'+str(output_path))
        time.sleep(.2)
    print('发布队列仍在核验，请勿重复启动。状态：'+str(status_path)+'；记录：'+str(output_path),flush=True);return 0

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1])))
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
