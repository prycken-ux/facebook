param([string]$Root,[string]$Entry,[string]$EntrySha,[string]$Run,[switch]$FunctionsOnly)
$ErrorActionPreference='Stop'
function Get-SharedHash([string]$Path) {
 $stream=$null;$hash=$null
 try{
  $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
  $hash=[Security.Cryptography.SHA256]::Create()
  [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()
 }finally{if($hash){$hash.Dispose()};if($stream){$stream.Dispose()}}
}
function Start-Nov24Queue([string]$Root,[string]$Entry,[string]$EntrySha,[string]$Run) {
 if($Run -notmatch '^[a-f0-9]{32}$'){throw 'Invalid launch identifier'}
 $Root=[IO.Path]::GetFullPath($Root).TrimEnd('\');$compare=$Root.Replace('/','\')
 $status=Join-Path $Root ('logs\nov24-queue-'+$Run+'.json')
 $mutex=$null;$owned=$false
 function State([string]$Phase,[string]$Message) {
  $value=[pscustomobject]@{run_id=$Run;phase=$Phase;message=$Message;pid=$PID;material_date='2026-11-24';updated_at=[datetimeoffset]::UtcNow.ToString('o')}
  $temporary=$status+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
  [IO.File]::WriteAllText($temporary,($value | ConvertTo-Json -Compress),(New-Object Text.UTF8Encoding($false)))
  try{for($i=0;$i -lt 20;$i++){try{Move-Item -LiteralPath $temporary -Destination $status -Force;break}catch{if($i -eq 19){throw};Start-Sleep -Milliseconds 20}}}finally{if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary}}
  # The same progress log is readable even while the queue is waiting. Share
  # Write access with the eventual publisher; optional logging never changes
  # the authoritative JSON acknowledgment or masks a running publisher.
  $stream=$null;$writer=$null
  try{
   $stream=[IO.File]::Open((Join-Path $Root 'logs\eligible60-2026-11-24-run.log'),[IO.FileMode]::Append,[IO.FileAccess]::Write,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
   $writer=New-Object IO.StreamWriter($stream,(New-Object Text.UTF8Encoding($false)))
   $writer.WriteLine(([datetimeoffset]::UtcNow.ToOffset([timespan]::FromHours(8)).ToString('o')+' '+$Phase+' '+$Message));$writer.Flush()
  }catch{}finally{if($writer){$writer.Dispose()}elseif($stream){$stream.Dispose()}}
 }
 function Workers {
  foreach($row in @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")){
   if(-not $row.CommandLine -and -not $row.ExecutablePath){throw '有任务无法核对，保留旧任务，暂不开始新发布。'}
   if(([string]$row.CommandLine).Replace('/','\').IndexOf($compare,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or ([string]$row.ExecutablePath).Replace('/','\').StartsWith($compare+'\',[StringComparison]::OrdinalIgnoreCase)){$row.ProcessId}
  }
 }
 try{
  $digest=[Security.Cryptography.SHA256]::Create()
  try{$key=[BitConverter]::ToString($digest.ComputeHash([Text.Encoding]::UTF8.GetBytes($Root.ToLowerInvariant()))).Replace('-','').Substring(0,24)}finally{$digest.Dispose()}
  $mutex=New-Object Threading.Mutex($false,('Local\FBUpload-Nov24-PublicationQueue-'+$key))
  try{$owned=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$owned=$true}
  if(-not $owned){State 'already_queued' '已有24号发布队列，未重复创建。';return}
  $runningPath=Join-Path $Root 'logs\eligible60-2026-11-24-status.json'
  if(Test-Path -LiteralPath $runningPath){
   $running=Get-Content -LiteralPath $runningPath -Raw -Encoding UTF8 | ConvertFrom-Json
   if($running.material_date -eq '2026-11-24' -and $running.phase -in @('preparing','running')){
    $owner=Get-CimInstance Win32_Process -Filter ('ProcessId='+$running.pid)
    $pattern='(?i)(?:^|\s)"?'+[regex]::Escape($Entry)+'"?(?=\s|$)'
    if($owner -and $owner.Name -in @('python.exe','pythonw.exe') -and $owner.CommandLine -match $pattern -and $owner.CreationDate.ToUniversalTime() -le [datetimeoffset]::Parse([string]$running.updated_at).UtcDateTime){State 'already_running' ('24号后台进程已在运行，PID：'+$running.pid+'；未重复启动。');return}
   }
  }
  $pointer=Join-Path $Root 'material-staging\eligible60-20261124-pending-import.json'
  # This waiter is PowerShell, not Python: it cannot deadlock the material
  # distributor that waits for project Python workers to exit before import.
  while($true){
   $live=@(Workers)
   if($live.Count){State 'waiting_workers' ('等待23号补发/今日分配/登录检查结束，PID：'+($live -join ','));Start-Sleep -Seconds 10;continue}
   $ready=$false
   if(Test-Path -LiteralPath $pointer){$value=Get-Content -LiteralPath $pointer -Raw -Encoding UTF8 | ConvertFrom-Json;$ready=($value.complete -eq $true)}
   if(-not $ready){State 'waiting_distribution' '等待11月24日60目标素材正式分配完成，请保留分配窗口。';Start-Sleep -Seconds 10;continue}
   break
  }
  $folder=Split-Path -Parent $Entry
  $manifest=Get-Content -LiteralPath (Join-Path $folder 'runtime-sha256.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach($property in $manifest.PSObject.Properties){
   if($property.Name -ne [IO.Path]::GetFileName($property.Name)){throw 'Invalid runtime path'}
   $file=Join-Path $folder $property.Name
   if(((Get-Item -LiteralPath $file -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Linked runtime file'}
   if((Get-SharedHash $file) -ne $property.Value){throw 'Runtime checksum mismatch'}
  }
  if((Get-SharedHash $Entry) -ne $EntrySha){throw 'Publisher checksum mismatch'}
  if(@(Workers).Count){throw 'Another project task started; original task preserved'}
  State 'starting' '24号素材已就绪，正在启动独立发布监控。'
  $start=New-Object Diagnostics.ProcessStartInfo
  $start.FileName=Join-Path $Root '.venv\Scripts\python.exe'
  $start.Arguments='-u "'+$Entry+'" "'+$Root+'"';$start.WorkingDirectory=$Root
  $start.UseShellExecute=$false;$start.CreateNoWindow=$true
  $start.EnvironmentVariables['FB_NOV24_RUN']=$Run
  $start.EnvironmentVariables['FB_NOV24_ROLE']='supervisor'
  $start.EnvironmentVariables['FB_PUBLISH_ISOLATED_BACKGROUND']='1'
  $start.EnvironmentVariables['PYTHONIOENCODING']='utf-8'
  # No console encoding or redirected pipes: the entry writes its own normal
  # diagnostic file before preflight imports and then logs all progress to disk.
  $process=[Diagnostics.Process]::Start($start)
  try{
   $ack=Join-Path $Root 'logs\eligible60-2026-11-24-status.json'
   for($i=0;$i -lt 300;$i++){
    if(Test-Path -LiteralPath $ack){
     $record=Get-Content -LiteralPath $ack -Raw -Encoding UTF8 | ConvertFrom-Json
     if($record.run_id -eq $Run -and $record.phase -in @('running','finished','review_required')){State 'started' ('24号后台监控已确认，PID：'+$record.pid);return}
     if($record.run_id -eq $Run -and $record.phase -eq 'failed'){throw ([string]$record.message)}
    }
    if($process.HasExited){
     $diagnostic=Join-Path $Root ('logs\nov24-launch-'+$Run+'.log')
     $detail=''
     if(Test-Path -LiteralPath $diagnostic){$detail=(@(Get-Content -LiteralPath $diagnostic -Encoding UTF8 -Tail 30) -join [Environment]::NewLine)}
     throw ('后台入口退出，代码：'+$process.ExitCode+'；诊断：'+$diagnostic+[Environment]::NewLine+$detail)
    }
    Start-Sleep -Milliseconds 200
   }
   State 'starting' ('后台核验尚未结束，未启动第二份；诊断：nov24-launch-'+$Run+'.log')
  }finally{$process.Dispose()}
 }catch{State 'failed' ('STOP：'+$_.Exception.Message)}finally{if($owned -and $mutex){$mutex.ReleaseMutex()};if($mutex){$mutex.Dispose()}}
}
if(-not $FunctionsOnly){Start-Nov24Queue $Root $Entry $EntrySha $Run}
