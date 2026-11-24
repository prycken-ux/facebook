param([long]$StarterPid=0,[switch]$FunctionsOnly,[string]$Root='E:\FB-AutoUpload')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$fbRoot=[IO.Path]::GetFullPath($Root).TrimEnd('\')
$fbCompare=$fbRoot.Replace('/','\')
$fbProfile=Join-Path $fbRoot 'profiles\fb01'

function Assert-Fb01Path([string]$Path) {
 $item=Get-Item -LiteralPath $Path -Force
 if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw ('路径是链接，保留原文件：'+$Path)}
}
function Get-Fb01Owners {
 foreach($row in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")){
  $cmd=[string]$row.CommandLine
  if($cmd -match '(?i)(?:^|\s)--type(?:=|\s)'){continue}
  $m=[regex]::Match($cmd,'(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
  if(-not $m.Success){continue}
  $actual=if($m.Groups[1].Success){$m.Groups[1].Value}else{$m.Groups[2].Value}
  if([string]::Equals([IO.Path]::GetFullPath($actual).TrimEnd('\'),$fbProfile,[StringComparison]::OrdinalIgnoreCase)){$row}
 }
}
function Get-Fb01ProjectWorkers {
 $rows=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")
 $lookup=@{};foreach($r in $rows){$lookup[[long]$r.ProcessId]=$r}
 $skip=New-Object 'Collections.Generic.HashSet[long]'
 $node=$lookup[$StarterPid]
 if($node){
  $ownArgs=([regex]::Match([string]$node.CommandLine,'^\s*(?:"[^"]*"|[^\s]+)\s+(.*)$')).Groups[1].Value
  [void]$skip.Add([long]$node.ProcessId)
  for($i=0;$i -lt 6;$i++){
   $parent=$lookup[[long]$node.ParentProcessId]
   if(-not $parent -or -not $ownArgs -or $parent.CreationDate -gt $node.CreationDate){break}
   $args=([regex]::Match([string]$parent.CommandLine,'^\s*(?:"[^"]*"|[^\s]+)\s+(.*)$')).Groups[1].Value
   if($args -ne $ownArgs -or -not $skip.Add([long]$parent.ProcessId)){break}
   $node=$parent
  }
 }
 foreach($r in $rows){
  if($skip.Contains([long]$r.ProcessId)){continue}
  if(-not $r.CommandLine -and -not $r.ExecutablePath){throw '有Python进程无法核对，保留fb01浏览器。'}
  if(([string]$r.CommandLine).Replace('/','\').IndexOf($fbCompare,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or ([string]$r.ExecutablePath).Replace('/','\').StartsWith($fbCompare+'\',[StringComparison]::OrdinalIgnoreCase)){$r}
 }
}
function Get-Fb01ActiveRecords {
 $path=Join-Path $fbRoot 'logs\publish_state.json'
 if(-not(Test-Path -LiteralPath $path)){throw '发布记录缺失，未关闭fb01浏览器。'}
 Assert-Fb01Path $path
 for($i=0;$i -lt 3;$i++){
  try{$value=Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json;break}
  catch{if($i -eq 2){throw '发布记录正在更新，未关闭浏览器；稍后运行同一入口。'};Start-Sleep -Milliseconds 200}
 }
 foreach($property in $value.PSObject.Properties){
  $r=$property.Value
  if($r.account -eq 'fb01' -and $r.status -in @('preparing','posting')){$r}
 }
}
function Assert-Fb01StaleBrowser($Row) {
 $workers=@(Get-Fb01ProjectWorkers)
 if($workers.Count -and @(Get-Fb01ActiveRecords).Count){throw 'fb01仍有准备中或提交中的发布记录，当前任务可能使用它；未结束浏览器，等待该账号处理后再试。'}
 foreach($worker in $workers){
  if(-not $worker.CreationDate -or $worker.CreationDate.ToUniversalTime() -le $Row.CreationDate.ToUniversalTime()){
   throw ('项目任务PID '+$worker.ProcessId+' 早于该浏览器启动，无法确认fb01已空闲；保留当前浏览器。')
  }
 }
}
function Get-Fb01PinnedProcess($Row) {
 $p=Get-Process -Id $Row.ProcessId
 try{
  $null=$p.Handle
  if($p.HasExited -or $p.ProcessName -ne 'chrome' -or $p.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $Row.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')){throw 'fb01进程身份已变化，未关闭任何程序。'}
  return $p
 }catch{$p.Dispose();throw}
}
function Get-Fb01Action($Row,$Process) {
 if($Process.HasExited){throw 'fb01浏览器已退出，请运行同一入口重新检查。'}
 if($Process.MainWindowHandle -ne 0){return 'restore'}
 if([string]$Row.CommandLine -notmatch '(?i)(?:^|\s)--headless(?:=new|=old)?(?:\s|$)'){Assert-Fb01StaleBrowser $Row;return 'new_visible_window'}
 Assert-Fb01StaleBrowser $Row
 return 'close_stale_headless'
}
function Show-Fb01Window($Handle) {
 if(-not ('Fb01OriginalWindow' -as [type])){
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class Fb01OriginalWindow {
 [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hwnd,int command);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
}
'@
 }
 [void][Fb01OriginalWindow]::ShowWindowAsync($Handle,9)
 [void][Fb01OriginalWindow]::SetForegroundWindow($Handle)
}
function Invoke-Fb01Open {
 $mutex=$null;$owned=$false
 try{
  foreach($path in @($fbRoot,(Join-Path $fbRoot 'profiles'),$fbProfile,(Join-Path $fbProfile 'Default'),(Join-Path $fbRoot 'upload_config.json'))){Assert-Fb01Path $path}
  $mutex=New-Object Threading.Mutex($false,'Local\FBUpload-fb01-original-window')
  try{$owned=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$owned=$true}
  if(-not $owned){throw '已有fb01打开检查在进行，未再打开第二个窗口。'}
  $chrome=@(foreach($base in @($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA)){
   if($base){$candidate=Join-Path $base 'Google\Chrome\Application\chrome.exe';if(Test-Path -LiteralPath $candidate -PathType Leaf){$candidate}}
  }) | Select-Object -First 1
  if(-not $chrome){throw '未找到原已安装Google Chrome，未更换浏览器或登录资料。'}
  $owners=@(Get-Fb01Owners)
  if($owners.Count -gt 1){throw 'fb01浏览器父进程不唯一，未结束任何程序。'}
  if($owners.Count -eq 1){
   $row=$owners[0];$p=Get-Fb01PinnedProcess $row
   try{
    $action=Get-Fb01Action $row $p
    if($action -eq 'restore'){Show-Fb01Window $p.MainWindowHandle;Write-Output 'fb01已有正常窗口，已还原到前台。';return}
    if($action -eq 'close_stale_headless'){
     Assert-Fb01StaleBrowser $row
     $fresh=@(Get-Fb01Owners)
     if($fresh.Count -ne 1 -or $fresh[0].ProcessId -ne $row.ProcessId -or $fresh[0].CreationDate -ne $row.CreationDate -or $fresh[0].CommandLine -ne $row.CommandLine){throw 'fb01占用状态变化，保留现有进程。'}
     $p.Refresh()
     if($p.HasExited -or $p.MainWindowHandle -ne 0){throw 'fb01窗口状态变化，未结束浏览器。'}
     $p.Kill()
     if(-not $p.WaitForExit(10000)){throw '旧fb01后台浏览器尚未退出，未重复启动。'}
     Write-Output ('已释放经核验的fb01旧无窗口进程：'+$row.ProcessId)
     if(@(Get-Fb01Owners).Count){throw 'fb01被其他任务重新使用，未结束新进程或再开窗口。'}
    }
   }finally{$p.Dispose()}
  }
  if(@(Get-Fb01ProjectWorkers).Count -and @(Get-Fb01ActiveRecords).Count){throw 'fb01当前存在进行中的发布，保留后台任务，未另开窗口。'}
  $start=New-Object Diagnostics.ProcessStartInfo
  $start.FileName=$chrome;$start.WorkingDirectory=$fbRoot;$start.UseShellExecute=$false
  $start.Arguments='--user-data-dir="'+$fbProfile+'" --profile-directory=Default --no-first-run --no-default-browser-check --new-window https://www.facebook.com/?locale=en_US'
  $started=[Diagnostics.Process]::Start($start)
  try{
   for($i=0;$i -lt 15;$i++){
    foreach($row in @(Get-Fb01Owners)){
     $p=Get-Fb01PinnedProcess $row
     try{
      $p.Refresh()
      if(-not $p.HasExited -and $p.MainWindowHandle -ne 0){Show-Fb01Window $p.MainWindowHandle;Write-Output 'fb01已打开正常Chrome窗口，沿用原登录资料、扩展和代理。其他账号进程未结束，发布记录未改动。';return}
      if([string]$row.CommandLine -match '(?i)(?:^|\s)--headless(?:=new|=old)?(?:\s|$)'){throw 'fb01刚被后台任务重新使用，未结束当前发布浏览器；请稍后重试。'}
     }finally{$p.Dispose()}
    }
    Start-Sleep -Seconds 1
   }
   throw '已请求打开原fb01，但尚未确认可见窗口；资料和发布记录保留，请发送此输出。'
  }finally{$started.Dispose()}
 }finally{
  if($owned -and $mutex){$mutex.ReleaseMutex()}
  if($mutex){$mutex.Dispose()}
 }
}
if(-not $FunctionsOnly){
 try{Invoke-Fb01Open}
 catch{Write-Output ('STOP：'+$_.Exception.Message);exit 1}
}
