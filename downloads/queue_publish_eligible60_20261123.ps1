param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Entry,[Parameter(Mandatory=$true)][string]$EntrySha)
$ErrorActionPreference='Stop'
$fbRoot=[IO.Path]::GetFullPath($Root).TrimEnd('\')
$fbCompare=$fbRoot.Replace('/','\')
$fbLog=Join-Path $fbRoot 'logs\eligible60-2026-11-23-queue.log'
$fbStatus=Join-Path $fbRoot 'logs\eligible60-2026-11-23-queue.json'
$fbMutex=$null
$fbOwned=$false
function Write-FbState([string]$Phase,[string]$Message) {
 $stamp=[DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(8)).ToString('o')
 ($stamp+' '+$Message) | Add-Content -LiteralPath $fbLog -Encoding UTF8
 [pscustomobject]@{phase=$Phase;message=$Message;time_beijing=$stamp;pid=$PID;material_date='2026-11-23'} |
  ConvertTo-Json -Compress | Set-Content -LiteralPath $fbStatus -Encoding UTF8
}
function Get-FbWorkers {
 foreach($p in @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop)) {
  $cmd=[string]$p.CommandLine;$exe=[string]$p.ExecutablePath
  if(-not $cmd -and -not $exe){throw 'A Python process cannot be inspected; publication was not started.'}
  if($cmd.Replace('/','\').IndexOf($fbCompare,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or
     $exe.Replace('/','\').StartsWith($fbCompare+'\',[StringComparison]::OrdinalIgnoreCase)){[long]$p.ProcessId}
 }
}
try {
 $sha=[Security.Cryptography.SHA256]::Create()
 try{$key=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($fbRoot.ToLowerInvariant())))).Replace('-','').Substring(0,20)}finally{$sha.Dispose()}
 $fbMutex=New-Object Threading.Mutex($false,('Local\FBUpload-Nov23-Queue-'+$key))
 try{$fbOwned=$fbMutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$fbOwned=$true}
 if(-not $fbOwned){exit 0}
 $pointer=Join-Path $fbRoot 'material-staging\eligible60-20261123-pending-import.json'
 # This waiter is PowerShell, so it never appears as another project Python
 # worker and cannot block the allocator or the Nov20 resumption it awaits.
 while($true) {
  $workers=@(Get-FbWorkers)
  if($workers.Count){Write-FbState 'waiting_workers' ('等待原发布/分配/登录任务结束，PID：'+($workers -join ','));Start-Sleep -Seconds 10;continue}
  $ready=$false
  if(Test-Path -LiteralPath $pointer) {
   try{$saved=Get-Content -LiteralPath $pointer -Raw -Encoding UTF8 | ConvertFrom-Json;$ready=($saved.complete -eq $true)}catch{$ready=$false}
  }
  if(-not $ready){Write-FbState 'waiting_distribution' '等待11月23日60条素材正式分配完成；请保留原分配窗口。';Start-Sleep -Seconds 10;continue}
  break
 }
 $folder=Split-Path -Parent $Entry
 $manifest=Get-Content -LiteralPath (Join-Path $folder 'runtime-sha256.json') -Raw -Encoding UTF8 | ConvertFrom-Json
 foreach($item in $manifest.PSObject.Properties){
  if($item.Name -ne [IO.Path]::GetFileName($item.Name)){throw 'Invalid runtime file name.'}
  $file=Join-Path $folder $item.Name
  $info=Get-Item -LiteralPath $file -Force
  if(($info.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Runtime file is a link.'}
  if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Value){throw 'Runtime hash changed; publication was not started.'}
 }
 if((Get-FileHash -LiteralPath $Entry -Algorithm SHA256).Hash.ToLowerInvariant() -ne $EntrySha){throw 'Publisher hash changed.'}
 if(@(Get-FbWorkers).Count){throw 'Another project task started; no concurrent publisher was launched. Re-run the same entry after it finishes.'}
 Write-FbState 'starting' '今天素材已分配、原任务已结束，开始后台发布11月23日视频及评论。'
 $start=New-Object Diagnostics.ProcessStartInfo
 $start.FileName=Join-Path $fbRoot '.venv\Scripts\python.exe'
 $start.Arguments='-u "'+$Entry+'" "'+$fbRoot+'"'
 $start.WorkingDirectory=$fbRoot;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
 $start.EnvironmentVariables['FB_PUBLISH_ISOLATED_BACKGROUND']='1'
 $start.EnvironmentVariables['FB_PUBLISH_FILE_LOG_ONLY']='1'
 $start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
 $process=[Diagnostics.Process]::Start($start)
 try {
  $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
  $process.WaitForExit()
  $output=$stdout.GetAwaiter().GetResult();$errorText=$stderr.GetAwaiter().GetResult()
  if($errorText){$errorText | Add-Content -LiteralPath (Join-Path $fbRoot 'logs\eligible60-2026-11-23-startup-error.txt') -Encoding UTF8}
  if($process.ExitCode -eq 0){Write-FbState 'finished' '本批视频及评论流程完成；实际明细见发布日志。'}
  elseif($process.ExitCode -eq 3){Write-FbState 'review_required' '自动发布和补发阶段已结束，仍有待核实或人工处理项目；请查看发布日志。'}
  elseif($process.ExitCode -eq -1073741510){Write-FbState 'interrupted' '发布进程收到控制台中断/关闭信号(0xC000013A)，已保留原记录；请使用隔离版入口续跑，已提交视频不重复上传。'}
  else{Write-FbState 'stopped' ('发布入口停止，退出码：'+$process.ExitCode+'；原记录保留，请查看发布日志。')}
 }finally{$process.Dispose()}
}catch{
 if($fbOwned){Write-FbState 'error' ('STOP：'+$_.Exception.Message)}
}finally{
 if($fbOwned -and $fbMutex){$fbMutex.ReleaseMutex()}
 if($fbMutex){$fbMutex.Dispose()}
}
