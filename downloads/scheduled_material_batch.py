"""Freeze today's exact new media and register one Beijing-time Windows task."""
import argparse
import traceback
import base64
import contextlib
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import fb_upload as upload
from add_fb_accounts import locked
from apply_common_caption import atomic_caption
from diagnose_personal_identity import close_selected_window

BJ=timezone(timedelta(hours=8))
NS='http://schemas.microsoft.com/windows/2004/02/mit/task'
SCHEMA='frozen-scheduled-material-v1'
ET.register_namespace('',NS)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def eligible(entry,include_pages):
    return (re.fullmatch(r'fb(?:0[1-9]|1[0-9]|2[0-3])',str(entry.get('account',''))) is not None
        and entry['account'] not in {'fb16','fb18','fb21'}
        and (include_pages or not (entry['account']=='fb10' and entry.get('type')=='page')))


def start_time(date,time_text,now):
    wanted=datetime.fromisoformat(date+'T'+time_text+':00+08:00')
    if now.astimezone(BJ).date()!=wanted.date():
        raise ValueError('此命令仅用于指定的北京时间当天，不自动移到明天')
    return max(wanted,now.astimezone(BJ)+timedelta(seconds=75)) if wanted<=now else wanted


def freeze(date,time_text,include_pages,comment,now):
    if upload.VERSION not in {'2.38','2.39','2.40','2.41','2.42','2.43','2.44'}:raise ValueError('需安装配套上传核心 2.38～2.44')
    if not comment.strip() or len(comment)>5000:raise ValueError('评论文案为空或过长')
    effective=start_time(date,time_text,now)
    config=upload.read_json(upload.CONFIG,{})
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    entries=[e for e in config.get('targets',[]) if eligible(e,include_pages)]
    urls=Counter(upload.target_key(e['url']) for e in entries)
    pairs=Counter((e['account'],e['target']) for e in entries)
    common_path=upload.ROOT/'common_caption_today.txt'
    common=common_path.read_text(encoding='utf-8-sig').strip() if common_path.is_file() else ''
    backup=upload.ROOT/'backups'/('scheduled-captions-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    jobs=[];issues=[];seen=set()
    for entry in sorted(entries,key=lambda e:(e['account'],e['target'])):
        pair=entry['account'],entry['target']
        try:
            upload.validate_entry(entry)
            if urls[upload.target_key(entry['url'])]!=1 or pairs[pair]!=1:raise ValueError('配置的目标重复')
            folder=upload.inbox_for(entry)
            if not folder.is_dir():continue
            for video in sorted(folder.iterdir(),key=upload.queue_order):
                if not video.is_file() or video.suffix.lower()!='.mp4':continue
                try:
                    upload.validate_video_filename(video.name)
                    video.resolve().relative_to(folder.resolve())
                    if video.name.lower() in {str(n).lower() for n in entry.get('excluded_files',[])}:
                        issues.append(dict(account=pair[0],target=pair[1],filename=video.name,reason='文件名在原排除名单，未自动解除；请手动核实'))
                        continue
                    before=video.stat()
                    if not before.st_size:raise ValueError('视频为空')
                    key=upload.job_key(entry,video)
                    after=video.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('视频正在复制，未冻结')
                    if key in state:
                        if state[key].get('status')!='published':
                            issues.append(dict(account=pair[0],target=pair[1],filename=video.name,key=key,
                                reason='原素材已有记录，保留不重发：'+state[key].get('status','unknown')))
                        continue
                    if key in seen:
                        issues.append(dict(account=pair[0],target=pair[1],filename=video.name,reason='同内容不同名重复文件，已只选择一份'))
                        continue
                    caption=video.with_suffix('.txt')
                    caption.resolve().relative_to(folder.resolve())
                    text=caption.read_text(encoding='utf-8-sig').strip() if caption.is_file() else ''
                    if not text:
                        if not common:raise ValueError('无现有文案，已保存的统一文案也为空')
                        backup.mkdir(parents=True,exist_ok=True)
                        if caption.exists():
                            saved=backup/caption.relative_to(upload.ROOT);saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(caption,saved)
                        atomic_caption(caption,common)
                        text=common
                    jobs.append(dict(account=pair[0],target=pair[1],filename=video.name,key=key,url=entry['url'],
                        entry_sha256=digest(entry),caption_text=text,caption_sha256=file_hash(caption),video_size=after.st_size))
                    seen.add(key)
                except Exception as error:
                    issues.append(dict(account=pair[0],target=pair[1],filename=video.name,reason=str(error)))
        except Exception as error:
            issues.append(dict(account=pair[0],target=pair[1],reason=str(error)))
    if not jobs:raise ValueError('没有可冻结的全新视频，未创建空计划；已有记录的素材不会重发')
    payload=dict(schema=SCHEMA,date=date,requested_start=date+'T'+time_text+':00+08:00',start=effective.isoformat(),
        ai_label=False,include_fb10_pages=include_pages,excluded_accounts=['fb16','fb18','fb21'],
        comment_text=comment,jobs=jobs)
    checksum=digest(payload)
    path=upload.ROOT/'logs'/('frozen-material-'+date+'-'+checksum[:16]+'.json')
    manifest=dict(payload=payload,sha256=checksum,created_at=now.isoformat(),issues=issues)
    if path.exists():
        existing=upload.read_json(path,{})
        if existing.get('payload')!=payload or existing.get('sha256')!=checksum:raise ValueError('同名冻结计划不一致，未覆盖')
        manifest=existing
    else:upload.save_json(path,manifest)
    with path.with_suffix('.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['account','target','filename','key','url','caption_text'],extrasaction='ignore')
        writer.writeheader();writer.writerows(jobs)
    return path,manifest


def task_xml(path,manifest):
    def add(parent,name,value=None,**attrs):
        element=ET.SubElement(parent,'{'+NS+'}'+name,attrs);element.text=value;return element
    task=ET.Element('{'+NS+'}Task',version='1.4')
    add(add(task,'RegistrationInfo'),'Description','One frozen media batch; Beijing UTC+08; authorized publication and comments.')
    trigger=add(add(task,'Triggers'),'TimeTrigger')
    add(trigger,'StartBoundary',manifest['payload']['start']);add(trigger,'Enabled','true')
    principal=add(add(task,'Principals'),'Principal',id='Author')
    add(principal,'UserId','CURRENT_USER');add(principal,'LogonType','InteractiveToken');add(principal,'RunLevel','LeastPrivilege')
    settings=add(task,'Settings')
    for key,value in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),
        ('StopIfGoingOnBatteries','false'),('AllowHardTerminate','false'),('StartWhenAvailable','true'),
        ('RunOnlyIfNetworkAvailable','false'),('Enabled','true'),('WakeToRun','true'),('ExecutionTimeLimit','PT0S')]:
        add(settings,key,value)
    action=add(add(task,'Actions',Context='Author'),'Exec')
    add(action,'Command',str(upload.ROOT/'.venv/Scripts/python.exe'))
    add(action,'Arguments',subprocess.list2cmdline([str(upload.ROOT/'scheduled_material_batch.py'),'run','--manifest',str(path)]))
    add(action,'WorkingDirectory',str(upload.ROOT))
    return ET.tostring(task,encoding='unicode')


