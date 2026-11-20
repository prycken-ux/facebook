"""Three isolated real-footage allocations and one-shot Beijing 17:10 runs."""
import base64,contextlib,copy,hashlib,json,os,re,shutil,subprocess,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parent))
import publish_eligible60_materials_20261119 as app
import publication_content_20261119 as content
from xml.etree import ElementTree as ET

VERSION='1.0-weekend60-nov20-22-beijing1710-real-off'
DAYS=('2026-11-20','2026-11-21','2026-11-22')
TIME='17:10'
BJ=timezone(timedelta(hours=8))
FOLDER='material-staging/weekend60-20261120-22-1710'
MANIFEST=FOLDER+'/manifest.json'
SCHEMA='weekend60-three-days-source-bound-v1'
AUTH='user-authorized-nov20-through22-1710-real-footage-no-ai-v1'
NS='http://schemas.microsoft.com/windows/2004/02/mit/task'
ET.register_namespace('',NS)
upload=app.first.upload
materials=app.stage.materials
BOOTSTRAP=re.compile(app.workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_weekend60_schedule_20261120').replace('verified-first24-material-distribution','verified-weekend60-three-day-schedule'))


def now():return datetime.now(timezone.utc)
def today():return now().astimezone(BJ).date().isoformat()
def digest(value):return app.first.batch.digest(value)
def safe(root,path):return app.stage.safe_child(Path(root),Path(path))
def day_inbox(root,account,target,day):
    if day not in DAYS or (account,target) not in app.EXPECTED:raise ValueError('日期或发布目标不属于本次三天60目标计划。')
    return safe(root,root/'videos'/account/target/'scheduled'/day/'inbox')
def day_runner(day):return Path(__file__).with_name('weekend60_run_'+day.replace('-','')+'.py')


def inspect_workers(root):
    runner=Path(sys.argv[0]).resolve()
    allowed={Path(__file__).resolve(),*(day_runner(d).resolve() for d in DAYS)}
    extra=()
    if runner not in allowed:runner=Path(__file__).resolve()  # tests/import-only verification never launches a worker
    elif runner!=Path(__file__).resolve():
        if len(sys.argv)!=3 or not re.fullmatch('[a-f0-9]{64}',sys.argv[2]):raise ValueError('定时任务缺少原三天计划指纹。')
        extra=(sys.argv[2],)
    with patch.object(app.workers,'BOOTSTRAP',BOOTSTRAP):return app.workers.active_workers(root,runner,extra_arguments=extra)


def checked_json(root,path):
    value=upload.read_json(safe(root,path),{});p=value.get('payload',{})
    if not isinstance(p,dict) or value.get('sha256')!=digest(p):raise ValueError('原清单指纹变化，未另选素材：'+str(path))
    return value


def history_hashes(root):
    found=set()
    # Prior import journals carry raw video hashes even after local media cleanup.
    for path in (root/'logs/material-distribution').glob('*/*.json'):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:-reserved50|-eligible78|-eligible62|-eligible60)?\.json',path.name):continue
        value=materials.read_plan(upload,path)
        found.update(r['files'][-1]['sha256'] for r in value['payload']['assignments'])
    for path in (root/'material-staging').glob('*/*/manifest.json'):
        _,value=app.stage.validate_stage(root,path)
        found.update(r['files'][-1]['sha256'] for r in value['payload']['distribution']['payload']['assignments'])
    ledger=upload.read_json(root/'logs/user_confirmed_archived_media.json',None)
    if ledger is not None:
        if ledger.get('schema')!='user-confirmed-archived-media-v1' or not isinstance(ledger.get('rows'),dict):raise ValueError('原归档台账异常。')
        found.update(r['video_sha256'] for r in ledger['rows'].values() if r.get('status')=='published' and re.fullmatch('[a-f0-9]{64}',str(r.get('video_sha256',''))))
    for path in (root/'logs').glob('frozen-material-*-*.json'):
        if not re.fullmatch(r'frozen-material-\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json',path.name):continue
        value=checked_json(root,path)
        found.update(j['video_sha256'] for j in value['payload'].get('jobs',[]) if re.fullmatch('[a-f0-9]{64}',str(j.get('video_sha256',''))))
    cleanup=upload.read_json(root/'logs/user-video-cleanup-20261119-progress.json',None)
    if cleanup is not None:
        plan=checked_json(root,root/'logs/user-video-cleanup-20261119.json')
        if cleanup.get('plan_sha256')!=plan['sha256'] or not isinstance(cleanup.get('rows'),dict):raise ValueError('原视频清理记录异常。')
        found.update(r['sha256'] for r in cleanup['rows'].values() if r.get('status')=='deleted' and re.fullmatch('[a-f0-9]{64}',str(r.get('sha256',''))))
    return found


