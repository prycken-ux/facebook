param([string]$Root='E:\FB-AutoUpload',[string]$ResultPath,[switch]$FunctionsOnly)
$ErrorActionPreference='Stop'
function Get-SharedHash([string]$Path) {
 $stream=$null;$hash=$null
 try{
  $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
  $hash=[Security.Cryptography.SHA256]::Create()
  [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()
 }finally{if($hash){$hash.Dispose()};if($stream){$stream.Dispose()}}
}
function Pin-Nov23Process($row) {
 $p=Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
 if(-not $p){return $null}
 try{
  $null=$p.Handle
  if($p.HasExited){$p.Dispose();return $null}
  if($p.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $row.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')){throw '进程身份变化，未结束其他程序。'}
  return $p
 }catch{$p.Dispose();throw}
}
function Stop-Nov23VideoRepair([string]$Root,[string]$ResultPath) {
 $Root=[IO.Path]::GetFullPath($Root).TrimEnd('\')
 $statusPath=Join-Path $Root 'logs\nov23-caption-fb09-repair-status.json'
 $status=Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
 if($status.material_date -ne '2026-11-23' -or $status.launch_id -notmatch '^[a-f0-9]{32}$' -or -not $status.pid){throw '23号修复任务身份记录不符，未结束程序。'}
 $scriptPath=Join-Path $Root 'material-staging\tools\nov23-caption-repair-e6453166086a0db8\repair_nov23_caption_fb09_20261124.py'
 $pattern='(?i)(?:^|\s)"?'+[regex]::Escape($scriptPath)+'"?(?=\s|$)'
 $rootPattern='(?i)(?:^|\s)"?'+[regex]::Escape($Root)+'"?(?=\s|$)'
 $rows=@(Get-CimInstance Win32_Process)
 $owners=@($rows | Where-Object {$_.ProcessId -eq $status.pid})
 $held=New-Object 'Collections.Generic.List[object]'
 $known=@{};$ended=@()
 try{
  if($owners.Count){
   if($owners.Count -ne 1){throw '进程编号不唯一。'}
   $owner=$owners[0]
   if($owner.Name -notin @('python.exe','pythonw.exe') -or $owner.CommandLine -notmatch $pattern -or $owner.CommandLine -notmatch $rootPattern){throw '记录中的PID不属于原23号修复任务，未关闭它。'}
   if((Get-SharedHash $scriptPath) -ne '9c79188f0dc75d57f071941be899752d2bc8bcf64f66cdf46075b366155bb8b7'){throw '原23号程序指纹不符，未关闭程序。'}
   if(-not $owner.CreationDate -or $owner.CreationDate.ToUniversalTime() -gt [datetimeoffset]::Parse([string]$status.updated_at).UtcDateTime){throw 'PID已复用或回执过旧，未关闭程序。'}
   $p=Pin-Nov23Process $owner
   if($p){$held.Add($p);$known[[long]$owner.ProcessId]=$owner}
   # Pin handles before terminating. Retained handles prevent PID reuse while
   # collecting descendants, including children launched during the first scan.
   function Collect-Nov23Descendants($snapshot) {
    for($round=0;$round -lt $snapshot.Count;$round++){
     $added=$false
     foreach($row in $snapshot){
      if($known.ContainsKey([long]$row.ProcessId) -or -not $known.ContainsKey([long]$row.ParentProcessId)){continue}
      if(-not $row.CreationDate -or $row.CreationDate -lt $known[[long]$row.ParentProcessId].CreationDate){continue}
      $child=Pin-Nov23Process $row
      if($child){$held.Add($child);$known[[long]$row.ProcessId]=$row;$added=$true}
     }
     if(-not $added){break}
    }
   }
   if($held.Count){
    Collect-Nov23Descendants $rows
    $fresh=Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if($fresh.launch_id -ne $status.launch_id -or $fresh.pid -ne $status.pid){throw '23号任务身份已变化，未结束程序。'}
    $current=Get-CimInstance Win32_Process -Filter ('ProcessId='+$status.pid)
    if(-not $current -or $current.CommandLine -ne $owner.CommandLine -or $current.CreationDate -ne $owner.CreationDate){throw '23号任务进程变化，未结束程序。'}
    # Root first prevents advancement to the next video. Kill only pinned owned
    # processes; never select Chrome or Python by name alone.
    for($round=0;$round -lt 4;$round++){
     foreach($p in $held){try{if(-not $p.HasExited){$p.Kill()}}catch{if(-not $p.HasExited){throw}}}
     foreach($p in $held){if(-not $p.WaitForExit(5000)){throw '23号子进程尚未退出。'}}
     $count=$held.Count
     Collect-Nov23Descendants @(Get-CimInstance Win32_Process)
     if($held.Count -eq $count){break}
    }
    if(@($held | Where-Object {-not $_.HasExited}).Count){throw '23号子进程仍在退出，请再次核对。'}
    $ended=@($held | ForEach-Object {$_.Id})
   }
  }
  # A stale/missing PID cannot authorize another live run with this entry.
  for($check=0;$check -lt 10;$check++){
   $remaining=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -match $pattern -and $_.CommandLine -match $rootPattern})
   if(-not $remaining.Count){break}
   Start-Sleep -Milliseconds 100
  }
  if($remaining.Count){throw '仍发现23号修复入口，身份与原回执不同，保留并报告；未影响24号。'}
  $fresh=Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if($fresh.launch_id -ne $status.launch_id -or $fresh.pid -ne $status.pid){throw '23号回执已经变化，未覆盖。'}
  $audit=[ordered]@{schema='nov23-user-ended-video-repair-v1';material_date='2026-11-23';launch_id=$status.launch_id;owner_pid=$status.pid;ended_pids=$ended;stopped_at=[datetime]::UtcNow.ToString('o');original_status=$status;submission_records_preserved=$true}
  [IO.File]::WriteAllText($ResultPath,($audit | ConvertTo-Json -Depth 30),(New-Object Text.UTF8Encoding($false)))
  Write-Output '23号修复发布进程已结束；所有提交和待核实记录保留。'
 }finally{foreach($p in $held){$p.Dispose()}}
}
if(-not $FunctionsOnly){try{Stop-Nov23VideoRepair $Root $ResultPath}catch{Write-Output ('STOP：'+$_.Exception.Message);exit 1}}
