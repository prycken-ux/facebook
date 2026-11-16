param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Queue,[Parameter(Mandatory=$true)][string]$Prepare,[Parameter(Mandatory=$true)][string]$Publisher)
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$host.UI.RawUI.WindowTitle='新增50账号排队发布（实拍，AI标签关闭）'
function Read-Record([string]$Path){if(Test-Path -LiteralPath $Path){return Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json};return $null}
function First24-Started {
  $material=Read-Record (Join-Path $Root 'material-staging\first24-pending-import.json')
  if(-not $material -or -not $material.sha256){return $true}
  $ptr=Read-Record (Join-Path $Root 'logs\nov16-new-first24-ai-disclosure-on-publication.json')
  if(-not $ptr){return $false}
  $plan=Read-Record (Join-Path $Root ('logs\'+$ptr.manifest))
  return ($plan -and $plan.sha256 -eq $ptr.sha256 -and $plan.payload.stage_sha256 -eq $material.sha256)
}
function First24-Finished($q){
  if(-not $q.payload.first24_stage_sha256){return $true}
  $ptr=Read-Record (Join-Path $Root 'logs\nov16-new-first24-ai-disclosure-on-publication.json')
  if(-not $ptr){return $false}
  $plan=Read-Record (Join-Path $Root ('logs\'+$ptr.manifest))
  if(-not $plan -or $plan.sha256 -ne $ptr.sha256 -or $plan.payload.stage_sha256 -ne $q.payload.first24_stage_sha256){return $false}
  $r=Read-Record (Join-Path $Root ('logs\'+([IO.Path]::GetFileNameWithoutExtension($ptr.manifest))+'-results.json'))
  if(-not $r){return $false}
  foreach($j in $plan.payload.jobs){if(@($r.attempts | Where-Object {$_.key -eq $j.key}).Count -eq 0){return $false}}
  return $true
}
function Live-Publishers {
  $python=Join-Path $Root '.venv\Scripts\python.exe';$found=@()
  foreach($p in @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")){
    $line=[string]$p.CommandLine;$exe=[string]$p.ExecutablePath
    if([string]::IsNullOrWhiteSpace($line) -and [string]::IsNullOrWhiteSpace($exe)){throw 'Cannot inspect Python processes safely'}
    if([string]::Equals($exe,$python,[StringComparison]::OrdinalIgnoreCase) -or $line.IndexOf($Root,[StringComparison]::OrdinalIgnoreCase) -ge 0){$found+=[long]$p.ProcessId}
  }
  return @($found)
}
$q=Read-Record $Queue
$hash=[Security.Cryptography.SHA256]::Create()
$key=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Root.ToLowerInvariant()+'|new50-real-request-20261116')))).Replace('-','').Substring(0,24)
$hash.Dispose()
$mutex=[Threading.Mutex]::new($false,('FBNew50Queue-'+$key))
$owned=$false
try{
  try{$owned=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$owned=$true}
  if(-not $owned){Write-Host '该批新增50个账号已有排队窗口，保留原窗口，不重复发布。';exit 0}
  if(-not $q){
    while(-not (First24-Started)){Write-Host '先等待前面44个目标启动并冻结原任务；本窗口只等候，不占用Python。请运行前面的44目标发布指令。';Start-Sleep -Seconds 15}
    & (Join-Path $Root '.venv\Scripts\python.exe') -u $Prepare $Root --prepare-only
    $prepareCode=$LASTEXITCODE
    if($prepareCode -ne 0){$mutex.ReleaseMutex();$owned=$false;Read-Host '素材准备未完成，原任务和源文件均保留；按回车关闭后可重跑同一入口继续' | Out-Null;exit $prepareCode}
    $q=Read-Record $Queue
  }
  if(-not $q -or $q.payload.authorization -ne 'user-confirmed-real-new50-request-20261116-v1'){throw 'Queue authorization mismatch'}
  Write-Host '新增fb25-fb74：每账号1条，全部实拍，AI标签关闭。等待前面44个目标结束后继续。'
  while($true){
    $live=@(Live-Publishers)
    if($live.Count -gt 0){Write-Host ('前一任务仍运行；等待其视频、评论及登录检查结束。PID：'+($live -join ','));Start-Sleep -Seconds 15;continue}
    try{$finished=First24-Finished $q}catch{$finished=$false}
    if(-not $finished){Write-Host '前面44个目标首轮尚未处理完；请保留本窗口并继续原发布窗口。15秒后检查。';Start-Sleep -Seconds 15;continue}
    & (Join-Path $Root '.venv\Scripts\python.exe') -u $Publisher $Root
    $code=$LASTEXITCODE
    if($code -eq 75){Write-Host '原任务仍在收尾，15秒后重试。';Start-Sleep -Seconds 15;continue}
    if($code -eq 0){Write-Host '新增50个账号本批视频和评论已完成。'}
    elseif($code -eq 130){Write-Host '已暂停；进度保留，重跑同一入口继续。'}
    else{Write-Host '仍有待人工处理或待核实项，请查看上方逐条结果；不会盲目重发已提交视频。'}
    break
  }
  $mutex.ReleaseMutex();$owned=$false
  Read-Host '本排队窗口已结束，按回车关闭' | Out-Null
}finally{if($owned){$mutex.ReleaseMutex()};$mutex.Dispose()}
