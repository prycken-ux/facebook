param([string]$InputFile,[switch]$FunctionsOnly)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
# Enumerate all visible top-level windows for the browser root and its Chrome
# subprocesses. A zero MainWindowHandle alone does not prove no window exists.
function Test-ProfileVisibleWindow([int]$BrowserId) {
 if(-not ('FBResume18VisibleWindow' -as [type])){
  Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class FBResume18VisibleWindow {
 delegate bool EnumProc(IntPtr window, IntPtr data);
 [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc callback, IntPtr data);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
 public static bool HasVisible(int[] pids) {
  var targets = new HashSet<int>(pids); bool found = false;
  bool ok = EnumWindows(delegate(IntPtr w, IntPtr d) {
   uint pid; GetWindowThreadProcessId(w, out pid);
   if (targets.Contains((int)pid) && IsWindowVisible(w)) found = true;
   return true;
  }, IntPtr.Zero);
  if (!ok) throw new InvalidOperationException("Unable to enumerate browser windows");
  return found;
 }
}
'@
 }
 $family=New-Object 'System.Collections.Generic.HashSet[int]'
 $null=$family.Add($BrowserId)
 $rows=@(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")
 for($i=0;$i -lt 16;$i++){
  $before=$family.Count
  foreach($child in $rows){
   if($family.Contains([int]$child.ParentProcessId) -and ([string]$child.CommandLine) -match '(?i)(?:^|\s)--type(?:=|\s)'){$null=$family.Add([int]$child.ProcessId)}
  }
  if($family.Count -eq $before){break}
 }
 [FBResume18VisibleWindow]::HasVisible([int[]]@($family))
}
function Release-IdleProfile([string]$InputFile) {
 $packet=Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json
 $root=[IO.Path]::GetFullPath([string]$packet.root).TrimEnd('\')
 $rootCompare=$root.Replace('/','\')
 $account=[string]$packet.account
 if($account -notin @('fb01','fb02','fb04','fb06','fb07','fb08','fb10','fb11')){throw '账号不在本次18目标范围，未关闭浏览器。'}
 $targetProfile=Join-Path $root ('profiles\'+$account)
 function Assert-Idle {
  $rows=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")
  foreach($row in $rows){
   if(-not $row.CommandLine -and -not $row.ExecutablePath){throw '无法核对Python任务，保留当前账号浏览器。'}
   $related=([string]$row.CommandLine).Replace('/','\').IndexOf($rootCompare,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or ([string]$row.ExecutablePath).Replace('/','\').StartsWith($rootCompare+'\',[StringComparison]::OrdinalIgnoreCase)
   if(-not $related){continue}
   $known=@($packet.allowed | Where-Object {$_.pid -eq $row.ProcessId})
   if($known.Count -ne 1){throw '其他项目任务仍在运行，保留当前账号浏览器。'}
   $born=if($known[0].created -is [datetime]){$known[0].created.ToUniversalTime()}else{[datetimeoffset]::Parse([string]$known[0].created).UtcDateTime}
   if(-not $row.CreationDate -or $row.CreationDate.ToUniversalTime() -ne $born){throw '项目任务启动时间已变化，保留当前账号浏览器。'}
   $sha=[Security.Cryptography.SHA256]::Create()
   try{$digest=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$row.CommandLine))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
   if($digest -ne $known[0].command_sha){throw '项目进程身份变化，保留当前账号浏览器。'}
  }
  $state=Get-Content -LiteralPath (Join-Path $root 'logs\publish_state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if(@($state.PSObject.Properties | Where-Object {$_.Value.account -eq $account -and $_.Value.status -in @('preparing','posting')}).Count){throw '当前账号另有准备中或提交中的记录，保留浏览器。'}
 }
function Get-ProfileOwners {
 foreach($row in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")){
  $cmd=[string]$row.CommandLine
  if($cmd -match '(?i)(?:^|\s)--type(?:=|\s)'){continue}
  $m=[regex]::Match($cmd,'(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
  if(-not $m.Success){continue}
  $actual=if($m.Groups[1].Success){$m.Groups[1].Value}else{$m.Groups[2].Value}
  if([string]::Equals([IO.Path]::GetFullPath($actual).TrimEnd('\'),$targetProfile,[StringComparison]::OrdinalIgnoreCase)){$row}
 }
}
 Assert-Idle
 $owners=@(Get-ProfileOwners)
 if(-not $owners.Count){Write-Output '当前账号没有浏览器占用，可继续原视频。';return}
 if($owners.Count -ne 1){throw '当前账号浏览器父进程不唯一，保留。'}
 $row=$owners[0]
 if($row.CommandLine -notmatch '(?i)(?:^|\s)--headless(?:=new|=old)?(?:\s|$)' -and $packet.closed_windows_authorization -ne 'user-closed-selected18-windows-20261126'){throw '缺少用户已关窗的本次范围记录，保留普通Chrome。'}
 $starter=@(Get-CimInstance Win32_Process -Filter ('ProcessId='+$packet.starter_pid))
 if($starter.Count -ne 1 -or -not $row.CreationDate -or $row.CreationDate -ge $starter[0].CreationDate){throw '当前账号浏览器不是原有残留，保留新进程。'}
 $p=Get-Process -Id $row.ProcessId
 try{
  $null=$p.Handle
  if($p.HasExited -or $p.ProcessName -ne 'chrome' -or $p.MainWindowHandle -ne 0 -or $p.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $row.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')){throw '当前账号进程或窗口身份变化，未关闭。'}
  if(Test-ProfileVisibleWindow ([int]$row.ProcessId)){throw '当前账号仍有可见Chrome窗口，保留窗口。'}
  Assert-Idle
  $fresh=@(Get-ProfileOwners)
  if($fresh.Count -ne 1 -or $fresh[0].ProcessId -ne $row.ProcessId -or $fresh[0].CreationDate -ne $row.CreationDate -or $fresh[0].CommandLine -ne $row.CommandLine){throw '当前账号占用状态变化，未关闭。'}
  $p.Refresh()
  if($p.HasExited -or $p.MainWindowHandle -ne 0){throw '当前账号窗口状态变化，未关闭。'}
  if(Test-ProfileVisibleWindow ([int]$row.ProcessId)){throw '关闭前又出现可见窗口，未结束进程。'}
  $p.Kill()
  if(-not $p.WaitForExit(10000)){throw '当前账号旧进程尚未退出，未重复启动。'}
  if(@(Get-ProfileOwners).Count){throw '当前账号被其他进程重新使用，保留新进程。'}
  Write-Output ('已释放本次授权账号的旧无窗口Chrome：'+$row.ProcessId+'；原登录资料未改动。')
 }finally{$p.Dispose()}
}
if(-not $FunctionsOnly){try{Release-IdleProfile $InputFile}catch{Write-Output ('当前账号保留待处理：'+$_.Exception.Message);exit 3}}
