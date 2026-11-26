"""End proven old FB work, release its profiles, then delete proven pre-Nov26 media."""
import contextlib,hashlib,json,ntpath,os,re,subprocess,sys,time,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parent))
import material_distribution_worker_check as workers
import clean_pre_nov26_materials_20261126 as cleanup
import set_login_abnormal_fb32_fb52_20261126 as disabled
from publication_file_state_20261124 import save

DAY='2026-11-26';CUTOFF='2026-11-25'
BOOTSTRAP=re.compile(workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_prepare_fb_for_nov26_20261126').replace('verified-first24-material-distribution','verified-fb-prepare-nov26'))
SNAPSHOT=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$rows=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -in @('python.exe','pythonw.exe','powershell.exe','pwsh.exe')} | ForEach-Object {
 [pscustomobject]@{pid=[long]$_.ProcessId;parent=[long]$_.ParentProcessId;name=[string]$_.Name;exe=[string]$_.ExecutablePath;command=[string]$_.CommandLine;created=$_.CreationDate.ToUniversalTime().ToString('o')}
})
$tasks=@(Get-ScheduledTask | ForEach-Object {[pscustomobject]@{name=$_.TaskName;path=$_.TaskPath;actions=@($_.Actions | ForEach-Object {[pscustomobject]@{execute=[string]$_.Execute;arguments=[string]$_.Arguments;working=[string]$_.WorkingDirectory}})}})
[pscustomobject]@{processes=$rows;tasks=$tasks} | ConvertTo-Json -Depth 8 -Compress
'''

def norm(path):return ntpath.normcase(ntpath.normpath(str(path)))
def same(a,b):return norm(a)==norm(b)
def below(path,root):return norm(path).startswith(norm(root).rstrip('\\')+'\\')
def identity(row):return dict(pid=row['pid'],name=row['name'],created=row['created'],command_sha=hashlib.sha256(row['command'].encode()).hexdigest())
def known_entries():return json.loads(Path(__file__).with_name('known_old_fb_entries_20261126.json').read_text())

def manifest_date(root,name):
    path=Path(name)
    if not path.is_absolute():path=root/path
    try:path.resolve().relative_to((root/'logs').resolve())
    except ValueError:return None
    if not re.fullmatch(r'(?:frozen-material|automatic-retry)-\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json',path.name):return None
    value=cleanup.checked(cleanup.media.safe(root,path));p=value['payload']
    if not path.stem.endswith(value['sha256'][:16]):return None
    return cleanup.day(p.get('material_source_date') or p.get('material_date') or p.get('date'))

def entry_date(root,args,known):
    argv=list(args)
    if argv[:1]==['-u']:argv=argv[1:]
    if not argv:return None
    if argv[0]=='-c' and len(argv)==3 and same(argv[2],root):
        match=re.fullmatch(r"import hashlib,ssl,sys,urllib\.request;c=ssl\.create_default_context\(\);c\.minimum_version=ssl\.TLSVersion\.TLSv1_2;b=urllib\.request\.urlopen\('https://raw\.githubusercontent\.com/prycken-ux/facebook/[a-f0-9]{40}/downloads/([a-zA-Z0-9_]+\.py)',context=c,timeout=30\)\.read\(131073\);hashlib\.sha256\(b\)\.hexdigest\(\)=='([a-f0-9]{64})' or sys\.exit\('Checksum mismatch; stopped'\);exec\(compile\(b,'[a-zA-Z0-9_-]+','exec'\)\)",argv[1])
        if match:return next((r['material_date'] for r in known if r['name']==match[1] and r['sha256']==match[2]),None)
    lower=[a.casefold() for a in argv]
    script=None
    if argv[0].lower().endswith('.py'):script=argv[0]
    elif '-file' in lower:
        i=lower.index('-file')
        if i+1<len(argv):script=argv[i+1]
    if not script or not below(script,root):return None
    path=Path(script)
    if path.is_file() and below(script,root/'material-staging/tools'):
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        d=next((r['material_date'] for r in known if r['name']==path.name and r['sha256']==sha),None)
        root_bound=any(same(a,root) for a in argv[1:])
        if d and root_bound:return d
    if '--manifest' in lower and ntpath.basename(script) in {'scheduled_material_batch.py','scheduled_priority_workflow.py','daily_publish_and_comments.py'}:
        i=lower.index('--manifest')
        if i+1<len(argv):return manifest_date(root,argv[i+1])
    return None

def plan(root,snapshot,known=None,pid=None,runner=None):
    known=known_entries() if known is None else known;pid=os.getpid() if pid is None else pid;runner=Path(__file__).resolve() if runner is None else Path(runner)
    rows=snapshot['processes'];py=[r for r in rows if r['name'].casefold() in {'python.exe','pythonw.exe'}]
    with patch.object(workers,'BOOTSTRAP',BOOTSTRAP):_,allowed=workers.classify_workers(py,root,pid,runner)
    stop=[];unknown=[];ignored=set()
    for row in rows:
        if row['pid'] in allowed:continue
        args=workers.win_args(row['command'])
        if args and same(args[-1],root.parent/'IG-AutoUpload'):ignored.add(row['pid']);continue
        related=(norm(root) in row['command'].replace('/','\\').casefold()) or below(row['exe'],root)
        if not related:continue
        d=entry_date(root,args[1:],known)
        if d and d<=CUTOFF:stop.append(dict(identity(row),material_date=d,kind='queue' if row['name'].casefold() in {'powershell.exe','pwsh.exe'} else 'worker'))
        else:unknown.append(dict(identity(row),reason='今日或无法确认来源的项目任务，保留'))
    tasks=[];retained_tasks=[]
    for task in snapshot.get('tasks',[]):
        dates=[];bound=False
        for action in task.get('actions',[]):
            args=workers.win_args(action.get('arguments',''));related=norm(root) in action.get('arguments','').replace('/','\\').casefold() or below(action.get('execute',''),root)
            if not related:dates.append(None);continue
            bound=True;dates.append(entry_date(root,args,known))
        if bound and dates and all(d and d<=CUTOFF for d in dates):tasks.append(task)
        elif bound:retained_tasks.append(task)
    if unknown:raise ValueError('仍有今日或来源未核实的FB任务，未结束进程或删除素材：'+','.join(str(r['pid']) for r in unknown))
    return dict(schema='fb-old-materials-preparation-v1',root=str(root),cutoff=CUTOFF,keep_from=DAY,allowed=[identity(r) for r in rows if r['pid'] in set(allowed)|ignored],stop=sorted(stop,key=lambda r:r['kind']!='queue'),tasks=tasks,retained_tasks=retained_tasks,created_at=datetime.now(timezone.utc).isoformat())

def snapshot():
    r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',SNAPSHOT],capture_output=True,timeout=30,creationflags=0x08000000)
    if r.returncode:raise RuntimeError('无法核对项目任务及计划任务，未删除：'+r.stderr.decode('utf-8-sig',errors='replace')[-1200:])
    return json.loads(r.stdout.decode('utf-8-sig'))

def live(root):
    s=snapshot();prepared=plan(root,s)
    return prepared['stop']

def windows_prepare(root,prepared,run):
    plan_path=root/'logs'/('nov26-prepare-plan-'+run+'.json');audit_path=root/'logs'/('nov26-prepare-windows-'+run+'.json');output=root/'logs'/('nov26-prepare-windows-'+run+'.log');save(plan_path,prepared)
    with output.open('ab') as stream:
        p=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('prepare_fb_windows_20261126.ps1')),'-Plan',str(plan_path),'-Result',str(audit_path)],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,creationflags=0x08000000)
        began=time.monotonic();notice=began
        while p.poll() is None:
            now=time.monotonic()
            if now-notice>=10:print('正在结束旧FB任务并关闭账号窗口；已用',int(now-began),'秒。',flush=True);notice=now
            if now-began>120:p.kill();p.wait(timeout=10);raise RuntimeError('关闭任务/窗口超过准备上限，未开始删除视频。诊断：'+str(output))
            time.sleep(.25)
    if p.returncode or not audit_path.is_file():raise RuntimeError('旧任务/窗口处理未完成，未删除视频。诊断：'+str(output)+'\n'+output.read_text(encoding='utf-8-sig',errors='replace')[-2500:])
    audit=json.loads(audit_path.read_text(encoding='utf-8-sig'))
    if audit.get('schema')!='fb-old-materials-windows-audit-v1' or not same(audit.get('root',''),root) or audit.get('cutoff')!=CUTOFF or audit.get('completed') is not True or audit.get('instagram_untouched') is not True or audit.get('blocked'):raise RuntimeError('FB窗口或任务释放回执未通过，未删除视频：'+json.dumps(audit,ensure_ascii=False))
    return audit

def execute(root):
    root=Path(root).resolve()
    if root!=cleanup.upload.ROOT.resolve() or not (root/'upload_config.json').is_file():raise ValueError('不是原FB-AutoUpload目录')
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!=DAY:raise ValueError('此入口仅用于北京时间11月26日准备，不用于其他日期清理')
    run=uuid.uuid4().hex;print('准备11月26日FB环境：仅清理25日及以前，Instagram目录和今天素材保留。',flush=True)
    prepared=plan(root,snapshot());print('已核实旧任务',len(prepared['stop']),'个、旧计划任务',len(prepared['tasks']),'个；开始释放FB窗口。',flush=True)
    if prepared['retained_tasks']:print('来源不明/包含其他操作的计划任务保留：',','.join(t['path']+t['name'] for t in prepared['retained_tasks']),flush=True)
    audit=windows_prepare(root,prepared,run)
    if live(root):raise RuntimeError('结束旧任务后仍有FB进程，未删除素材')
    disabled.apply(root)
    with patch.object(cleanup.workers,'active_workers',side_effect=lambda *a,**k:live(root)):
        cleanup.execute(root)
    save(root/'logs/materials-ended-through-20261125.json',dict(cutoff=CUTOFF,keep_from=DAY,retired_at=datetime.now(timezone.utc).isoformat(),windows_audit=audit,instagram_untouched=True))
    print('FB旧素材清理和窗口准备结束；今天还未分配或发布。新分配会读取实际停用名单；既有基线为36个停用账号、58个可用目标。',flush=True)
    return 0

class Tee:
    def __init__(self,*streams):self.streams=streams
    def write(self,text):
        for stream in self.streams:stream.write(text);stream.flush()
        return len(text)
    def flush(self):
        for stream in self.streams:stream.flush()

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
        root=Path(sys.argv[1]).resolve()
        with (root/'logs/nov26-environment-prepare-run.log').open('a',encoding='utf-8') as output,contextlib.redirect_stdout(Tee(sys.stdout,output)):
            try:raise SystemExit(execute(root))
            except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
