"""Persistent user preferences and one exact 17:00 Beijing batch with full workflow."""
import argparse,base64,contextlib,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from xml.etree import ElementTree as ET
import fb_upload as upload
import scheduled_material_batch as batch
import publication_preferences as preferences
import publish_priority_batch as priority
import automatic_batch_retry as retry
import daily_publish_and_comments as daily
import actual_reels_comment_lookup as actual
import normal_chrome_batch as normal
import local_file_input as local
import confirm_all_nov05_20261106 as previous
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

VERSION='1.0-frozen-priority-task'
FRESH_FB24_VERSION='1.0-explicit-new-fb24-only'
SETUP_DATE='2026-11-06'


def require_versions():
    if (upload.VERSION!='2.47' or upload.IMMEDIATE_COMMENT_VERSION!='1.0-receipt-first-reload'
            or batch.PUBLICATION_PREFERENCES_VERSION!=preferences.VERSION
            or normal.LOCAL_FILE_INPUT_COMPATIBILITY!=local.VERSION or local.VERSION!='1.0-verified-local-file-paths'
            or actual.REELS_ENTRY_VERSION!='1.0-owner-route-fallback'
            or retry.FILE_CHOOSER_RETRY_VERSION!='1.0-stage-bound-missing-chooser'
            or retry.VISIBILITY_RETRY_VERSION!='1.0-stage-bound-visibility'):raise ValueError('发布、上传或评论配套程序版本不匹配')


def validate(path,value):
    priority.validate(path,value,value['payload']['date'])
    if (value.get('scheduled_priority_runner')!=VERSION or value.get('browser_launch_mode')!=normal.NORMAL_CHROME_VERSION
            or value.get('local_file_input_mode')!=local.VERSION):raise ValueError('计划不是普通Chrome本机文件优先发布流程')
    for job in value['payload']['jobs']:
        if job['account'] in {'fb25','fb26'}:raise ValueError('已删除账号不进入计划')
        if job['account']=='fb24':
            registry=upload.read_json(upload.ROOT/'additional_personal_accounts.json',{})
            batch_id='personal-20261110-one-fb24';slot=registry.get('slots',{}).get('fb24',{})
            reservation=registry.get('batches',{}).get(batch_id,{})
            if slot.get('batch_id')!=batch_id or reservation.get('accounts')!=['fb24'] or reservation.get('count')!=1:
                raise ValueError('fb24不是用户这次指定并核验的新账号，未恢复旧账号')


def task_xml(path,value):
    task=ET.fromstring(batch.task_xml(path,value));ns={'t':batch.NS}
    task.find('t:RegistrationInfo/t:Description',ns).text='One frozen batch: publish all, one safe retry, verified comments; Beijing 17:00.'
    task.find('t:Actions/t:Exec/t:Arguments',ns).text=subprocess.list2cmdline([str(upload.ROOT/'scheduled_priority_workflow.py'),'run','--manifest',str(path)])
    return ET.tostring(task,encoding='unicode')