def validate(root,value):
    p=value.get('payload',{})
    if (value.get('sha256')!=digest(p) or p.get('schema')!=SCHEMA or p.get('authorization')!=AUTH
            or p.get('days')!=list(DAYS) or p.get('time_beijing')!=TIME or p.get('ai_label') is not False
            or p.get('real_footage_confirmed') is not True or p.get('content')!=content.CONTENT
            or p.get('excluded_accounts')!=sorted(app.BLOCKED) or set(p.get('batches',{}))!=set(DAYS)):
        raise ValueError('三天分配、实拍标签或定时授权变化，未继续。')
    sources=[];hashes=set()
    for day,batch in p['batches'].items():
        source=Path(batch['source']);sources.append(str(source).casefold())
        if batch.get('date')!=day or batch.get('source_id')!=hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]:raise ValueError('素材日期或源目录指纹不符。')
        rows=batch['assignments'];app.stage.check_scope(rows)
        for row in rows:
            video=row['files'][-1]
            if (len(row['files'])!=2 or video['kind']!='video' or row['files'][0]['kind']!='caption'
                    or video['sha256'] in hashes or not re.fullmatch('[a-f0-9]{64}',str(video['sha256']))):raise ValueError('素材重复或文件指纹异常。')
            hashes.add(video['sha256'])
            prefix=day.replace('-','')+'-'+batch['source_id'][:8]+'-weekend60-'
            for part in row['files']:
                if Path(part['name']).name!=part['name'] or re.search(r'[\\/:\x00-\x1f]',part['name']) or part['destination_name']!=prefix+part['name']:raise ValueError('素材文件名或日期不符。')
                safe(root,day_inbox(root,row['account'],row['target'],day)/part['destination_name'])
            caption=row['files'][0]
            if caption['sha256']!=hashlib.sha256((content.CAPTION+'\n').encode('utf-8')).hexdigest():raise ValueError('三天统一正文指纹不符。')
    if len(set(sources))!=3:raise ValueError('三天必须选择三个不同的素材文件夹。')
    return value


def choose_sources(root):
    result={}
    for day,label in zip(DAYS,('今天/周五','周六','周日')):
        print('请选择',label,day,'的素材总文件夹（本日60条；不要选择账号目录）。',flush=True)
        result[day]=str(materials.validate_source(Path(materials.choose_source()).resolve()))
    return result


