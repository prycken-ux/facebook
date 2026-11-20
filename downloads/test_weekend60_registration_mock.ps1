param([Parameter(Mandatory=$true)][string]$RegistrationScript,[Parameter(Mandatory=$true)][string]$Fixture)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($RegistrationScript,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors | Out-String)}
$script:FixtureData=Get-Content -LiteralPath $Fixture -Raw -Encoding UTF8 | ConvertFrom-Json
$script:TaskMap=@{};$script:Registered=@();$script:Disabled=@();$script:Started=@();$script:FailName=''
function Get-ScheduledTask {param($TaskName,$ErrorAction) if($script:TaskMap.ContainsKey($TaskName)){return $script:TaskMap[$TaskName]}}
function Register-ScheduledTask {
 param($TaskName,$Xml,$ErrorAction)
 if($TaskName -eq $script:FailName){throw 'Simulated registration failure'}
 [xml]$x=$Xml
 $script:Registered+=$TaskName
 $script:TaskMap[$TaskName]=[pscustomobject]@{TaskName=$TaskName;State='Disabled';Actions=@([pscustomobject]@{Execute=[string]$x.Task.Actions.Exec.Command;Arguments=[string]$x.Task.Actions.Exec.Arguments;WorkingDirectory=[string]$x.Task.Actions.Exec.WorkingDirectory});Triggers=@([pscustomobject]@{StartBoundary=[string]$x.Task.Triggers.TimeTrigger.StartBoundary;EndBoundary=[string]$x.Task.Triggers.TimeTrigger.EndBoundary;CimClass=[pscustomobject]@{CimClassName='MSFT_TaskTimeTrigger'};Repetition=[pscustomobject]@{Interval=$null}})}
}
function Enable-ScheduledTask {param($TaskName,$ErrorAction) $script:TaskMap[$TaskName].State='Ready'}
function Disable-ScheduledTask {param($TaskName) $script:TaskMap[$TaskName].State='Disabled';$script:Disabled+=$TaskName}
function Get-ScheduledTaskInfo {param($TaskName,$ErrorAction) return [pscustomobject]@{NextRunTime='fixture-local-time';LastTaskResult=0}}
function Start-ScheduledTask {param($TaskName,$ErrorAction) $script:Started+=$TaskName;$script:TaskMap[$TaskName].State='Running'}
$code=[IO.File]::ReadAllText($RegistrationScript)
$code=$code.Replace('$d=[Console]::In.ReadToEnd() | ConvertFrom-Json','$d=$script:FixtureData')
$code=$code.Replace('[Security.Principal.WindowsIdentity]::GetCurrent().User.Value',"'S-1-5-21-fixture'")
$code=$code.Replace('[DateTimeOffset]::UtcNow',"[DateTimeOffset]::Parse('2026-11-20T09:15:00Z')")
$block=[scriptblock]::Create($code)
function Assert($value,$message){if(-not $value){throw $message}}
$output=@(& $block)
Assert ($script:Registered.Count -eq 3) 'Must register exactly three one-shot dates'
Assert ($output.Count -eq 3) 'Must return three receipts'
Assert ($script:Started.Count -eq 1 -and $script:Started[0] -eq $script:FixtureData.tasks[0].name) 'Late setup may start only Friday, never Saturday/Sunday'
$output=@(& $block)
Assert ($script:Registered.Count -eq 3) 'Repeated setup must not replace matching tasks'
Assert ($script:Started.Count -eq 2 -and @($script:Started | Where-Object {$_ -ne $script:FixtureData.tasks[0].name}).Count -eq 0) 'Future tasks must never be started during setup'
$bad=$script:FixtureData.tasks[1].name
$script:TaskMap[$bad].Actions[0].Arguments='unexpected other source'
$failed=$false;try{& $block | Out-Null}catch{$failed=$true}
Assert $failed 'Mismatched existing action must be refused'
Assert ($script:Registered.Count -eq 3) 'Mismatched action must not be overwritten'
$script:TaskMap=@{};$script:Registered=@();$script:Disabled=@();$script:Started=@();$script:FailName=$script:FixtureData.tasks[1].name
$failed=$false;try{& $block | Out-Null}catch{$failed=$true}
Assert $failed 'Registration failure must propagate'
Assert ($script:Disabled.Count -eq 1 -and $script:Disabled[0] -eq $script:FixtureData.tasks[0].name) 'Partial failure disables only this setup newly-created task'
Assert ($script:Started.Count -eq 0) 'Partial setup failure must never launch any publisher'
Write-Host 'PASS: actual PowerShell execution with mocked scheduler API;three dates, idempotent registration, fixed-source conflict, partial failure and no premature future runs.'