def register(path,value):
    if sys.platform!='win32':raise ValueError('请在原Windows电脑注册计划')
    name='FBUpload-Priority-Once-'+value['payload']['date'].replace('-','')+'-'+value['sha256'][:8]
    args=subprocess.list2cmdline([str(upload.ROOT/'scheduled_priority_workflow.py'),'run','--manifest',str(path)])
    data=dict(name=name,xml=task_xml(path,value),root=str(upload.ROOT),arguments=args,python=str(upload.ROOT/'.venv/Scripts/python.exe'),start=value['payload']['start'],
              legacy_scripts=[str(upload.ROOT/n) for n in ('run_scheduled_batch.py','scheduled_material_batch.py','scheduled_priority_workflow.py')])
    payload=base64.b64encode(json.dumps(data).encode()).decode()
    script=r'''$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$d=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD')) | ConvertFrom-Json
$others=@(Get-ScheduledTask | Where-Object {$_.TaskName -like 'FBUpload-*' -and $_.TaskName -ne $d.name -and $_.State -ne 'Disabled' -and @($_.Actions | Where-Object {$_.WorkingDirectory -eq $d.root}).Count -gt 0})
foreach($other in $others){
  if([string]$other.State -eq 'Running'){throw ('Another upload task is running: '+$other.TaskName)}
  $actions=@($other.Actions);$known=$false
  if($actions.Count -eq 1 -and $actions[0].Execute -eq $d.python){
    foreach($knownScript in $d.legacy_scripts){
      $arguments=[string]$actions[0].Arguments
      if($arguments.StartsWith($knownScript+' ',[StringComparison]::OrdinalIgnoreCase) -or $arguments.StartsWith(('"'+$knownScript+'" '),[StringComparison]::OrdinalIgnoreCase)){$known=$true;break}
    }
  }
  if(-not $known){throw ('Unrecognized upload schedule action requires review: '+$other.TaskName)}
}
$existing=Get-ScheduledTask -TaskName $d.name -ErrorAction SilentlyContinue
if($null -eq $existing){
  [xml]$xml=$d.xml; $xml.Task.Principals.Principal.UserId=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $xml.Task.Settings.Enabled='false'
  Register-ScheduledTask -TaskName $d.name -Xml $xml.OuterXml | Out-Null
} else {
  $actions=@($existing.Actions);$triggers=@($existing.Triggers)
  if($actions.Count -ne 1 -or $actions[0].Execute -ne $d.python -or $actions[0].WorkingDirectory -ne $d.root -or $actions[0].Arguments -ne $d.arguments -or $triggers.Count -ne 1 -or $triggers[0].CimClass.CimClassName -ne 'MSFT_TaskTimeTrigger' -or $triggers[0].Repetition.Interval){throw 'Existing task does not match the exact frozen priority workflow'}
  if([DateTimeOffset]::Parse($triggers[0].StartBoundary) -ne [DateTimeOffset]::Parse($d.start)){throw 'Existing task start time differs'}
}
$disabled=@()
try{
  if($others.Count -gt 0){
    $backup=Join-Path $d.root ('backups\replaced-publish-schedules-'+[Guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -Path $backup | Out-Null
    $meta=@()
    for($index=0;$index -lt $others.Count;$index++){
      $other=$others[$index];$file=Join-Path $backup ($index.ToString()+'.xml')
      $oldXml=Export-ScheduledTask -TaskName $other.TaskName -TaskPath $other.TaskPath
      [IO.File]::WriteAllText($file,$oldXml,[Text.UTF8Encoding]::new($false))
      $meta+=[pscustomobject]@{TaskName=$other.TaskName;TaskPath=$other.TaskPath;State=[string]$other.State;Xml=$file}
    }
    [IO.File]::WriteAllText((Join-Path $backup 'tasks.json'),(ConvertTo-Json -InputObject $meta -Depth 5),[Text.UTF8Encoding]::new($false))
    foreach($other in $others){
      $live=Get-ScheduledTask -TaskName $other.TaskName -TaskPath $other.TaskPath
      if([string]$live.State -eq 'Running'){throw ('Another upload task started meanwhile: '+$other.TaskName)}
      Disable-ScheduledTask -TaskName $other.TaskName -TaskPath $other.TaskPath | Out-Null;$disabled+=$other
      Write-Output ('Replaced previous publisher schedule: '+$other.TaskName)
    }
    Write-Output ('Previous publisher schedules backed up: '+$backup)
  }
  Enable-ScheduledTask -TaskName $d.name | Out-Null
} catch {
  try{Disable-ScheduledTask -TaskName $d.name | Out-Null}catch{}
  foreach($old in $disabled){try{Enable-ScheduledTask -TaskName $old.TaskName -TaskPath $old.TaskPath | Out-Null}catch{}}
  throw
}
$t=Get-ScheduledTask -TaskName $d.name; $i=Get-ScheduledTaskInfo -TaskName $d.name
[pscustomobject]@{TaskName=$t.TaskName;State=[string]$t.State;NextRunTimeBeijing=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($i.NextRunTime,'China Standard Time').ToString('yyyy-MM-dd HH:mm:ss');LastTaskResult=$i.LastTaskResult} | ConvertTo-Json -Compress
'''.replace('PAYLOAD',payload)
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,encoding='utf-8',errors='replace',check=False)
    if result.returncode:raise RuntimeError('17点计划未注册：'+result.stderr.strip()[:1600])
    receipt=json.loads(result.stdout.strip().splitlines()[-1])
    if receipt.get('TaskName')!=name or receipt.get('State') not in {'Ready','Running','Queued'}:raise ValueError('计划注册回读状态不一致，需核实')
    print(result.stdout.strip(),flush=True)
    return name