def register(path,manifest):
    if sys.platform!='win32':raise RuntimeError('计划任务必须在 Windows 上传电脑注册')
    name='FBUpload-Once-'+manifest['payload']['date'].replace('-','')+'-'+manifest['sha256'][:8]
    payload=base64.b64encode(json.dumps(dict(name=name,xml=task_xml(path,manifest),root=str(upload.ROOT),manifest=str(path))).encode()).decode()
    script=r'''$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$d=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD')) | ConvertFrom-Json
$existing=Get-ScheduledTask -TaskName $d.name -ErrorAction SilentlyContinue
if($null -eq $existing){
  $conflicts=@(Get-ScheduledTask | Where-Object {$_.TaskName -like 'FBUpload-*' -and $_.State -ne 'Disabled' -and @($_.Actions | Where-Object {$_.WorkingDirectory -eq $d.root}).Count -gt 0})
  if($conflicts.Count -gt 0){throw ('Other uploader schedules require review: '+(($conflicts.TaskName)-join ', '))}
  [xml]$xml=$d.xml
  $xml.Task.Principals.Principal.UserId=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  Register-ScheduledTask -TaskName $d.name -Xml $xml.OuterXml | Out-Null
} else {
  $actions=@($existing.Actions)
  if($actions.Count -ne 1 -or -not $actions[0].Arguments.Contains($d.manifest)){throw 'Existing task does not match this frozen manifest'}
}
$t=Get-ScheduledTask -TaskName $d.name
$i=Get-ScheduledTaskInfo -TaskName $d.name
[pscustomobject]@{TaskName=$t.TaskName;State=[string]$t.State;NextRunTimeBeijing=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($i.NextRunTime,'China Standard Time').ToString('yyyy-MM-dd HH:mm:ss');Manifest=$d.manifest} | ConvertTo-Json -Compress
'''.replace('PAYLOAD',payload)
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,encoding='utf-8',errors='replace',check=False)
    if result.returncode:raise RuntimeError('计划任务未注册：'+result.stderr.strip()[:1600])
    print(result.stdout.strip(),flush=True)
    return name


