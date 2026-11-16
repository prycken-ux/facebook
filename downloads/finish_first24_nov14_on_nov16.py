"""Nov16 continuation: repair proven pre-Post originals, then the fixed Nov14 stage.

Retire expired execution queues, never publication evidence or material history.
"""
import contextlib,copy,json,ntpath,os,re,shutil,subprocess,sys,uuid
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    sys.path.insert(0,str(Path(__file__).resolve().parent))
import publish_staged_first24_nov14 as staged
import retry_first24_original_prepost_on_nov16 as repair
first=staged.first
DAY='2026-11-16'
MATERIAL_DAY='2026-11-14'
SCOPE='nov16-publish-exact-nov14-stage-ee49926eedf51de8-first24-v1'
POINTER=SCOPE+'.json'
VERSION='1.0-nov16-frozen-stage-and-prepost-only'
WORKER_VERSION='1.1-verified-windows-venv-launch-chain'
RUN=first.execute
NORMAL=first.normal.launch_normal
RECONCILE=first.reconcile
SKIPPED=set()

# Query locally; raw command lines stay in memory, never console/report output.
# A Windows venv redirector may retain a Python stub for EACH invocation:
# bootstrap stub -> bootstrap runtime -> runner stub -> runner runtime.
WORKERS=r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$d=[Console]::In.ReadToEnd() | ConvertFrom-Json
$result=@()
foreach($p in @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop)){
  $created=$null
  if($null -ne $p.CreationDate){$created=$p.CreationDate.ToUniversalTime().ToString('o')}
  $result+=[pscustomobject]@{pid=[long]$p.ProcessId;parent=[long]$p.ParentProcessId;name=[string]$p.Name;exe=[string]$p.ExecutablePath;command=[string]$p.CommandLine;created=$created}
}
ConvertTo-Json -InputObject @($result) -Compress
'''

BOOTSTRAP=re.compile(
    r"import hashlib,ssl,sys,urllib\.request;c=ssl\.create_default_context\(\);c\.minimum_version=ssl\.TLSVersion\.TLSv1_2;"
    r"b=urllib\.request\.urlopen\('https://raw\.githubusercontent\.com/prycken-ux/facebook/[a-f0-9]{40}/downloads/start_finish_first24_nov16\.py',context=c,timeout=30\)\.read\(131073\);"
    r"hashlib\.sha256\(b\)\.hexdigest\(\)=='[a-f0-9]{64}' or sys\.exit\('Checksum mismatch; stopped'\);"
    r"exec\(compile\(b,'verified-nov16-first24-and-nov14-stage','exec'\)\)")


def win_args(line):
    """Decode standard Windows CRT quoting without evaluating any command."""
    result=[];index=0
    while index<len(line):
        while index<len(line) and line[index] in ' \t':index+=1
        if index==len(line):break
        word=[];quoted=False
        while index<len(line) and (quoted or line[index] not in ' \t'):
            slashes=0
            while index<len(line) and line[index]=='\\':slashes+=1;index+=1
            if index<len(line) and line[index]=='"':
                word.extend('\\'*(slashes//2))
                if slashes%2:word.append('"');index+=1
                elif quoted and index+1<len(line) and line[index+1]=='"':word.append('"');index+=2
                else:quoted=not quoted;index+=1
            else:
                word.extend('\\'*slashes)
                if index<len(line) and (quoted or line[index] not in ' \t'):word.append(line[index]);index+=1
        if quoted:raise ValueError('进程参数引号未能完整核对。')
        result.append(''.join(word))
    return result


def win_path(value):return ntpath.normcase(ntpath.normpath(str(value)))


def classify_workers(rows,root,pid,runner=None):
    """Exempt only the actual contiguous, argument-verified parent chain.

    Base Python executable paths are allowed within that verified chain. A
    sibling/second launch, an old publisher, an unknown ancestor, or a recycled
    parent PID remains a blocker even when it uses the same runtime or filename.
    """
    if (not isinstance(rows,list) or any(not isinstance(r,dict) or type(r.get('pid')) is not int or type(r.get('parent')) is not int
            or r.get('name','').lower() not in {'python.exe','pythonw.exe'} or not isinstance(r.get('command'),str)
            or not isinstance(r.get('exe'),str) for r in rows)):raise ValueError('发布进程检查数据异常。')
    lookup={r['pid']:r for r in rows}
    if len(lookup)!=len(rows) or pid not in lookup:raise ValueError('无法唯一定位本次发布进程。')
    root_key=win_path(root);runner_key=win_path(runner or Path(__file__).resolve())
    parsed={}
    for r in rows:
        if not r['command'] and not r['exe']:raise ValueError('有Python进程无法核对，未开始发布。')
        try:parsed[r['pid']]=win_args(r['command'])
        except ValueError:parsed[r['pid']]=[]
    def args(row):
        argv=parsed[row['pid']][1:]
        return argv[1:] if argv[:1]==['-u'] else argv
    def role(row):
        argv=args(row)
        if len(argv)==2 and win_path(argv[0])==runner_key and win_path(argv[1])==root_key:return 'runner'
        if len(argv)==3 and argv[0]=='-c' and BOOTSTRAP.fullmatch(argv[1]) and win_path(argv[2])==root_key:return 'bootstrap'
        return None
    def born(row):
        try:return datetime.fromisoformat(row['created'].replace('Z','+00:00')).timestamp()
        except (ValueError,TypeError,KeyError):return None
    allowed={pid};current=lookup[pid];phase='runner'
    if role(current)=='runner':
        for _ in range(8):
            parent=lookup.get(current['parent'])
            if parent is None or parent['pid'] in allowed:break
            child_time,parent_time=born(current),born(parent)
            if child_time is None or parent_time is None or parent_time>child_time:break
            kind=role(parent)
            duplicate=kind==phase and args(parent)==args(current)
            transition=phase=='runner' and kind=='bootstrap'
            if not (duplicate or transition):break
            allowed.add(parent['pid']);current=parent;phase=kind
    workers=[]
    for row in rows:
        if row['pid'] in allowed:continue
        related=win_path(row['exe'])==win_path(ntpath.join(str(root),'.venv','Scripts','python.exe')) or root_key in row['command'].replace('/','\\').casefold()
        if not related:continue
        argv=args(row);script=ntpath.basename(argv[0]) if argv else ''
        if (argv and win_path(ntpath.dirname(argv[0]))==root_key
                and re.fullmatch(r'(?:summarize_[a-z0-9_]+|start_stage_(?:first24|next)_materials_20261114)\.py',script,re.I)):continue
        kind='另一个本批启动进程' if role(row) else '发布/登录检查任务' if re.fullmatch(r'(?:publish|resume|retry|diagnose|stage|finish|start)_[a-z0-9_]+\.py',script,re.I) else '未识别的Python任务'
        workers.append(dict(pid=row['pid'],name=row['name'],kind=kind))
    return workers,sorted(allowed)


def active_workers(root):
    if sys.platform!='win32':raise ValueError('发布进程检查必须在原Windows电脑执行。')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',WORKERS],input=b'{}',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,creationflags=0x08000000)
    if result.returncode:raise RuntimeError('无法读取当前发布进程信息，尚未导入或发布。')
    try:rows=json.loads(result.stdout.decode('utf-8-sig'))
    except (ValueError,UnicodeError):raise ValueError('发布进程信息未能读取，未开始发布。') from None
    workers,allowed=classify_workers(rows,root,os.getpid())
    print('本次启动链已核对（含虚拟环境启动层）：',','.join(map(str,allowed)),'；另有任务：',len(workers),'个。',flush=True)
    return workers

SCHEDULES=r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$d=[Console]::In.ReadToEnd() | ConvertFrom-Json
if(-not(Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue)){throw 'ScheduledTasks cmdlets unavailable'}
$selected=@();$preserved=@()
foreach($t in @(Get-ScheduledTask | Where-Object {$_.TaskName -like 'FBUpload-*'})){
  $a=@($t.Actions);$tr=@($t.Triggers);$known=$false
  if($a.Count -eq 1 -and $a[0].WorkingDirectory -eq $d.root -and $a[0].Execute -eq $d.python){
    foreach($s in $d.scripts){
      $arg=[string]$a[0].Arguments
      if($arg.StartsWith($s+' ',[StringComparison]::OrdinalIgnoreCase) -or $arg.StartsWith(('"'+$s+'" '),[StringComparison]::OrdinalIgnoreCase)){$known=$true}
    }
  }
  $old=$false
  if($tr.Count -eq 1 -and $tr[0].CimClass.CimClassName -eq 'MSFT_TaskTimeTrigger' -and -not $tr[0].Repetition.Interval -and $tr[0].StartBoundary){
    $old=[DateTimeOffset]::Parse($tr[0].StartBoundary) -lt [DateTimeOffset]::Parse($d.cutoff)
  }
  if(-not($known -and $old)){$preserved+=$t.TaskName;continue}
  if([string]$t.State -eq 'Running'){throw 'An old publisher schedule is still running; close it normally first'}
  $xml=Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath
  $file=Join-Path $d.backup (([Guid]::NewGuid().ToString('N'))+'.xml')
  [IO.File]::WriteAllText($file,$xml,[Text.UTF8Encoding]::new($false))
  $selected+=[pscustomobject]@{TaskName=$t.TaskName;TaskPath=$t.TaskPath;Xml=$file;State=[string]$t.State}
}
[IO.File]::WriteAllText((Join-Path $d.backup 'scheduled-tasks.json'),(ConvertTo-Json -InputObject @($selected) -Depth 5),[Text.UTF8Encoding]::new($false))
$removed=@()
try{
  foreach($t in $selected){
    $live=Get-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath
    if([string]$live.State -eq 'Running'){throw 'A publisher started meanwhile; no forced termination'}
    if((Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath) -ne [IO.File]::ReadAllText($t.Xml)){throw 'Schedule changed after backup'}
    Unregister-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Confirm:$false
    $removed+=$t
  }
}catch{
  foreach($t in $removed){Register-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Xml ([IO.File]::ReadAllText($t.Xml)) | Out-Null}
  throw
}
ConvertTo-Json -InputObject @{removed=@($removed | ForEach-Object {$_.TaskName});preserved=@($preserved)} -Compress
'''


