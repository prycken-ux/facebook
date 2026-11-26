param([string]$Plan,[string]$Result,[switch]$FunctionsOnly)
$ErrorActionPreference='Stop'
function CommandHash([string]$Text){$h=[Security.Cryptography.SHA256]::Create();try{[BitConverter]::ToString($h.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}}
function UtcValue($Value){if($Value -is [datetime]){$Value.ToUniversalTime()}else{[datetimeoffset]::Parse([string]$Value).UtcDateTime}}
function SameProcess($row,$expected){$row -and $row.Name -eq $expected.name -and (UtcValue $row.CreationDate) -eq (UtcValue $expected.created) -and (CommandHash ([string]$row.CommandLine)) -eq $expected.command_sha}
function ProfileOwners([string]$Root){
 $prefix=(Join-Path $Root 'profiles').Replace('/','\').TrimEnd('\')+'\'
 foreach($row in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")){
  $cmd=[string]$row.CommandLine
  if($cmd -match '(?i)(?:^|\s)--type(?:=|\s)'){continue}
  $m=[regex]::Match($cmd,'(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
  if(-not $m.Success){continue}
  $path=if($m.Groups[1].Success){$m.Groups[1].Value}else{$m.Groups[2].Value}
  $path=[IO.Path]::GetFullPath($path).Replace('/','\').TrimEnd('\')
  if(-not $path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){continue}
  $account=$path.Substring($prefix.Length)
  if($account -match '^fb\d{2,}$'){[pscustomobject]@{account=$account;row=$row}}
 }
}
function BrowserFamily([int]$BrowserId){
 $ids=New-Object 'Collections.Generic.HashSet[int]';$null=$ids.Add($BrowserId)
 $rows=@(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")
 for($i=0;$i -lt 16;$i++){$before=$ids.Count;foreach($row in $rows){if($ids.Contains([int]$row.ParentProcessId) -and ([string]$row.CommandLine) -match '(?i)(?:^|\s)--type(?:=|\s)'){$null=$ids.Add([int]$row.ProcessId)}};if($before -eq $ids.Count){break}}
 [int[]]@($ids)
}
function LoadWindowApi {
 if('FBPrepare26Windows' -as [type]){return}
 Add-Type -TypeDefinition @'
using System;using System.Collections.Generic;using System.Runtime.InteropServices;
public static class FBPrepare26Windows {
 delegate bool EnumProc(IntPtr w,IntPtr d);
 [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f,IntPtr d);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr w);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr w,out uint pid);
 [DllImport("user32.dll")] static extern bool PostMessage(IntPtr w,uint m,IntPtr a,IntPtr b);
 static List<IntPtr> Windows(int[] ids){var set=new HashSet<int>(ids);var found=new List<IntPtr>();bool ok=EnumWindows(delegate(IntPtr w,IntPtr d){uint pid;GetWindowThreadProcessId(w,out pid);if(set.Contains((int)pid)&&IsWindowVisible(w))found.Add(w);return true;},IntPtr.Zero);if(!ok)throw new InvalidOperationException("Cannot enumerate windows");return found;}
 public static bool Visible(int[] ids){return Windows(ids).Count>0;}
 public static int Close(int[] ids){int n=0;foreach(var w in Windows(ids)){if(PostMessage(w,0x0010,IntPtr.Zero,IntPtr.Zero))n++;}return n;}
}
'@
}
function HasVisible([int]$BrowserId){LoadWindowApi;[FBPrepare26Windows]::Visible([int[]]@(BrowserFamily $BrowserId))}
function CloseVisible([int]$BrowserId){LoadWindowApi;[FBPrepare26Windows]::Close([int[]]@(BrowserFamily $BrowserId))}
function AssertFbIdle($packet){
 $root=[string]$packet.root;$compare=$root.Replace('/','\').TrimEnd('\')
 $ig=Join-Path (Split-Path -Parent $root) 'IG-AutoUpload';$igPattern='(?i)(?:^|\s)"?'+[regex]::Escape($ig)+'"?$'
 foreach($row in @(Get-CimInstance Win32_Process | Where-Object {$_.Name -in @('python.exe','pythonw.exe','powershell.exe','pwsh.exe')})){
  if($row.ProcessId -eq $PID){continue}
  if(([string]$row.CommandLine) -match $igPattern){continue}
  $related=([string]$row.CommandLine).Replace('/','\').IndexOf($compare,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or ([string]$row.ExecutablePath).Replace('/','\').StartsWith($compare+'\',[StringComparison]::OrdinalIgnoreCase)
  if(-not $related){continue}
  $known=@($packet.allowed | Where-Object {$_.pid -eq $row.ProcessId})
  if($known.Count -ne 1 -or -not (SameProcess $row $known[0])){throw ('仍有未释放的FB项目进程，保留账号窗口：'+$row.ProcessId)}
 }
}
function InvokeFbPrepare([string]$Plan,[string]$Result){
 $packet=Get-Content -LiteralPath $Plan -Raw -Encoding UTF8 | ConvertFrom-Json
 if($packet.schema -ne 'fb-old-materials-preparation-v1' -or $packet.cutoff -ne '2026-11-25' -or $packet.keep_from -ne '2026-11-26'){throw '清理任务身份不符'}
 $root=[IO.Path]::GetFullPath([string]$packet.root).TrimEnd('\')
 $audit=[ordered]@{schema='fb-old-materials-windows-audit-v1';root=$root;cutoff=$packet.cutoff;stopped=@();disabled_tasks=@();closed_profiles=@();blocked=@();instagram_untouched=$true;completed=$false}
 try{
  foreach($expected in @($packet.tasks)){
   $task=Get-ScheduledTask -TaskName $expected.name -TaskPath $expected.path
   $actions=@($task.Actions)
   if($actions.Count -ne @($expected.actions).Count){throw '旧计划任务操作已变化，保留'}
   for($i=0;$i -lt $actions.Count;$i++){if([string]$actions[$i].Execute -ne [string]$expected.actions[$i].execute -or [string]$actions[$i].Arguments -ne [string]$expected.actions[$i].arguments -or [string]$actions[$i].WorkingDirectory -ne [string]$expected.actions[$i].working){throw '旧计划任务内容已变化，保留'}}
   Disable-ScheduledTask -TaskName $expected.name -TaskPath $expected.path | Out-Null
   if($task.State -eq 'Running'){Stop-ScheduledTask -TaskName $expected.name -TaskPath $expected.path}
   $audit.disabled_tasks+=($expected.path+$expected.name)
  }
  foreach($expected in @($packet.stop)){
   $row=Get-CimInstance Win32_Process -Filter ('ProcessId='+$expected.pid)
   if(-not $row){continue}
   if(-not (SameProcess $row $expected)){throw ('旧任务PID身份变化，未结束：'+$expected.pid)}
   $p=Get-Process -Id $expected.pid -ErrorAction SilentlyContinue
   if(-not $p){continue}
   try{
    $null=$p.Handle
    if($p.HasExited){continue}
    if($p.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne (UtcValue $expected.created).ToString('yyyyMMddHHmmssfff')){throw '旧任务启动时间变化'}
    $fresh=Get-CimInstance Win32_Process -Filter ('ProcessId='+$expected.pid)
    if(-not (SameProcess $fresh $expected)){throw '结束前进程身份变化'}
    $p.Kill();if(-not $p.WaitForExit(5000)){throw '旧进程尚未退出'};$audit.stopped+=$expected.pid
   }finally{$p.Dispose()}
  }
  AssertFbIdle $packet
  $owners=@(ProfileOwners $root)
  foreach($owner in $owners){
   $fresh=Get-CimInstance Win32_Process -Filter ('ProcessId='+$owner.row.ProcessId)
   if(-not $fresh){continue}
   if($fresh.CreationDate -ne $owner.row.CreationDate -or $fresh.CommandLine -ne $owner.row.CommandLine){throw '关窗前浏览器身份变化，未操作窗口'}
   $null=CloseVisible ([int]$owner.row.ProcessId)
  }
  # Give all visible FB windows a shared graceful-close interval.
  $until=[datetime]::UtcNow.AddSeconds(12)
  while([datetime]::UtcNow -lt $until){$visible=@($owners | Where-Object {HasVisible ([int]$_.row.ProcessId)});if(-not $visible.Count){break};Start-Sleep -Milliseconds 250}
  foreach($owner in $owners){
   $old=$owner.row;$row=Get-CimInstance Win32_Process -Filter ('ProcessId='+$old.ProcessId)
   if(-not $row){$audit.closed_profiles+=$owner.account;continue}
   if($row.CreationDate -ne $old.CreationDate -or $row.CommandLine -ne $old.CommandLine){$audit.blocked+=('进程身份变化：'+$owner.account);continue}
   if(HasVisible ([int]$row.ProcessId)){$audit.blocked+=('仍有可见窗口/确认框：'+$owner.account);continue}
   AssertFbIdle $packet
   $p=Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
   if(-not $p){continue}
   try{
    $null=$p.Handle
    if($p.HasExited){continue}
    if($p.ProcessName -ne 'chrome' -or $p.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $row.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')){throw '浏览器PID已复用'}
    $fresh=Get-CimInstance Win32_Process -Filter ('ProcessId='+$row.ProcessId)
    if(-not $fresh){continue}
    if($fresh.CommandLine -ne $row.CommandLine -or $fresh.CreationDate -ne $row.CreationDate -or (HasVisible ([int]$row.ProcessId))){$audit.blocked+=('窗口或进程状态变化：'+$owner.account);continue}
    $p.Kill();if(-not $p.WaitForExit(5000)){throw '账号后台进程尚未退出'};$audit.closed_profiles+=$owner.account
   }finally{$p.Dispose()}
  }
  foreach($owner in @(ProfileOwners $root)){$audit.blocked+=('账号资料仍被占用：'+$owner.account+' PID '+$owner.row.ProcessId)}
  AssertFbIdle $packet
  $audit.completed=(-not $audit.blocked.Count)
 }catch{$audit.blocked+=($_.Exception.Message)}finally{
  $audit.finished_at=[datetime]::UtcNow.ToString('o')
  [IO.File]::WriteAllText($Result,($audit | ConvertTo-Json -Depth 10),(New-Object Text.UTF8Encoding($false)))
 }
 if($audit.blocked.Count){throw ($audit.blocked -join '；')}
 Write-Output ('旧FB任务已结束；已关闭/释放账号窗口：'+($audit.closed_profiles -join ',')+'；Instagram窗口保留。')
}
if(-not $FunctionsOnly){try{InvokeFbPrepare $Plan $Result}catch{Write-Output ('STOP：'+$_.Exception.Message);exit 1}}