def setup(real_footage):
    require_versions();now=datetime.now(timezone.utc)
    if not real_footage:raise ValueError('今天全批尚未确认实拍')
    if now.astimezone(batch.BJ).date().isoformat()!=SETUP_DATE:raise ValueError('此安装指令仅安排11月6日今天的17点批次')
    previous.execute()  # The user's existing Nov-5 confirmation remains authorized and idempotent.
    with locked():
        policy=preferences.save_authorized();pointer=upload.ROOT/'logs'/('priority-batch-'+SETUP_DATE+'.json');saved=upload.read_json(pointer,None)
        if saved is None:
            path,value=batch.freeze(SETUP_DATE,'17:00',True,daily.COMMENT,now,report_format='text',exclude_previous_plans=True)
            value.update(workflow='future-video-comments-v1',auto_retry_policy=retry.POLICY,comment_timing=priority.TIMING,
                         priority_workflow=priority.PRIORITY_WORKFLOW_VERSION,scheduled_priority_runner=VERSION,
                         browser_launch_mode=normal.NORMAL_CHROME_VERSION,local_file_input_mode=local.VERSION)
            validate(path,value);upload.save_json(path,value)
            upload.save_json(pointer,dict(date=SETUP_DATE,manifest=path.name,sha256=value['sha256']))
        else:
            if (not isinstance(saved,dict) or saved.get('date')!=SETUP_DATE or not isinstance(saved.get('manifest'),str)
                    or Path(saved['manifest']).name!=saved['manifest'] or not saved['manifest'].startswith('frozen-material-'+SETUP_DATE+'-')):raise ValueError('今天原批次指针异常，未另建计划')
            path=upload.ROOT/'logs'/saved['manifest'];value=upload.read_json(path,{})
            if value.get('sha256')!=saved.get('sha256'):raise ValueError('今天续跑指纹不一致')
            validate(path,value)
        report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
        if report and report.get('manifest')!=path.name:raise ValueError('今天结果报告不一致')
        batch.results(path,value,report.get('attempts',[]),None,final=False)
        name=register(path,value)
    print('已注册本次17点优先发布计划：',name,flush=True)
    print('北京时间开始：',value['payload']['start'],'；本批视频：',len(value['payload']['jobs']),'条。',flush=True)
    print('本次及后续跳过 fb16/fb17/fb18/fb21；正文已统一为你提供的原文，购买链接和换行保留。',flush=True)
    print('先全部发布，再对可恢复的发布前失败补发一次，最后自动评论并刷新核验。注册本身未上传。',flush=True)
    print('请保持电脑开机联网、Windows用户已登录。此次只注册今天这一批，不创建每日自动发布。',flush=True)
    return path,value


def run(path):
    require_versions();path=Path(path);path.resolve().relative_to((upload.ROOT/'logs').resolve());value=upload.read_json(path,{})
    validate(path,value);date=value['payload']['date']
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=date:raise ValueError('已经不是本批授权日期，不自动补跑到明天')
    with locked():
        pointer=upload.read_json(upload.ROOT/'logs'/('priority-batch-'+date+'.json'),{})
        if pointer!={'date':date,'manifest':path.name,'sha256':value['sha256']}:raise ValueError('原计划指针不一致')
    original_prepare=priority.prepare;original_launch=upload.launch_context
    upload.launch_context=normal.launcher_for_jobs(value['payload']['jobs'])
    def prepare(requested):
        if requested!=date or upload.read_json(path,{})!=value:raise ValueError('计划在运行期间发生变化')
        validate(path,value)
        with locked():
            state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
            fresh=[j for j in value['payload']['jobs'] if j['key'] not in state and not any(r.get('account')==j['account'] and r.get('status') in {'preparing','posting'} for r in state.values())]
            if fresh:
                from playwright.sync_api import sync_playwright
                job=next((j for j in fresh if j.get('video_size',0)>50*1024*1024),fresh[0]);entry=dict(daily.configured(job),_local_file_selfcheck=True)
                print('先核验本批原文件的本机选取；尚未上传。',flush=True);close_selected_window(entry['account'])
                with sync_playwright() as playwright:
                    context=upload.launch_context(playwright,entry)
                    try:local.self_check(context,job)
                    finally:context.close()
        return path,value
    priority.prepare=prepare
    try:return priority.execute(date,True)
    finally:priority.prepare=original_prepare;upload.launch_context=original_launch


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='按持久规则安排或运行一批优先发布、补发和评论')
    sub=parser.add_subparsers(dest='action',required=True)
    create=sub.add_parser('setup');create.add_argument('--real-footage',action='store_true')
    execute=sub.add_parser('run');execute.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.action=='setup':setup(args.real_footage);raise SystemExit(0)
        log=upload.ROOT/'logs'/('scheduled-priority-'+datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()+'.log')
        with log.open('a',encoding='utf-8') as handle,contextlib.redirect_stdout(batch.Tee(sys.stdout,handle)),contextlib.redirect_stderr(batch.Tee(sys.stderr,handle)):
            raise SystemExit(run(args.manifest))
    except KeyboardInterrupt:print('已停止；发布、补发和评论发送记录保留，未清空重发。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
