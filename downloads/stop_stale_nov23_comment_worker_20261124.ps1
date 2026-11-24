param([string]$InputFile,[switch]$FunctionsOnly)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
function Get-SharedFileSha256([string]$LiteralPath) {
 $stream=$null;$hash=$null
 try{
  # The old Python worker holds its log open for writing. A reader must also
  # share Write access; Get-FileHash's default stream can reject that writer.
  $sharing=[IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
  $stream=[IO.File]::Open($LiteralPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,$sharing)
  $hash=[Security.Cryptography.SHA256]::Create()
  return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()
 }finally{
  if($hash){$hash.Dispose()}
  if($stream){$stream.Dispose()}
 }
}
function Invoke-StaleCommentStop([string]$InputFile) {
$d=Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json
$root=[IO.Path]::GetFullPath([string]$d.root).TrimEnd('\')
$queue=Join-Path $root 'logs\eligible60-2026-11-23-queue.json'
$log=Join-Path $root 'logs\eligible60-2026-11-23-run.log'
$script=Join-Path $root 'material-staging\tools\b9876463425ed103\publish_eligible60_real_20261123.py'
function Assert-StillStale {
 if((Get-SharedFileSha256 $queue) -ne $d.queue_sha){throw '队列记录已经变化，未停止任务。'}
 if((Get-SharedFileSha256 $log) -ne $d.log_sha){throw '日志已有新进度，未停止任务。'}
 if((Get-Item -LiteralPath $log).LastWriteTimeUtc -gt [datetime]::UtcNow.AddSeconds(-180)){throw '日志未停滞三分钟，未停止任务。'}
}
function Pin-Process($row) {
 $p=Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
 if(-not $p){return $null}
 try{
  $null=$p.Handle
  if($p.HasExited){$p.Dispose();return $null}
  if($p.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $row.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')){throw '进程身份已变化，保留未核实进程。'}
  return $p
 }catch{$p.Dispose();throw}
}
$held=New-Object 'Collections.Generic.List[object]'
try{
 Assert-StillStale
 $status=Get-Content -LiteralPath $queue -Raw -Encoding UTF8 | ConvertFrom-Json
 if($status.phase -ne 'running' -or $status.runner -ne 'direct_background' -or $status.material_date -ne '2026-11-23' -or $status.launch_id -ne $d.launch_id -or $status.pid -ne $d.pid){throw '不是已核验的23号旧后台任务。'}
 if((Get-SharedFileSha256 $script) -ne '50b3cb7017669f075904dfe9b1c6eb3501b88368911940dea6c2ef5eddf4c35a'){throw '旧任务入口指纹不符，未停止进程。'}
 $rows=@(Get-CimInstance Win32_Process)
 $owner=@($rows | Where-Object {$_.ProcessId -eq $d.pid})
 if($owner.Count -eq 0){Write-Output '原23号任务已退出，未结束其他进程。';return}
 if($owner.Count -ne 1){throw '旧任务身份不唯一。'}
 $row=$owner[0]
 if(-not $row.CreationDate -or $row.CreationDate.ToUniversalTime() -gt [datetimeoffset]::Parse([string]$status.time_beijing).UtcDateTime){throw 'PID启动时间晚于原回执，保留可能复用的进程。'}
 $scriptPattern='(?i)(?:^|\s)"?'+[regex]::Escape($script)+'"?(?=\s|$)'
 $rootPattern='(?i)(?:^|\s)"?'+[regex]::Escape($root)+'"?(?=\s|$)'
 if($row.Name -notin @('python.exe','pythonw.exe') -or $row.CommandLine -notmatch $scriptPattern -or $row.CommandLine -notmatch $rootPattern){throw 'PID已不是原23号发布入口，未停止。'}
 $p=Pin-Process $row
 if(-not $p){throw '旧任务刚已退出，请重新核对。'}
 $held.Add($p)
 $ids=New-Object 'Collections.Generic.HashSet[long]';[void]$ids.Add([long]$row.ProcessId)
 $known=@{};$known[[long]$row.ProcessId]=$row
 for($i=0;$i -lt $rows.Count;$i++){
  $added=$false
  foreach($child in $rows){
   if($ids.Contains([long]$child.ProcessId) -or -not $ids.Contains([long]$child.ParentProcessId)){continue}
   if(-not $child.CreationDate -or $child.CreationDate -lt $known[[long]$child.ParentProcessId].CreationDate){continue}
   $handle=Pin-Process $child
   if($handle){$held.Add($handle);[void]$ids.Add([long]$child.ProcessId);$known[[long]$child.ProcessId]=$child;$added=$true}
  }
  if(-not $added){break}
 }
 Assert-StillStale
 $fresh=Get-CimInstance Win32_Process -Filter ('ProcessId='+$d.pid)
 if(-not $fresh -or $fresh.CreationDate -ne $row.CreationDate -or $fresh.CommandLine -ne $row.CommandLine){throw '旧任务身份变化，未停止。'}
 # Stop the pinned root first; only already-verified descendants are touched.
 foreach($handle in $held){try{if(-not $handle.HasExited){$handle.Kill()}}catch{if(-not $handle.HasExited){throw}}}
 foreach($handle in $held){if(-not $handle.WaitForExit(10000)){throw '旧任务进程尚未退出，未启动下一条。'}}
 Write-Output ('已结束核验过的23号卡住任务及其子进程；原记录保留。PID：'+(($held | ForEach-Object {$_.Id}) -join ','))
}finally{foreach($handle in $held){$handle.Dispose()}}

}
if(-not $FunctionsOnly){try{Invoke-StaleCommentStop $InputFile}catch{Write-Output ('STOP：'+$_.Exception.Message);exit 1}}
