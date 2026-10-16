"""Create a Windows interactive task using explicit Beijing-time daily triggers."""
import argparse
import base64
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
TASK_NAME = 'FBUpload-Seven-Daily'
BEIJING = timezone(timedelta(hours=8))
NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
ET.register_namespace('', NS)


def next_boundary(time_text, now):
    if not re.fullmatch(r'([01][0-9]|2[0-3]):[0-5][0-9]', time_text):
        raise ValueError('时间需为北京时间 HH:mm，例如20:00')
    local_now = now.astimezone(BEIJING)
    hour, minute = map(int, time_text.split(':'))
    start = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start <= local_now:
        start += timedelta(days=1)
    return start.isoformat(timespec='seconds')


def make_xml(root, times, accounts, rounds, now):
    def add(parent, tag, text=None, **attrs):
        node = ET.SubElement(parent, '{'+NS+'}'+tag, attrs)
        node.text = text
        return node
    task = ET.Element('{'+NS+'}Task', version='1.4')
    info = add(task, 'RegistrationInfo')
    add(info, 'Description', 'Local FB uploader daily batch; Beijing UTC+08:00; interactive desktop required.')
    triggers = add(task, 'Triggers')
    for time_text in times:
        trigger = add(triggers, 'CalendarTrigger')
        add(trigger, 'StartBoundary', next_boundary(time_text, now))
        add(trigger, 'Enabled', 'true')
        add(add(trigger, 'ScheduleByDay'), 'DaysInterval', '1')
    principal = add(add(task, 'Principals'), 'Principal', id='Author')
    add(principal, 'UserId', 'CURRENT_USER')
    add(principal, 'LogonType', 'InteractiveToken')
    add(principal, 'RunLevel', 'LeastPrivilege')
    settings = add(task, 'Settings')
    for tag, value in [('MultipleInstancesPolicy', 'IgnoreNew'), ('DisallowStartIfOnBatteries', 'false'),
                       ('StopIfGoingOnBatteries', 'false'), ('StartWhenAvailable', 'false'),
                       ('RunOnlyIfNetworkAvailable', 'true'), ('Enabled', 'true'),
                       ('WakeToRun', 'false'), ('ExecutionTimeLimit', 'PT2H')]:
        add(settings, tag, value)
    action = add(add(task, 'Actions', Context='Author'), 'Exec')
    add(action, 'Command', str(root / '.venv' / 'Scripts' / 'python.exe'))
    add(action, 'Arguments', '"' + str(root / 'run_scheduled_batch.py') + '" --accounts=' + accounts + ' --rounds=' + str(rounds))
    add(action, 'WorkingDirectory', str(root))
    return ET.tostring(task, encoding='unicode')


def powershell_script(xml):
    payload = base64.b64encode(xml.encode('utf-8')).decode('ascii')
    return """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$existing = @(Get-ScheduledTask | Where-Object { $_.TaskName -like 'FBUpload-*' -and $_.State -ne 'Disabled' })
if ($existing.Count -gt 0) { throw ('Existing FBUpload task(s): ' + (($existing | Select-Object -ExpandProperty TaskName) -join ', ') + '. Check them before creating another schedule.') }
[xml]$taskXml = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('""" + payload + """'))
$taskXml.Task.Principals.Principal.UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
Register-ScheduledTask -TaskName 'FBUpload-Seven-Daily' -Xml $taskXml.OuterXml | Out-Null
$createdTask = Get-ScheduledTask -TaskName 'FBUpload-Seven-Daily'
$taskInfo = Get-ScheduledTaskInfo -TaskName 'FBUpload-Seven-Daily'
[pscustomobject]@{
    TaskName = $createdTask.TaskName
    State = $createdTask.State
    NextRunTimeBeijing = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($taskInfo.NextRunTime, 'China Standard Time')
    LastTaskResult = $taskInfo.LastTaskResult
} | Format-List
"""


def main():
    parser = argparse.ArgumentParser(description='注册七账号定时任务，时间均按北京时间；注册不会立即发布')
    parser.add_argument('--time', help='北京时间，例如20:00；不填则运行时询问；多个时间用逗号分隔')
    parser.add_argument('--accounts', default='fb01,fb02,fb03,fb04,fb05,fb06,fb07')
    parser.add_argument('--rounds', type=int)
    parser.add_argument('--preview', action='store_true', help='只显示任务XML，不注册、不发布')
    args = parser.parse_args()
    if not args.time:
        if args.preview:
            parser.error('--preview 需指定 --time')
        if sys.platform != 'win32':
            raise RuntimeError('请在上传视频的 Windows 电脑运行此注册命令。')
        time_text = input('每天北京时间几点启动？输入 HH:mm，例如20:00：').strip()
        rounds = args.rounds if args.rounds is not None else int(input('每个时间每账号最多几条？直接回车为1：').strip() or '1')
    else:
        time_text = args.time
        rounds = args.rounds if args.rounds is not None else 1
    times = list(dict.fromkeys(value.strip() for value in time_text.split(',')))
    if rounds < 1 or not re.fullmatch(r'[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*', args.accounts):
        parser.error('轮数或账号列表无效')
    xml = make_xml(ROOT, times, args.accounts, rounds, datetime.now(timezone.utc))
    if args.preview:
        print(xml)
        return 0
    if sys.platform != 'win32':
        raise RuntimeError('请在上传视频的 Windows 电脑运行此注册命令。')
    python = ROOT / '.venv' / 'Scripts' / 'python.exe'
    runner = ROOT / 'run_scheduled_batch.py'
    if not python.is_file() or not runner.is_file():
        raise RuntimeError('缺少本地 Python 或 run_scheduled_batch.py。')
    checked = subprocess.run([str(python), str(runner), '--check', '--accounts=' + args.accounts], cwd=str(ROOT), check=False)
    if checked.returncode != 0:
        print('STOP：先处理预检查问题；本次未注册任务，也未发布。')
        return checked.returncode
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', powershell_script(xml)],
                            cwd=str(ROOT), text=True, encoding='utf-8', check=False)
    if result.returncode == 0:
        print('任务已创建，时间按北京时间：', ', '.join(times))
        print('每个时间启动', rounds, '轮；每轮每账号最多一条。注册不会立即发布。')
        print('请保持电脑开机联网、Windows已登录且桌面可用，并关闭占用账号资料的Chrome窗口。')
        print('错过的时间不补发；日志保存在 logs/scheduled-*.log。')
    return result.returncode


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