def validate_job(job):
    config=upload.read_json(upload.CONFIG,{})
    entries=[e for e in config.get('targets',[]) if (e.get('account'),e.get('target'))==(job['account'],job['target'])]
    if len(entries)!=1 or digest(entries[0])!=job['entry_sha256']:raise ValueError('目标配置已变化，未替换目标')
    entry=entries[0];video=upload.inbox_for(entry)/job['filename'];caption=video.with_suffix('.txt')
    if not video.is_file() or upload.job_key(entry,video)!=job['key']:raise ValueError('原视频缺失或内容变化，未选择其他文件')
    if not caption.is_file() or file_hash(caption)!=job['caption_sha256']:raise ValueError('冻结后的文案发生变化，未使用其他文案')
    return entry


def results(path,manifest,attempts,output_dir,final=False):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    rows=[]
    for job in manifest['payload']['jobs']:
        record=state.get(job['key'],{})
        attempt=next((a for a in reversed(attempts) if a['key']==job['key']),{})
        rows.append(dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],
            video_status=record.get('status','not_started'),comment_status=record.get('comment_status','not_started'),
            reason=attempt.get('error') or record.get('comment_error') or record.get('error',''),permalink=record.get('permalink','')))
    report=dict(schema='scheduled-material-results-v1',manifest=path.name,created_at=datetime.now(timezone.utc).isoformat(),rows=rows,
        setup_issues=manifest.get('issues',[]),attempts=attempts)
    report_path=path.with_name(path.stem+'-results.json');upload.save_json(report_path,report)
    csv_path=report_path.with_suffix('.csv')
    with csv_path.open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['account','target','filename','video_status','comment_status','reason','permalink','key'])
        writer.writeheader();writer.writerows(rows)
    destination=Path(output_dir) if output_dir else upload.ROOT/'logs'
    if not destination.is_dir():destination=upload.ROOT/'logs'
    label='八个失败目标重发-' if manifest['payload'].get('run_kind')=='retry-oct30-eight' else '今日定时发布与评论-'
    output=destination/(label+manifest['payload']['date']+'-'+manifest['sha256'][:8]+'.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(report_path,'results.json');archive.write(csv_path,'results.csv')
        for job in manifest['payload']['jobs']:
            for prefix in ['review-','comment-','batch-']:
                for suffix in ['.png','-error.txt','.aria.txt']:
                    artifact=upload.ROOT/'logs'/(prefix+job['key'][:12]+suffix)
                    if artifact.is_file():archive.write(artifact,artifact.name)
    print('本批状态：',dict(Counter(r['video_status'] for r in rows)),flush=True)
    print('评论状态：',dict(Counter(r['comment_status'] for r in rows)),flush=True)
    for row in rows:
        if not final and not any(a['key']==row['key'] for a in attempts):continue
        if row['video_status']!='published' or row['comment_status'] not in {'sent','already_present'}:
            print('需手动核实：',row['account']+'/'+row['target'],row['filename'],row['video_status'],row['comment_status'],str(row['reason']).split('\n',1)[0],flush=True)
    print('完整结果：',output,flush=True)
    return rows


class Tee:
    def __init__(self,*streams):self.streams=streams
    def write(self,text):
        for stream in self.streams:stream.write(text);stream.flush()
        return len(text)
    def flush(self):
        for stream in self.streams:stream.flush()


def run(path,output_dir=None,before_job=None,defer_comments=False,retry_before_post=False):
    path=Path(path)
    path.resolve().relative_to((upload.ROOT/'logs').resolve())
    manifest=upload.read_json(path,{})
    payload=manifest.get('payload',{})
    if payload.get('schema')!=SCHEMA or digest(payload)!=manifest.get('sha256'):raise ValueError('冻结计划校验失败')
    now=datetime.now(timezone.utc)
    if now.astimezone(BJ).date().isoformat()!=payload['date']:raise ValueError('已不是本批授权日期，不补跑过期计划')
    if now<datetime.fromisoformat(payload['start']):raise ValueError('尚未到指定开始时间，不提前发布')
    if upload.VERSION not in {'2.38','2.39','2.40','2.41','2.42','2.43','2.44'}:raise ValueError('上传核心版本不匹配')
    attempts=[]
    with locked(),path.with_suffix('.log').open('a',encoding='utf-8') as log:
        with contextlib.redirect_stdout(Tee(sys.stdout,log)),contextlib.redirect_stderr(Tee(sys.stderr,log)):
            try:
                for job in payload['jobs']:
                    attempt=dict(account=job['account'],target=job['target'],key=job['key'],started_at=datetime.now(timezone.utc).isoformat())
                    try:
                        state_path=upload.ROOT/'logs/publish_state.json';state=upload.read_json(state_path,{})
                        old=state.get(job['key'],{})
                        can_retry=(retry_before_post and old.get('status')=='failed_before_post'
                            and not any(old.get(k) for k in ('success_message','permalink','confirmation_method','confirmed_at','post_intent_at','today_first_retry_used')))
                        if job['key'] in state and not can_retry:
                            print('原素材已有记录，不重发：',job['account'],job['filename'],state[job['key']].get('status'),flush=True)
                            attempt['action']='existing_record';continue
                        if any(r.get('account')==job['account'] and r.get('status') in {'preparing','posting'} for r in state.values()):
                            raise RuntimeError('该账号仍有准备中或提交中的旧任务，不关闭其浏览器、不解除记录；需手动核实')
                        entry=validate_job(job)
                        if before_job is not None:
                            before_job(job)
                            state=upload.read_json(state_path,{})
                        close_selected_window(entry['account'])
                        entry=dict(entry,enabled=True,auto_switch_personal=True,_authorized_comment_text=payload['comment_text'])
                        print('\n开始本批原视频：',job['account'],job['target'],job['filename'],flush=True)
                        upload.run_entry(entry,state,state_path,True,filename=job['filename'],ai_label_override=False,
                            expected_job_key=job['key'],preserve_old_review_for_exact_job=True,
                            defer_comments=defer_comments,retry_before_post=can_retry)
                        attempt['action']='finished'
                    except KeyboardInterrupt:
                        attempt.update(action='interrupted',error='用户中断，保留原状态，禁止直接重复发布');raise
                    except Exception as error:
                        message=str(error).strip() or type(error).__name__
                        attempt.update(action='manual_required',error=message)
                        try:(upload.ROOT/'logs'/('batch-'+job['key'][:12]+'-error.txt')).write_text(traceback.format_exc(),encoding='utf-8')
                        except OSError:pass
                        print('此目标停止并保留记录，继续其他确切素材：',message.split('\n',1)[0],flush=True)
                    finally:
                        attempts.append(attempt)
                        results(path,manifest,attempts,output_dir)
            finally:rows=results(path,manifest,attempts,output_dir,final=True)
    return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows) else 3


