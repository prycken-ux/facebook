param([string]$ScriptPath = (Join-Path $PSScriptRoot 'open_fb63_original_profile_20261120.ps1'))
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($ScriptPath,[ref]$tokens,[ref]$errors)
if($errors.Count){ throw ($errors | ForEach-Object {$_.Message} | Out-String) }
# Load function definitions only; never execute the repair or any real process action.
$functions=$ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)
foreach($function in $functions){Invoke-Expression $function.Extent.Text}
function Assert($condition,[string]$message){if(-not $condition){throw $message}}
function Must-Stop([scriptblock]$action){$stopped=$false;try{& $action}catch{$stopped=$true};Assert $stopped 'An unsafe case was allowed'}
$fbRoot='/fixture/uploader'
$fbProfile='/fixture/uploader/profiles/fb63'
$script:rows=@()
function Get-CimInstance {param($ClassName,$Filter,$ErrorAction) return $script:rows}
$script:rows=@(
 [pscustomobject]@{ProcessId=98765;CommandLine='chrome --user-data-dir="/fixture/uploader/profiles/fb63" --headless=new'},
 [pscustomobject]@{ProcessId=42;CommandLine='chrome --user-data-dir=/fixture/uploader/profiles/fb630 --headless'},
 [pscustomobject]@{ProcessId=43;CommandLine='chrome --user-data-dir=/fixture/uploader/profiles/fb62'},
 [pscustomobject]@{ProcessId=44;CommandLine='chrome --type=renderer --user-data-dir=/fixture/uploader/profiles/fb63'},
 [pscustomobject]@{ProcessId=45;CommandLine='chrome --user-data-dir=/fixture/uploader/profiles/fb63-extra'}
)
$owners=@(Get-Fb63Owners)
Assert ($owners.Count -eq 1 -and $owners[0].ProcessId -eq 98765) 'Exact dynamic fb63 owner detection failed'
$process=[pscustomobject]@{MainWindowHandle=0;HasExited=$false}
Assert ((Get-Fb63WindowAction $owners[0] $process) -eq 'close_idle_headless') 'Idle headless action missing'
$process.MainWindowHandle=7
Assert ((Get-Fb63WindowAction $owners[0] $process) -eq 'restore') 'Visible window must never be killed'
$process.MainWindowHandle=0
Assert ((Get-Fb63WindowAction ([pscustomobject]@{CommandLine='chrome --user-data-dir=/fixture/uploader/profiles/fb63'}) $process) -eq 'blocked') 'Unknown hidden interactive browser must be retained'
$process.HasExited=$true
Must-Stop {Get-Fb63WindowAction $owners[0] $process}
$script:rows=@([pscustomobject]@{ProcessId=88;CommandLine=$null})
Must-Stop {Get-Fb63Owners}
$fbRoot='E:\FB-AutoUpload'
$script:rows=@([pscustomobject]@{ProcessId=99;ExecutablePath='E:\FB-AutoUpload\.venv\Scripts\python.exe';CommandLine='python task'})
Must-Stop {Assert-FbUploadIdle}
$script:rows=@([pscustomobject]@{ProcessId=99;ExecutablePath='C:\Other\python.exe';CommandLine='python E:/FB-AutoUpload/task.py'})
Must-Stop {Assert-FbUploadIdle}
$script:rows=@([pscustomobject]@{ProcessId=99;ExecutablePath='C:\Other\python.exe';CommandLine='python unrelated.py'})
Assert-FbUploadIdle
$script:rows=@([pscustomobject]@{ProcessId=99;ExecutablePath=$null;CommandLine=$null})
Must-Stop {Assert-FbUploadIdle}
$script:disposed=$false
$script:fake=[pscustomobject]@{ProcessName='chrome';StartTime=[datetime]'2026-11-20T07:00:00Z';HasExited=$false;Handle=123}
$script:fake | Add-Member ScriptMethod Dispose {$script:disposed=$true}
function Get-Process {param($Id,$ErrorAction) return $script:fake}
$row=[pscustomobject]@{ProcessId=98765;CreationDate=[datetime]'2026-11-20T07:00:00Z'}
$result=Get-Fb63PinnedProcess $row
Assert ($result -eq $script:fake) 'Matching pinned process must be accepted'
$row.CreationDate=[datetime]'2026-11-20T08:00:00Z'
Must-Stop {Get-Fb63PinnedProcess $row}
Assert $script:disposed 'A mismatched/recycled process must be released without killing it'
$script:fake.ProcessName='another'
Must-Stop {Get-Fb63PinnedProcess ([pscustomobject]@{ProcessId=98765;CreationDate=[datetime]'2026-11-20T07:00:00Z'})}
Write-Host 'PASS: PowerShell syntax, exact/dynamic profile ownership, visible/hidden window handling, uploader blockers and process identity checks. No Windows process was stopped.'