def make_plan(root,sources):
    if set(sources)!=set(DAYS):raise ValueError('必须分别选择周五、周六、周日三个素材目录。')
    if len({str(Path(v).resolve()).casefold() for v in sources.values()})!=3:raise ValueError('请依次选择周五、周六、周日三个不同素材文件夹。')
    if today()!=DAYS[0]:raise ValueError('首次设置仅安排11月20日至22日；已保存计划可以继续原进度。')
    rows,generations=app.stage.target_snapshot(root,scope='eligible60');app.stage.check_scope(rows)
    used=history_hashes(root);batches={};total_bytes=0
    for day in DAYS:
        source=materials.validate_source(Path(sources[day]).resolve())
        if source.is_relative_to((root/'material-staging').resolve()):raise ValueError('请选择桌面原素材目录，不能选已生成的暂存目录。')
        token=hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16];files=[];seen=set(used);total=0
        for path in sorted(source.iterdir(),key=lambda p:(materials.natural(p.name),p.name)):
            if path.suffix.lower()!='.mp4' or not path.is_file():continue
            upload.validate_video_filename(path.name);meta=materials.file_info(path);total+=1
            if meta['size']<=0:raise ValueError('视频为空：'+path.name)
            if meta['sha256'] in seen:continue
            seen.add(meta['sha256']);files.append(meta)
        if len(files)<60:raise ValueError(day+' 素材不足：第一层MP4 '+str(total)+'条，去除历史及跨日重复后只有'+str(len(files))+'条，需要60条。尚未复制或注册任务。')
        assignments=[];prefix=day.replace('-','')+'-'+token[:8]+'-weekend60-'
        for target,video in zip(rows,files[:60]):
            caption_name=str(Path(video['name']).with_suffix('.txt'));text=(content.CAPTION+'\n').encode('utf-8')
            caption=dict(kind='caption',name=caption_name,destination_name=prefix+caption_name,size=len(text),sha256=hashlib.sha256(text).hexdigest())
            assignments.append(dict(target,source_token=digest(dict(name=video['name'].casefold(),sha256=video['sha256'])),video_filename=video['name'],files=[caption,dict(video,kind='video',destination_name=prefix+video['name'])]))
            used.add(video['sha256']);total_bytes+=video['size']+len(text)
        batches[day]=dict(date=day,source=str(source),source_id=token,assignments=assignments,leftover_count=len(files)-60,generations=generations)
        print(day,'待分配60条；第一层MP4',total,'；多余新素材保留',len(files)-60,'条。',flush=True)
    p=dict(schema=SCHEMA,authorization=AUTH,created_at=now().isoformat(),days=list(DAYS),time_beijing=TIME,ai_label=False,real_footage_confirmed=True,content=copy.deepcopy(content.CONTENT),excluded_accounts=sorted(app.BLOCKED),batches=batches,total_copy_bytes=total_bytes)
    return validate(root,dict(payload=p,sha256=digest(p)))


def prepare(root,sources=None):
    root=app.stage.setup(root);folder=safe(root,root/FOLDER);folder.mkdir(parents=True,exist_ok=True);path=folder/'manifest.json'
    with app.stage.staging_lock(folder):
        if path.exists():value=validate(root,checked_json(root,path));print('继续三天原分配清单；不重新选目录或重排。',flush=True)
        else:
            value=make_plan(root,sources or choose_sources(root))
            # Reserve enough space before changing account folders.
            required=value['payload']['total_copy_bytes']+max(r['files'][-1]['size'] for b in value['payload']['batches'].values() for r in b['assignments'])+64*1024*1024
            if shutil.disk_usage(root).free<required:raise ValueError('磁盘可用空间不足：三天素材需约'+str(round(required/1024**3,2))+' GB；尚未复制或注册任务。')
            upload.save_json(path,value)
        progress_path=folder/'copy-progress.json';progress=upload.read_json(progress_path,dict(sha256=value['sha256'],done=[],complete=False))
        if progress.get('sha256')!=value['sha256'] or not isinstance(progress.get('done'),list):raise ValueError('三天原复制进度不符。')
        keys={d+'/'+r['account']+'/'+r['target'] for d,b in value['payload']['batches'].items() for r in b['assignments']}
        if len(set(progress['done']))!=len(progress['done']) or not set(progress['done'])<=keys:raise ValueError('复制进度包含其他任务。')
        for day,batch in value['payload']['batches'].items():
            app.stage.check_live_pauses(root,batch['assignments'])
            for index,row in enumerate(batch['assignments'],1):
                key=day+'/'+row['account']+'/'+row['target']
                if key in progress['done']:continue
                folder_day=day_inbox(root,row['account'],row['target'],day);folder_day.mkdir(parents=True,exist_ok=True)
                video=row['files'][-1];source=Path(batch['source'])/video['name']
                materials.copy_exact(source,folder_day/video['destination_name'],video)
                caption=folder_day/row['files'][0]['destination_name']
                if caption.exists() and hashlib.sha256(caption.read_bytes()).hexdigest()!=row['files'][0]['sha256']:raise ValueError('本次预留文案后来变化，未覆盖。')
                if not caption.exists():app.first.atomic_caption(caption,content.CAPTION)
                progress['done'].append(key);upload.save_json(progress_path,progress)
                print(day,str(index)+'/60',row['account']+'/'+row['target'],'←',video['name'],flush=True)
        progress['complete']=set(progress['done'])==keys;upload.save_json(progress_path,progress)
        lines=['三天各60条：北京时间每天17:10开始；实拍AI关闭；原素材保留。','排除34个账号：'+','.join(sorted(app.BLOCKED))]
        for day,batch in value['payload']['batches'].items():
            lines.append('\n'+day+' '+TIME+' +08:00')
            lines += [r['account']+'/'+r['target']+' <- '+r['video_filename']+' -> '+str(day_inbox(root,r['account'],r['target'],day)/r['files'][-1]['destination_name']) for r in batch['assignments']]
        (path.parent/'三天分配清单.txt').write_text('\n'.join(lines),encoding='utf-8-sig')
        print('三天分配完成：180条，按账号和日期独立保存；正式inbox及昨天的记录未改动。',flush=True)
    return path,value


