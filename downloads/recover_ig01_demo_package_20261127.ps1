param([string]$Root='E:\IG-AutoUpload',[string]$Desktop=[Environment]::GetFolderPath('Desktop'))
$ErrorActionPreference='Stop'
if((Split-Path -Leaf $Root) -ne 'IG-AutoUpload'){throw 'Unexpected IG root'}
$base=Join-Path $Root 'logs/demo-recordings'
foreach($path in @($Root,(Join-Path $Root 'logs'),$base)) {
    $item=Get-Item -LiteralPath $path
    if(-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Linked or invalid recording directory preserved'}
}
$session=Get-ChildItem -LiteralPath $base -Directory |
    Where-Object { $_.Name -match '^[a-f0-9]{32}$' -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) } |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if(-not $session){throw 'No demonstration recording folder found'}
$files=@(Get-ChildItem -LiteralPath $session.FullName -File |
    Where-Object { $_.Extension.ToLowerInvariant() -in @('.json','.txt','.png') -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) })
if(-not $files.Count){throw 'No saved recording files found; preserve the original PowerShell output'}
if(-not $Desktop -or -not (Test-Path -LiteralPath $Desktop -PathType Container)){$Desktop=Join-Path $Root 'logs'}
$zip=Join-Path $Desktop ('IG-demo-recovered-20261127-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)+'.zip')
Compress-Archive -LiteralPath @($files.FullName) -DestinationPath $zip
Write-Host ('Recording source: '+$session.FullName)
Write-Host ('Recording files: '+$files.Count)
Write-Host ('Complete event metadata present: '+(Test-Path -LiteralPath (Join-Path $session.FullName 'recording.json')))
Write-Host ('Saved package: '+$zip)
if($env:OS -eq 'Windows_NT'){Start-Process explorer.exe -ArgumentList ('/select,"'+$zip+'"')}
