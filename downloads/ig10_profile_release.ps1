param([string]$Packet,[switch]$FunctionsOnly)
$ErrorActionPreference='Stop'
function LoadIgWindows {
 if('IG10Windows' -as [type]){return}
 Add-Type -TypeDefinition @'
using System;using System.Collections.Generic;using System.Runtime.InteropServices;
public static class IG10Windows {
 delegate bool Callback(IntPtr h,IntPtr p);
 [DllImport("user32.dll")] static extern bool EnumWindows(Callback f,IntPtr p);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h,uint m,IntPtr a,IntPtr b);
 static List<IntPtr> Find(int[] ids){var set=new HashSet<int>(ids);var found=new List<IntPtr>();if(!EnumWindows(delegate(IntPtr h,IntPtr p){uint id;GetWindowThreadProcessId(h,out id);if(set.Contains((int)id)&&IsWindowVisible(h))found.Add(h);return true;},IntPtr.Zero))throw new Exception("Cannot inspect windows");return found;}
 public static bool Visible(int[] ids){return Find(ids).Count>0;}
 public static void Close(int[] ids){foreach(var h in Find(ids))PostMessage(h,0x0010,IntPtr.Zero,IntPtr.Zero);}
}
'@
}
function Family([int]$BrowserId){
 $ids=New-Object 'Collections.Generic.HashSet[int]';$null=$ids.Add($BrowserId)
 $rows=@(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")
 for($i=0;$i -lt 16;$i++){$before=$ids.Count;foreach($r in $rows){if($ids.Contains([int]$r.ParentProcessId) -and ([string]$r.CommandLine) -match '(?i)(?:^|\s)--type(?:=|\s)'){$null=$ids.Add([int]$r.ProcessId)}};if($before -eq $ids.Count){break}}
 [int[]]@($ids)
}
function IgOwners($p){
 $prefix=(Join-Path $p.root 'profiles').Replace('/','\').TrimEnd('\')+'\'
 foreach($r in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")){
  $cmd=[string]$r.CommandLine;if($cmd -match '(?i)(?:^|\s)--type(?:=|\s)'){continue}
  $m=[regex]::Match($cmd,'(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))');if(-not $m.Success){continue}
  $path=if($m.Groups[1].Success){$m.Groups[1].Value}else{$m.Groups[2].Value};$path=[IO.Path]::GetFullPath($path).Replace('/','\').TrimEnd('\')
  if(-not $path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){continue}
  $a=$path.Substring($prefix.Length);if($a -in $p.accounts){[pscustomobject]@{account=$a;row=$r}}
 }
}
function AssertIgIdle($p){
 $allow=New-Object 'Collections.Generic.HashSet[int]';$current=[int]$p.caller_pid
 for($i=0;$i -lt 8;$i++){
  $r=Get-CimInstance Win32_Process -Filter ('ProcessId='+$current)
  if(-not $r -or $r.Name -notin @('python.exe','pythonw.exe')){break}
  if($current -ne $p.caller_pid -and ([string]$r.CommandLine).IndexOf([string]$p.root,[StringComparison]::OrdinalIgnoreCase) -lt 0){break}
  $null=$allow.Add($current);$current=[int]$r.ParentProcessId
 }
 foreach($r in @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")){
  if($allow.Contains([int]$r.ProcessId)){continue}
  if(([string]$r.CommandLine).IndexOf([string]$p.root,[StringComparison]::OrdinalIgnoreCase) -ge 0){throw ('Another IG task is active; kept all profiles. PID '+$r.ProcessId)}
 }
}
function ReleaseIgProfiles([string]$Packet){
 $p=Get-Content -LiteralPath $Packet -Raw -Encoding UTF8 | ConvertFrom-Json
 if($p.authorization -ne 'ig10-publication-normal-close-20261127' -or (Split-Path -Leaf $p.root) -ne 'IG-AutoUpload' -or @($p.accounts).Count -gt 10 -or @($p.accounts | Where-Object {$_ -notmatch '^ins(0[1-9]|10)$'}).Count){throw 'Invalid IG profile scope'}
 AssertIgIdle $p;LoadIgWindows;$owners=@(IgOwners $p);$released=@()
 foreach($o in $owners){$fresh=Get-CimInstance Win32_Process -Filter ('ProcessId='+$o.row.ProcessId);if($fresh -and ($fresh.CreationDate -ne $o.row.CreationDate -or $fresh.CommandLine -ne $o.row.CommandLine)){throw 'Browser identity changed before close'};if($fresh){[IG10Windows]::Close([int[]]@(Family $fresh.ProcessId))}}
 $until=[datetime]::UtcNow.AddSeconds(12)
 while([datetime]::UtcNow -lt $until){if(-not @(IgOwners $p).Count){break};Start-Sleep -Milliseconds 250}
 foreach($o in $owners){
  $r=Get-CimInstance Win32_Process -Filter ('ProcessId='+$o.row.ProcessId);if(-not $r){$released+=$o.account;continue}
  if($r.CreationDate -ne $o.row.CreationDate -or $r.CommandLine -ne $o.row.CommandLine){throw 'Browser identity changed; preserved'}
  if([IG10Windows]::Visible([int[]]@(Family $r.ProcessId))){throw ('Visible IG window/modal remains: '+$o.account)}
  AssertIgIdle $p;$proc=Get-Process -Id $r.ProcessId
  try{
   $null=$proc.Handle;if($proc.HasExited){continue}
   if($proc.ProcessName -ne 'chrome' -or $proc.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $r.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')){throw 'Recycled browser PID preserved'}
   $fresh=Get-CimInstance Win32_Process -Filter ('ProcessId='+$r.ProcessId)
   if(-not $fresh){continue}
   if($fresh.CreationDate -ne $r.CreationDate -or $fresh.CommandLine -ne $r.CommandLine -or [IG10Windows]::Visible([int[]]@(Family $r.ProcessId))){throw 'Window/browser changed; preserved'}
   $proc.Kill();if(-not $proc.WaitForExit(5000)){throw 'Owned IG background process did not exit'};$released+=$o.account
  }finally{$proc.Dispose()}
 }
 if(@(IgOwners $p).Count){throw 'IG profile still in use; publication not started'}
 Write-Output ('IG profile release complete: '+($released -join ', '))
}
if(-not $FunctionsOnly){ReleaseIgProfiles $Packet}
