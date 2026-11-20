"""Local process classification for material distribution; no publication imports."""
import json,ntpath,os,re,subprocess,sys
from datetime import datetime
from pathlib import Path

WORKER_VERSION='1.1-verified-windows-venv-launch-chain'

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
    r"b=urllib\.request\.urlopen\('https://raw\.githubusercontent\.com/prycken-ux/facebook/[a-f0-9]{40}/downloads/start_distribute_first24_materials_20261116\.py',context=c,timeout=30\)\.read\(131073\);"
    r"hashlib\.sha256\(b\)\.hexdigest\(\)=='[a-f0-9]{64}' or sys\.exit\('Checksum mismatch; stopped'\);"
    r"exec\(compile\(b,'verified-first24-material-distribution','exec'\)\)")

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

def classify_workers(rows,root,pid,runner=None,extra_arguments=()):
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
    if extra_arguments and (not isinstance(extra_arguments,(tuple,list)) or len(extra_arguments)!=1 or not re.fullmatch('[a-f0-9]{64}',extra_arguments[0])):raise ValueError('固定任务指纹参数异常。')
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
        if len(argv)==2+len(extra_arguments) and win_path(argv[0])==runner_key and win_path(argv[1])==root_key and argv[2:]==list(extra_arguments):return 'runner'
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

def active_workers(root,runner,extra_arguments=()):
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',WORKERS],input=b'{}',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,creationflags=0x08000000)
    if result.returncode:raise RuntimeError('发布进程尚未能核对，素材已保留，暂不导入。')
    workers,_=classify_workers(json.loads(result.stdout.decode('utf-8-sig')),root,os.getpid(),runner,extra_arguments=extra_arguments)
    return workers