def allocation(root,day,value):
    validate(root,value);batch=value['payload']['batches'][day]
    ready=upload.read_json(root/FOLDER/'copy-progress.json',{})
    if ready.get('sha256')!=value['sha256'] or ready.get('complete') is not True:raise ValueError('三天素材尚未全部准备完毕。')
    # Same distribution schema, separate pointer and dated inbox. Never import a future day.
    payload=dict(schema=materials.SCHEMA,source=batch['source'],date=day,assignments=batch['assignments'],leftover_count=batch['leftover_count'],copy_mode='retain-source',target_scope='eligible60',publication_order=['fb01-fb24-and-registered-pages','fb25-fb74'],excluded_accounts=sorted(app.BLOCKED),paused_policy='user-paused34-nov19-v1')
    distribution=dict(payload=payload,sha256=digest(payload))
    journal=safe(root,root/'logs/material-distribution'/batch['source_id']/(day+'-eligible60.json'))
    if journal.exists() and checked_json(root,journal)!=distribution:raise ValueError('此日期已有其他分配，未覆盖。')
    upload.save_json(journal,distribution)
    upload.save_json(journal.with_name(journal.stem+'-progress.json'),dict(sha256=distribution['sha256'],done=[a+'/'+t for a,t in sorted(app.EXPECTED)],complete=True))
    source_payload=dict(schema='weekend60-dated-allocation-v1',date=day,source_id=batch['source_id'],source=batch['source'],generations=batch['generations'],schedule_sha256=value['sha256'],distribution=distribution)
    source=dict(payload=source_payload,sha256=digest(source_payload))
    source_path=safe(root,root/FOLDER/(day+'-allocation.json'))
    if source_path.exists() and checked_json(root,source_path)!=source:raise ValueError('原日期素材绑定变化。')
    upload.save_json(source_path,source)
    return source_path,source,journal,distribution


def run_day(root,day,expected_sha=None):
    root=Path(root).resolve()
    if day not in DAYS or root!=upload.ROOT.resolve():raise ValueError('定时日期或安装目录不符。')
    value=validate(root,checked_json(root,root/MANIFEST))
    if expected_sha is not None and expected_sha!=value['sha256']:raise ValueError('定时任务绑定的原三天计划已变化，不运行其他素材。')
    planned=datetime.fromisoformat(day+'T'+TIME+':00+08:00')
    if today()!=day:raise ValueError('不在本批授权日期，不提前发布或把错过的素材补到另一天。')
    if now()<planned:raise ValueError('尚未到北京时间17:10，不提前发布。')
    # A per-date claim serializes restarts while waiting for another publisher.
    folder=safe(root,root/FOLDER/('run-'+day));folder.mkdir(exist_ok=True)
    with app.stage.staging_lock(folder):
        while True:
            if today()!=day:raise ValueError('等待其他任务期间已跨日；保留素材，不自动补跑昨天。')
            live=inspect_workers(root)
            if not live:break
            print('本日定时任务等待原发布/评论/检查结束，PID：',','.join(str(r['pid']) for r in live),'；15秒后检查。',flush=True);time.sleep(15)
        app.browser.staged.lock_recovery.recover_locks(root)
        # Validate the frozen policy revision; never save/replace text from another day.
        content.verify(root,value['payload']['content']['sha256'])
        with patch.object(app.content_today,'save_authorized',side_effect=lambda r:content.verify(r,value['payload']['content']['sha256'])),patch.object(app,'AUTH',AUTH),patch.object(app.queued,'AUTH',AUTH),patch.object(app.content_today,'DAY',day),patch.object(app,'REQUEST','logs/weekend60-publication-request-'+day+'.json'), \
             patch.object(app,'allocation',side_effect=lambda r:allocation(r,day,value)),patch.object(app,'current_workers',side_effect=inspect_workers), \
             patch.object(upload,'inbox_for',side_effect=lambda entry:day_inbox(root,entry['account'],entry['target'],day)), \
             patch.object(app.owners.guided,'prompt',return_value='S'):
            print('开始',day,'北京时间17:10独立60目标任务；后台发布、一次安全补发及评论；人工验证先跳过并留在日志。',flush=True)
            return app.execute(root,True)


