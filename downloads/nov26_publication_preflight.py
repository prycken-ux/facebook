"""One read-only snapshot of the exact FB profiles; keep IG tasks separate."""
import json,os,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import material_distribution_worker_check as workers
QUERY=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$p=[Console]::In.ReadToEnd() | ConvertFrom-Json
$prefix=(Join-Path $p.root 'profiles').TrimEnd('\')+'\'
$rows=@(foreach($r in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")){
 $cmd=[string]$r.CommandLine
 if($cmd -match '(?i)(?:^|\s)--type(?:=|\s)'){continue}
 $m=[regex]::Match($cmd,'(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
 if(-not $m.Success){continue}
 $path=if($m.Groups[1].Success){$m.Groups[1].Value}else{$m.Groups[2].Value}
 $path=[IO.Path]::GetFullPath($path).TrimEnd('\')
 if(-not $path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){continue}
 $a=$path.Substring($prefix.Length)
 if($a -in $p.accounts){[pscustomobject]@{account=$a;pid=[long]$r.ProcessId;created=$r.CreationDate.ToUniversalTime().ToString('o')}}
})
ConvertTo-Json -InputObject @($rows) -Compress
'''

def inspect_workers(root,runner,bootstrap):
 r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',workers.WORKERS],input=b'{}',capture_output=True,timeout=20,creationflags=0x08000000)
 if r.returncode:raise RuntimeError('无法核对FB任务，未另开发布')
 rows=json.loads(r.stdout.decode('utf-8-sig'));kept=[]
 for row in rows:
  try:args=workers.win_args(row['command'])
  except ValueError:args=[]
  if row['pid']!=os.getpid() and args and workers.win_path(args[-1])==workers.win_path(root.parent/'IG-AutoUpload'):continue
  kept.append(row)
 with patch.object(workers,'BOOTSTRAP',bootstrap):return workers.classify_workers(kept,root,os.getpid(),runner)

def require_profiles_free(root,accounts):
 if any(not re.fullmatch('fb[0-9]{2,}',a) for a in accounts):raise ValueError('预检账号范围异常')
 r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',QUERY],input=json.dumps(dict(root=str(root),accounts=sorted(accounts))).encode(),capture_output=True,timeout=20,creationflags=0x08000000)
 if r.returncode:raise RuntimeError('无法核对全批FB浏览器占用，未开始上传')
 rows=json.loads(r.stdout.decode('utf-8-sig'))
 if not isinstance(rows,list) or any(set(row)!={'account','pid','created'} or row['account'] not in accounts or type(row['pid'])!=int for row in rows):raise ValueError('资料占用预检结果异常，未上传')
 from publication_file_state_20261124 import save
 save(root/'logs/nov26-profile-preflight.json',dict(accounts=sorted(accounts),occupied=rows,checked_at=datetime.now(timezone.utc).isoformat(),instagram_untouched=True))
 if rows:raise RuntimeError('启动前发现FB资料占用，尚未上传；请关闭这些编号窗口后重跑：'+','.join(row['account']+' PID '+str(row['pid']) for row in rows))
 print('启动前FB资料占用检查通过：',len(accounts),'个账号；Instagram窗口保留。',flush=True)