def setup(args):
    now=datetime.now(timezone.utc)
    with locked():
        path,manifest=freeze(args.date,args.time,args.include_fb10_pages,Path(args.comment_file).read_text(encoding='utf-8-sig').strip(),now)
        if args.output_dir:
            manifest['output_dir']=str(args.output_dir);upload.save_json(path,manifest)
        print('已冻结全新视频：',len(manifest['payload']['jobs']),'条；AI 标签 off',flush=True)
        print('北京时间开始：',manifest['payload']['start'],flush=True)
        print('有同名文案保留；没有文案的已补统一文案。计划清单：',path.with_suffix('.csv'),flush=True)
        for issue in manifest.get('issues',[]):print('需核实/跳过：',issue,flush=True)
        if args.preview:print(task_xml(path,manifest));return 0
        register(path,manifest)
    print('计划注册完成。请保持电脑开机联网，当前 Windows 用户已登录；任务只运行本批一次。',flush=True)
    return 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='当前新视频的北京时间一次性发布及授权顶层评论')
    sub=parser.add_subparsers(dest='action',required=True)
    prepare=sub.add_parser('setup');prepare.add_argument('--date',required=True);prepare.add_argument('--time',default='17:00')
    prepare.add_argument('--include-fb10-pages',action='store_true');prepare.add_argument('--comment-file',required=True)
    prepare.add_argument('--output-dir',type=Path);prepare.add_argument('--preview',action='store_true')
    execute=sub.add_parser('run');execute.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.action=='setup':raise SystemExit(setup(args))
        stored=upload.read_json(args.manifest,{})
        raise SystemExit(run(args.manifest,stored.get('output_dir')))
    except KeyboardInterrupt:
        print('已中断，保留记录。',flush=True);raise SystemExit(130)
    except Exception as error:
        print('STOP：',error,flush=True);raise SystemExit(1)