def require_day():
    if datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()!=DAY:
        raise ValueError('此入口仅用于11月16日续发已确认实拍的11月14日素材；未修改原日期。')


def assert_idle():
    workers=active_workers(first.upload.ROOT)
    if workers:
        details='；'.join(str(r['pid'])+'（'+r.get('kind','Python任务')+'）' for r in workers)
        raise RuntimeError('排除本次启动链后仍有任务：'+details+'。请先在对应旧发布/导入/登录检查窗口按Ctrl+C正常退出，再运行本指令；没有强制结束进程或导入新素材。')


def retire_queues():
    require_day();assert_idle()
    root=first.upload.ROOT
    backup=root/'backups'/('nov16-retired-old-queues-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
    data=dict(root=str(root),python=str(root/'.venv/Scripts/python.exe'),backup=str(backup),cutoff=DAY+'T00:00:00+08:00',
              scripts=[str(root/n) for n in ('run_scheduled_batch.py','scheduled_material_batch.py','scheduled_priority_workflow.py')])
    if sys.platform!='win32':raise ValueError('旧任务检查必须在原Windows电脑执行。')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',SCHEDULES],input=json.dumps(data).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,creationflags=0x08000000)
    if result.returncode:raise RuntimeError('旧计划任务未能安全核对/清理，发布尚未开始；已保留备份，请发回此窗口结果。')
    receipt=json.loads(result.stdout.decode('utf-8-sig'))
    if not isinstance(receipt,dict) or not all(isinstance(receipt.get(k),list) for k in ('removed','preserved')):raise ValueError('旧计划任务清理回执异常。')
    # Retire the obsolete waiting pointer only. Frozen manifests and state remain
    # available for provenance, idempotency and receipt reconciliation.
    with first.locked():
        pointer=root/'logs'/staged.POINTER
        if pointer.exists():
            saved=first.upload.read_json(pointer,{})
            name=saved.get('manifest','')
            if not re.fullmatch(r'frozen-material-2026-11-14-[a-f0-9]{16}\.json',name):raise ValueError('旧等待指针异常，未移除。')
            origin=first.archive.checked_json(root/'logs'/name)
            if saved.get('sha256')!=origin['sha256'] or origin['payload'].get('distributed_scope')!=staged.SCOPE:raise ValueError('旧等待指针来源不符，未移除。')
            shutil.copy2(pointer,backup/pointer.name);pointer.unlink()
        first.upload.save_json(backup/'receipt.json',dict(date=DAY,scheduled_tasks=receipt,retired_pointer=staged.POINTER if (backup/staged.POINTER).is_file() else None))
    print('旧执行队列已检查；移除过期计划任务',len(receipt['removed']),'个。历史发布状态、冻结清单和素材均保留。备份：',backup,flush=True)
    return backup


def manual_launcher(pw,entry):
    if entry.get('_local_file_selfcheck') is True:return NORMAL(pw,entry)
    if entry['account'] in SKIPPED:raise repair.SessionNotReady('此账号本轮已由用户暂跳过；保留其他目标。')
    context=None
    try:
        context=NORMAL(pw,entry)
        page=context.pages[-1] if context.pages else context.new_page()
        repair.wait_session(page);first.upload.ensure_identity(page,entry)
        return context
    except KeyboardInterrupt:
        if context is not None:context.close()
        raise
    except Exception as error:
        if context is not None:context.close()
        issue=staged.guided.brief(error)
        if issue['code']=='profile_busy':raise
        print('此账号需手动检查：',entry['account'],entry['target'],issue['message'],flush=True)
    # Only login/identity/network recovery here: owner and target remain immutable.
    with patch.object(first.normal.background,'mode',return_value='foreground'):
        context=NORMAL(pw,dict(entry,_local_file_selfcheck=True))
    try:
        page=context.pages[-1] if context.pages else context.new_page()
        try:first.upload.navigate_profile(page,entry['url'])
        except Exception:print('检查窗口已保留，请检查网络或完成官方登录验证。',flush=True)
        while True:
            answer=input('在此账号窗口处理登录/验证；回车重新核验，R重开目标主页，S跳过此账号，Q暂停：').strip().lower()
            require_day()
            if answer=='q':raise KeyboardInterrupt
            if answer=='s':
                SKIPPED.add(entry['account'])
                raise repair.SessionNotReady('用户暂跳过此账号；未选择或发布视频。')
            if answer=='r':
                try:first.upload.navigate_profile(page,entry['url'])
                except Exception:print('主页暂未打开，请检查网络。',flush=True)
                continue
            if answer:continue
            try:
                repair.wait_session(page);first.upload.ensure_identity(page,entry)
            except Exception as error:
                print('核验未通过：',staged.guided.brief(error)['message'],flush=True);continue
            try:
                session=page.context.new_cdp_session(page)
                window=session.send('Browser.getWindowForTarget')
                session.send('Browser.setWindowBounds',dict(windowId=window['windowId'],bounds=dict(windowState='minimized')))
                session.detach()
            except Exception:print('身份已通过，可手动最小化此检查窗口。',flush=True)
            print('已通过原登记身份核验，继续此原视频；无需重新填写名称。',flush=True)
            return context
    except BaseException:context.close();raise


@contextlib.contextmanager
def browser_fixes():
    SKIPPED.clear()
    with patch.object(first.normal.background,'mode',return_value='background'), \
         patch.object(first.normal,'launch_normal',side_effect=manual_launcher), \
         patch.object(first.numeric,'ensure',side_effect=staged.page_identity), \
         patch.object(first.personals,'ensure_personal',side_effect=lambda page,entry:repair.ensure_background_identity(staged.PERSONAL,page,entry)):
        yield


def stage_parents(material):
    parents={};by_pair={}
    for path in sorted((first.upload.ROOT/'logs').glob('frozen-material-2026-11-14-*.json')):
        if not re.fullmatch(r'frozen-material-2026-11-14-[a-f0-9]{16}\.json',path.name):continue
        value=first.upload.read_json(path,{})
        if value.get('payload',{}).get('distributed_scope')!=staged.SCOPE:continue
        value=first.archive.checked_json(path);first.workflow.validate(path,value);p=value['payload']
        if p.get('distribution_sha256')!=material['sha256'] or p.get('ai_label') is not False:raise ValueError('14号原发布清单与暂存素材不一致。')
        assignments={(r['account'],r['target']):r for r in material['payload']['assignments']}
        for j in p['jobs']:
            pair=j['account'],j['target'];f=assignments.get(pair,{}).get('files',[{}])[-1]
            if (j['filename'],j['video_sha256'],j['video_size'])!=(f.get('destination_name'),f.get('sha256'),f.get('size')):raise ValueError('14号原发布文件与暂存清单不符。')
            if pair in by_pair and by_pair[pair]!=j:raise ValueError('原批次存在同目标不同任务，未猜选。')
            by_pair[pair]=j
        parents[path.name]=value
    return parents,by_pair


def freeze_stage():
    material_path,material,rows,duplicates=first.distribution()
    source_path,source=staged.checked_stage();parents,by_pair=stage_parents(material)
    pointer=first.upload.ROOT/'logs'/POINTER
    def validate(path,value):
        first.validate(path,value,material);p=value['payload']
        if (p.get('material_source_date')!=MATERIAL_DAY or p.get('stage_sha256')!=source['sha256']
                or p.get('source_plans')!={k:v['sha256'] for k,v in parents.items()}
                or p.get('old_material_files')!=[]):raise ValueError('新续跑清单来源变化。')
    saved=first.upload.read_json(pointer,None)
    owned=[]
    for path in (first.upload.ROOT/'logs').glob('frozen-material-'+DAY+'-*.json'):
        if not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json',path.name):continue
        value=first.upload.read_json(path,{})
        if value.get('payload',{}).get('distributed_scope')==SCOPE:
            validate(path,value);owned.append((path,value))
    if len(owned)>1:raise ValueError('同一新素材批次存在多个续跑清单。')
    if saved:
        if not owned or saved!={'manifest':owned[0][0].name,'sha256':owned[0][1]['sha256']}:raise ValueError('续跑指针与原清单不符。')
        return owned[0]
    if owned:
        path,value=owned[0];first.upload.save_json(pointer,dict(manifest=path.name,sha256=value['sha256']));return path,value
    content=first.batch.preferences.content_policy(MATERIAL_DAY);policy=first.batch.preferences.load(DAY)
    if (not content or content['payload']['caption']!=first.batch.preferences.EVERYDAY_CAPTION
            or content['payload']['comment']!=first.batch.preferences.EVERYDAY_COMMENT):raise ValueError('原正文或评论版本不符。')
    config=first.upload.read_json(first.upload.CONFIG,{});state=first.upload.read_json(first.upload.ROOT/'logs/publish_state.json',{})
    urls=Counter(first.upload.target_key(e['url']) for e in config.get('targets',[]) if e.get('account') in staged.ALLOWED and e.get('url'))
    previous=first.batch.previous_plan_keys(DAY);jobs=[];issues=[];changed=False
    for row in rows:
        account,target=row['account'],row['target'];pair=account,target;f=row['files'][-1]
        try:
            if pair in by_pair:jobs.append(copy.deepcopy(by_pair[pair]));continue
            entries=[e for e in config.get('targets',[]) if (e.get('account'),e.get('target'))==pair]
            if len(entries)!=1:raise ValueError('没有唯一已登记目标')
            entry=entries[0];first.upload.validate_entry(entry)
            if urls[first.upload.target_key(entry['url'])]!=1:raise ValueError('主页登记重复，未猜选')
            if row.get('url') and first.upload.target_key(row['url'])!=first.upload.target_key(entry['url']):raise ValueError('原登记身份变化')
            if not first.batch.eligible(entry,True,date=DAY):raise ValueError('目标尚未允许发布')
            if not (first.upload.ROOT/'profiles'/account).is_dir():raise ValueError('原浏览器资料缺失')
            filename=f['destination_name'];first.upload.validate_video_filename(filename)
            video=first.archive.safe(first.upload.inbox_for(entry)/filename)
            if first.archive.info(video)!=dict(size=f['size'],sha256=f['sha256']):raise ValueError('原素材缺失或指纹变化')
            key=first.upload.job_key(entry,video)
            if key in state or key in previous or account+'/'+target in duplicates:raise ValueError('已有其他任务记录，保留原状态，不重发')
            caption=video.with_suffix('.txt');text=content['payload']['caption']
            if not caption.is_file() or caption.read_text(encoding='utf-8-sig').strip()!=text:
                backup=first.upload.ROOT/'backups'/('nov16-caption-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
                if caption.is_file():shutil.copy2(caption,backup/caption.name)
                first.atomic_caption(caption,text);changed=True
            jobs.append(dict(account=account,target=target,filename=filename,key=key,url=entry['url'],entry_sha256=first.batch.digest(entry),
                             caption_text=text,caption_sha256=first.batch.file_hash(caption),video_size=f['size'],video_sha256=f['sha256'],publication_content_sha256=content['sha256']))
        except Exception as error:issues.append(dict(account=account,target=target,filename=f['destination_name'],reason=str(error)))
    if not jobs:raise ValueError('没有可处理的原44条素材：'+str(issues))
    now=datetime.now(timezone.utc)
    p=dict(schema=first.batch.SCHEMA,date=DAY,start=(now+timedelta(seconds=75 if changed else 0)).isoformat(),requested_start=now.isoformat(),
           ai_label=False,include_fb10_pages=True,excluded_accounts=sorted(first.batch.excluded_accounts(DAY)),jobs=jobs,comment_text=content['payload']['comment'],
           publication_content_sha256=content['sha256'],publication_preferences_sha256=policy['sha256'],comment_retry_policy=first.priority.COMMENT_RECOVERY_VERSION,
           distributed_scope=SCOPE,intended_accounts=sorted(staged.ALLOWED),distribution_manifest=first.archive.relative(material_path),distribution_sha256=material['sha256'],
           old_material_files=[],material_source_date=MATERIAL_DAY,stage_sha256=source['sha256'],source_plans={k:v['sha256'] for k,v in parents.items()})
    value=dict(payload=p,sha256=first.batch.digest(p),created_at=now.isoformat(),issues=issues,workflow='future-video-comments-v1',auto_retry_policy=first.priority.retry.POLICY,
               comment_timing=first.priority.TIMING,priority_workflow=first.priority.PRIORITY_WORKFLOW_VERSION,report_format='text',scheduled_priority_runner=first.workflow.VERSION,
               browser_launch_mode=first.normal.NORMAL_CHROME_VERSION,local_file_input_mode=first.local.VERSION)
    path=first.upload.ROOT/'logs'/('frozen-material-'+DAY+'-'+value['sha256'][:16]+'.json');validate(path,value)
    first.upload.save_json(path,value);first.upload.save_json(pointer,dict(manifest=path.name,sha256=value['sha256']));return path,value


def publish_stage():
    require_day();source_path,source=staged.checked_stage();material=source['payload']['distribution']
    assert_idle();staged.lock_recovery.recover_locks(first.upload.ROOT)
    with patch.object(staged.stage,'active_workers',side_effect=active_workers):staged.stage.import_stage(first.upload.ROOT,source_path)
    journal=first.upload.ROOT/'logs/material-distribution'/staged.SOURCE_ID/(MATERIAL_DAY+'.json')
    def bound(relative=None):
        if relative is not None and (first.upload.ROOT/relative).resolve()!=journal.resolve():raise ValueError('本批只接受14号原暂存清单。')
        result=staged.DISTRIBUTION(first.archive.relative(journal))
        if result[1]['sha256']!=material['sha256']:raise ValueError('原分配清单变化。')
        return result
    def reconcile(path,value):
        RECONCILE(path,value)
        parents,_=stage_parents(material);keys={j['key'] for j in value['payload']['jobs']}
        for name,parent in parents.items():
            view=copy.deepcopy(parent);view['payload']['jobs']=[j for j in parent['payload']['jobs'] if j['key'] in keys]
            if view['payload']['jobs']:RECONCILE(first.upload.ROOT/'logs'/name,view)
    recover=first.recover_own
    def recover_parents(path,value):
        parents,_=stage_parents(material)
        for name,parent in parents.items():recover(first.upload.ROOT/'logs'/name,parent)
        return recover(path,value)
    print('开始11月14日原44条素材：fb17继续暂跳过，其余43个目标；沿用原正文和评论，已提交结果先核实。',flush=True)
    with patch.object(first,'DAY',DAY),patch.object(first,'MATERIAL_DAY',MATERIAL_DAY),patch.object(first,'SCOPE',SCOPE),patch.object(first,'POINTER',POINTER), \
         patch.object(first,'ALLOWED',staged.ALLOWED),patch.object(first,'WAVE_LABEL','11月14日原素材续发'),patch.object(first,'WAVE_DESCRIPTION','fb01–fb24及公共主页（fb17暂跳过）'), \
         patch.object(first,'distribution',side_effect=bound),patch.object(first,'freeze',side_effect=freeze_stage),patch.object(first,'reconcile',side_effect=reconcile),patch.object(first,'recover_own',side_effect=recover_parents), \
         patch.object(first,'pause_archived_history',return_value=None),patch.object(first.archive,'today_files',side_effect=staged.protect_other_materials):
        RUN(True)
        # The user's explicit repair grant also covers a carried Nov14
        # pre-Post failure or a failure outside the transient-network allowlist.
        # One durable extra chance, and no chance at all after any submission.
        path,value=freeze_stage();parents,_=stage_parents(material)
        bindings=[dict(manifest=path.name,sha256=value['sha256'])]+[dict(manifest=k,sha256=v['sha256']) for k,v in parents.items()]
        with patch.object(repair,'GRANT','nov16-exact-nov14-stage-prepost-extra-once-v1'), \
             patch.object(repair,'source',return_value=(copy.deepcopy(value['payload']['jobs']),bindings,value['payload'])):
            repair.execute()
        report=first.upload.read_json(path.with_name(path.stem+'-results.json'),{})
        rows=first.batch.results(path,value,report.get('attempts',[]),None,final=True)
        return 0 if not value['issues'] and all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows) else 3


def execute():
    require_day();first.workflow.require_versions();staged.stage.setup(first.upload.ROOT)
    staged.checked_stage()  # Preflight the exact original44 before queue changes.
    repair.source()        # Old failure provenance must also be reviewable first.
    assert_idle();staged.lock_recovery.recover_locks(first.upload.ROOT);retire_queues()
    with browser_fixes():
        print('第一阶段：只重试fb01–fb24范围内原批次的明确发布前失败；已成功、待核实及fb17均不重发。',flush=True)
        old_result=repair.execute()
        print('第二阶段：导入并发布11月14日已暂存原素材；不加入fb25及以后账号。',flush=True)
        new_result=publish_stage()
    print('两阶段处理结束。旧记录均保留；请以逐条成功/发布前失败/待核实及评论结果为准。',flush=True)
    return 0 if old_result==new_result==0 else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if first.upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原Windows上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已暂停；保留每条提交和评论记录。11月16日重跑同一指令可继续，已提交视频不重复上传。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