def task_xml(root,day,value):
    def add(parent,name,text=None,**attrs):
        element=ET.SubElement(parent,'{'+NS+'}'+name,attrs);element.text=text;return element
    task=ET.Element('{'+NS+'}Task',version='1.4')
    add(add(task,'RegistrationInfo'),'Description','Exact60 '+day+' Beijing17:10; real footage AI OFF; headless; safe retries and comments; '+value['sha256'])
    trigger=add(add(task,'Triggers'),'TimeTrigger');add(trigger,'StartBoundary',day+'T'+TIME+':00+08:00');add(trigger,'EndBoundary',(datetime.fromisoformat(day)+timedelta(days=1)).date().isoformat()+'T00:00:00+08:00');add(trigger,'Enabled','true')
    principal=add(add(task,'Principals'),'Principal',id='Author');add(principal,'UserId','CURRENT_USER');add(principal,'LogonType','InteractiveToken');add(principal,'RunLevel','LeastPrivilege')
    settings=add(task,'Settings')
    for key,text in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),('StopIfGoingOnBatteries','false'),('AllowHardTerminate','false'),('StartWhenAvailable','true'),('RunOnlyIfNetworkAvailable','false'),('Enabled','false'),('WakeToRun','true'),('ExecutionTimeLimit','PT0S')]:add(settings,key,text)
    action=add(add(task,'Actions',Context='Author'),'Exec');add(action,'Command',str(root/'.venv/Scripts/pythonw.exe'));add(action,'Arguments',subprocess.list2cmdline(['-u',str(day_runner(day)),str(root),value['sha256']]));add(action,'WorkingDirectory',str(root))
    return ET.tostring(task,encoding='unicode')


REGISTER=r'''$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$d=[Console]::In.ReadToEnd() | ConvertFrom-Json
$created=@();$enabled=@()
try {
 foreach($item in @($d.tasks)) {
  $existing=Get-ScheduledTask -TaskName $item.name -ErrorAction SilentlyContinue
  if($null -eq $existing) {
   [xml]$xml=$item.xml;$xml.Task.Principals.Principal.UserId=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
   Register-ScheduledTask -TaskName $item.name -Xml $xml.OuterXml -ErrorAction Stop | Out-Null
   $created+=$item.name
  } else {
   $actions=@($existing.Actions);$triggers=@($existing.Triggers)
   if($actions.Count -ne 1 -or $actions[0].Execute -ne $d.python -or $actions[0].Arguments -ne $item.arguments -or $actions[0].WorkingDirectory -ne $d.root -or $triggers.Count -ne 1 -or $triggers[0].CimClass.CimClassName -ne 'MSFT_TaskTimeTrigger' -or $triggers[0].Repetition.Interval) {throw 'Existing schedule differs from this exact date/source; not replaced.'}
   if([DateTimeOffset]::Parse($triggers[0].StartBoundary) -ne [DateTimeOffset]::Parse($item.start) -or [DateTimeOffset]::Parse($triggers[0].EndBoundary) -ne [DateTimeOffset]::Parse($item.end)) {throw 'Existing schedule boundaries differ; not replaced.'}
  }
 }
 foreach($item in @($d.tasks)) {
  Enable-ScheduledTask -TaskName $item.name -ErrorAction Stop | Out-Null
  $enabled+=$item.name
  $task=Get-ScheduledTask -TaskName $item.name -ErrorAction Stop
  $info=Get-ScheduledTaskInfo -TaskName $item.name -ErrorAction Stop
  [pscustomobject]@{TaskName=$task.TaskName;State=[string]$task.State;StartBeijing=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::Parse($task.Triggers[0].StartBoundary),'China Standard Time').ToString('o');NextRunTime=[string]$info.NextRunTime;LastTaskResult=$info.LastTaskResult} | ConvertTo-Json -Compress
 }
 # A same-day setup after 17:10 starts only that due date. Future dates never start here.
 $beijing=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::UtcNow,'China Standard Time')
 foreach($item in @($d.tasks)) {
  $start=[DateTimeOffset]::Parse($item.start);$end=[DateTimeOffset]::Parse($item.end)
  if($beijing -ge $start -and $beijing -lt $end) {Start-ScheduledTask -TaskName $item.name -ErrorAction Stop}
 }
} catch {
 foreach($name in $created){try{Disable-ScheduledTask -TaskName $name | Out-Null}catch{}}
 throw
}
'''


