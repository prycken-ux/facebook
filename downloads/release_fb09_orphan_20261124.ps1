param([string]$InputFile,[switch]$FunctionsOnly)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
function Release-Fb09Orphan([string]$InputFile) {
 $packet=Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json
 $root=[IO.Path]::GetFullPath([string]$packet.root).TrimEnd('\')
 $rootCompare=$root.Replace('/','\')
 $profile=Join-Path $root 'profiles\fb09'
 function Assert-Idle {
  $rows=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")
  foreach($row in $rows){
   if(-not $row.CommandLine -and -not $row.ExecutablePath){throw '无法核对Python任务，保留fb09浏览器。'}
   $related=([string]$row.CommandLine).Replace('/','\').IndexOf($rootCompare,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or ([string]$row.ExecutablePath).Replace('/','\').StartsWith($rootCompare+'\',[StringComparison]::OrdinalIgnoreCase)
   if(-not $related){continue}
   $known=@($packet.allowed | Where-Object {$_.pid -eq $row.ProcessId})
   if($known.Count -ne 1){throw '其他项目任务仍在运行，保留fb09浏览器。'}
   $born=if($known[0].created -is [datetime]){$known[0].created.ToUniversalTime()}else{[datetimeoffset]::Parse([string]$known[0].created).UtcDateTime}
   if(-not $row.CreationDate -or $row.CreationDate.ToUniversalTime() -ne $born){throw '项目任务启动时间已变化，保留fb09浏览器。'}
   $sha=[Security.Cryptography.SHA256]::Create()
   try{$digest=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$row.CommandLine))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
   if($digest -ne $known[0].command_sha){throw '项目进程身份变化，保留fb09浏览器。'}
  }
  $state=Get-Content -LiteralPath (Join-Path $root 'logs\publish_state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if(@($state.PSObject.Properties | Where-Object {$_.Value.account -eq 'fb09' -and $_.Value.status -in @('preparing','posting')}).Count){throw 'fb09另有准备中或提交中的记录，保留浏览器。'}
 }
function Get-Fb09Owners {
 foreach($row in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")){
  $cmd=[string]$row.CommandLine
  if($cmd -match '(?i)(?:^|\s)--type(?:=|\s)'){continue}
  $m=[regex]::Match($cmd,'(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
  if(-not $m.Success){continue}
  $actual=if($m.Groups[1].Success){$m.Groups[1].Value}else{$m.Groups[2].Value}
  if([string]::Equals([IO.Path]::GetFullPath($actual).TrimEnd('\'),$profile,[StringComparison]::OrdinalIgnoreCase)){$row}
 }
}
 Assert-Idle
 $owners=@(Get-Fb09Owners)
 if(-not $owners.Count){Write-Output 'fb09没有浏览器占用，可继续原视频。';return}
 if($owners.Count -ne 1){throw 'fb09浏览器父进程不唯一，保留。'}
 $row=$owners[0]
 if($row.CommandLine -notmatch '(?i)(?:^|\s)--headless(?:=new|=old)?(?:\s|$)'){throw 'fb09是普通浏览器，保留手动窗口；本轮先跳过fb09。'}
 $starter=@(Get-CimInstance Win32_Process -Filter ('ProcessId='+$packet.starter_pid))
 if($starter.Count -ne 1 -or -not $row.CreationDate -or $row.CreationDate -ge $starter[0].CreationDate){throw 'fb09浏览器不是原有残留，保留新进程。'}
 $p=Get-Process -Id $row.ProcessId
 try{
  $null=$p.Handle
  if($p.HasExited -or $p.ProcessName -ne 'chrome' -or $p.MainWindowHandle -ne 0 -or $p.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $row.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')){throw 'fb09进程或窗口身份变化，未关闭。'}
  Assert-Idle
  $fresh=@(Get-Fb09Owners)
  if($fresh.Count -ne 1 -or $fresh[0].ProcessId -ne $row.ProcessId -or $fresh[0].CreationDate -ne $row.CreationDate -or $fresh[0].CommandLine -ne $row.CommandLine){throw 'fb09占用状态变化，未关闭。'}
  $p.Refresh()
  if($p.HasExited -or $p.MainWindowHandle -ne 0){throw 'fb09窗口状态变化，未关闭。'}
  $p.Kill()
  if(-not $p.WaitForExit(10000)){throw 'fb09旧进程尚未退出，未重复启动。'}
  if(@(Get-Fb09Owners).Count){throw 'fb09被其他进程重新使用，保留新进程。'}
  Write-Output ('已释放核验过的fb09旧无窗口Chrome：'+$row.ProcessId+'；原登录资料未改动。')
 }finally{$p.Dispose()}
}
if(-not $FunctionsOnly){try{Release-Fb09Orphan $InputFile}catch{Write-Output ('fb09保留待处理：'+$_.Exception.Message);exit 3}}
