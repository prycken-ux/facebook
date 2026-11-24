param([string]$Root='E:\FB-AutoUpload',[switch]$FunctionsOnly)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
function Get-SharedHash([string]$Path) {
 $stream=$null;$hash=$null
 try{
  $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
  $hash=[Security.Cryptography.SHA256]::Create()
  [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()
 }finally{if($hash){$hash.Dispose()};if($stream){$stream.Dispose()}}
}
function Stop-Nov23CommentMonitor([string]$Root) {
 $Root=[IO.Path]::GetFullPath($Root).TrimEnd('\')
 $statusPath=Join-Path $Root 'logs\eligible60-2026-11-23-deadline.json'
 if(-not(Test-Path -LiteralPath $statusPath)){Write-Output '未发现23号评论监控记录，继续核对原任务。';return}
 $status=Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
 if($status.material_date -ne '2026-11-23' -or $status.run_id -notmatch '^[a-f0-9]{32}$' -or -not $status.pid){throw '评论监控身份记录不符，未结束程序。'}
 $allowed=@{
  'comment-deadline-968df9d7ea399ce1'='ae8d8cd2702364f85bb34f8dcc7ae5c48c605074bc6210f3663703845d00ce28'
  'comment-deadline-df2c293a153a5f25'='659e4cfbdf5c69216696babaaa1b15993a0a1a8d02a3b8bc41e9617b03c3eb6a'
 }
 $rows=@(Get-CimInstance Win32_Process)
 $owners=@($rows | Where-Object {$_.ProcessId -eq $status.pid})
 if(-not $owners.Count){Write-Output '原23号评论监控已经结束，未关闭其他程序。';return}
 if($owners.Count -ne 1){throw '评论监控PID不唯一，未结束程序。'}
 $owner=$owners[0];$valid=$false
 $rootPattern='(?i)(?:^|\s)"?'+[regex]::Escape($Root)+'"?(?=\s|$)'
 foreach($folder in $allowed.Keys){
  $scriptPath=Join-Path $Root ('material-staging\tools\'+$folder+'\resume_nov23_comment_deadline_20261124.py')
  $pattern='(?i)(?:^|\s)"?'+[regex]::Escape($scriptPath)+'"?(?=\s|$)'
  if($owner.CommandLine -match $pattern -and $owner.CommandLine -match $rootPattern -and (Get-SharedHash $scriptPath) -eq $allowed[$folder]){$valid=$true;break}
 }
 if(-not $valid -or $owner.Name -notin @('python.exe','pythonw.exe')){throw '该PID不是原23号评论监控，未结束程序。'}
 if(-not $owner.CreationDate -or $owner.CreationDate.ToUniversalTime() -gt [datetimeoffset]::Parse([string]$status.updated_at).UtcDateTime){throw 'PID晚于监控回执，保留可能复用的程序。'}
 $held=New-Object 'Collections.Generic.List[object]'
 function Pin($row) {
  $p=Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
  if(-not $p){return $null}
  try{
   $null=$p.Handle
   if($p.HasExited){$p.Dispose();return $null}
   if($p.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $row.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')){throw '进程身份变化，未结束程序。'}
   return $p
  }catch{$p.Dispose();throw}
 }
 try{
  $p=Pin $owner
  if(-not $p){Write-Output '评论监控已退出，继续核对遗留锁。';return}
  $held.Add($p);$known=@{};$known[[long]$owner.ProcessId]=$owner
  for($i=0;$i -lt $rows.Count;$i++){
   $added=$false
   foreach($row in $rows){
    if($known.ContainsKey([long]$row.ProcessId) -or -not $known.ContainsKey([long]$row.ParentProcessId)){continue}
    if(-not $row.CreationDate -or $row.CreationDate -lt $known[[long]$row.ParentProcessId].CreationDate){continue}
    $p=Pin $row
    if($p){$held.Add($p);$known[[long]$row.ProcessId]=$row;$added=$true}
   }
   if(-not $added){break}
  }
  $fresh=Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if($fresh.run_id -ne $status.run_id -or $fresh.pid -ne $status.pid){throw '评论监控身份已经变化，未结束程序。'}
  $current=Get-CimInstance Win32_Process -Filter ('ProcessId='+$status.pid)
  if(-not $current -or $current.CommandLine -ne $owner.CommandLine -or $current.CreationDate -ne $owner.CreationDate){throw '评论监控进程发生变化，未结束程序。'}
  # Closing this supervisor also closes its job handle and stops its contained
  # worker. Snapshot descendants are pinned; unrelated Chrome is never selected.
  foreach($p in $held){try{if(-not $p.HasExited){$p.Kill()}}catch{if(-not $p.HasExited){throw}}}
  foreach($p in $held){if(-not $p.WaitForExit(10000)){throw '原评论任务尚未退出，未开始视频续跑。'}}
  $audit=Join-Path $Root ('logs\nov23-comments-stopped-'+$status.run_id+'.json')
  [IO.File]::WriteAllText($audit,($status | ConvertTo-Json -Depth 20),(New-Object Text.UTF8Encoding($false)))
  Write-Output ('已停止23号评论监控及其本轮子进程；保留所有视频和评论提交记录。PID：'+(($held | ForEach-Object {$_.Id}) -join ','))
 }finally{foreach($p in $held){$p.Dispose()}}
}
if(-not $FunctionsOnly){try{Stop-Nov23CommentMonitor $Root}catch{Write-Output ('STOP：'+$_.Exception.Message);exit 1}}