def register(root,value):
    validate(root,value)
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑注册三天任务。')
    python=root/'.venv/Scripts/pythonw.exe'
    if not python.is_file():raise ValueError('缺少原虚拟环境pythonw.exe，未注册会弹窗的替代任务。')
    tasks=[]
    for day in DAYS:
        runner=day_runner(day)
        if not runner.is_file():raise ValueError('缺少本日期的固定后台入口。')
        name='FBUpload-Weekend60-'+day.replace('-','')+'-'+value['sha256'][:8]
        xml=task_xml(root,day,value);tree=ET.fromstring(xml);ns={'t':NS}
        tasks.append(dict(name=name,xml=xml,arguments=subprocess.list2cmdline(['-u',str(runner),str(root),value['sha256']]),start=day+'T'+TIME+':00+08:00',end=tree.find('t:Triggers/t:TimeTrigger/t:EndBoundary',ns).text))
    payload=dict(root=str(root),python=str(python),tasks=tasks)
    receipt_path=safe(root,root/FOLDER/'task-registration.json')
    upload.save_json(safe(root,root/FOLDER/'task-registration-request.json'),dict(schedule_sha256=value['sha256'],payload=payload))
    completed=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',REGISTER],input=json.dumps(payload).encode('utf-8'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90,check=False,creationflags=0x08000000)
    if completed.returncode:raise RuntimeError('三天定时注册尚未全部完成，素材保留：'+completed.stderr.decode('utf-8','replace')[:1500])
    receipts=[json.loads(line) for line in completed.stdout.decode('utf-8-sig').splitlines() if line.startswith('{')]
    if {r.get('TaskName') for r in receipts}!={t['name'] for t in tasks} or any(r.get('State') not in {'Ready','Running','Queued'} for r in receipts) or any(datetime.fromisoformat(r['StartBeijing'])!=datetime.fromisoformat(next(t['start'] for t in tasks if t['name']==r['TaskName'])) for r in receipts):raise ValueError('三天定时回读未完整确认，素材及请求记录保留。')
    upload.save_json(receipt_path,dict(schedule_sha256=value['sha256'],registered_at=now().isoformat(),tasks=receipts))
    print('三个一次性计划已注册并回读确认：',flush=True)
    for row in receipts:print(row['StartBeijing'],row['TaskName'],row['State'],flush=True)
    print('请保持电脑开机联网、Windows用户已登录；自动发布使用无窗口Chrome，验证失败先跳过。',flush=True)
    print('180条分配清单：',root/FOLDER/'三天分配清单.txt','；计划回执：',receipt_path,flush=True)
    return receipts


def setup(root,sources=None,real_footage_confirmed=False):
    if real_footage_confirmed is not True:raise ValueError('三天新素材未确认全部实拍和AI关闭。')
    root=Path(root).resolve();content.verify(root,content.CONTENT['sha256'])
    _,value=prepare(root,sources);register(root,value);return 0


if __name__=='__main__':
    if sys.stdout is not None:sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
        raise SystemExit(setup(Path(sys.argv[1]),real_footage_confirmed=True))
    except KeyboardInterrupt:print('已暂停；三天原素材、分配及已注册计划保留，重跑同一入口续原进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
