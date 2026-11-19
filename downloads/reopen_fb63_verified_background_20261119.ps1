$ErrorActionPreference = 'Stop'
$fb63Profile = 'E:\FB-AutoUpload\profiles\fb63'
if (-not (Test-Path -LiteralPath $fb63Profile -PathType Container)) { throw 'Original fb63 profile is missing; no new profile was created.' }
$fbPython = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")
$fbBusy = @($fbPython | Where-Object {
    ((-not $_.ExecutablePath) -and (-not $_.CommandLine)) -or
    ([string]$_.ExecutablePath -like 'E:\FB-AutoUpload\*') -or
    (([string]$_.CommandLine).Replace('/','\') -like '*E:\FB-AutoUpload*')
})
if ($fbBusy.Count) { throw 'An uploader or uninspectable Python task is running. Wait for it to finish first.' }
$fb63Info = Get-CimInstance Win32_Process -Filter "Name='chrome.exe' AND ProcessId=11940"
if ($null -ne $fb63Info) {
    $fb63Arg = [regex]::Match([string]$fb63Info.CommandLine, '(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
    if (-not $fb63Arg.Success) { throw 'PID 11940 has no verified profile; nothing was stopped.' }
    $fb63Actual = if ($fb63Arg.Groups[1].Success) { $fb63Arg.Groups[1].Value } else { $fb63Arg.Groups[2].Value }
    if (-not [string]::Equals([IO.Path]::GetFullPath($fb63Actual).TrimEnd('\'), $fb63Profile, [StringComparison]::OrdinalIgnoreCase)) { throw 'PID 11940 is not fb63; nothing was stopped.' }
    if ([string]$fb63Info.CommandLine -match '(?i)(?:^|\s)--type(?:=|\s)') { throw 'This is not the verified browser parent process; nothing was stopped.' }
    if ([string]$fb63Info.CommandLine -notmatch '(?i)(?:^|\s)--headless(?:=new)?(?:\s|$)') { throw 'This is not verified background Chrome. Close the fb63 window normally.' }
    $fb63Process = Get-Process -Id 11940 -ErrorAction Stop
    try {
        $null = $fb63Process.Handle
        if ($fb63Process.ProcessName -ne 'chrome' -or $fb63Process.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $fb63Info.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')) { throw 'Process identity changed; nothing was stopped.' }
        if ($fb63Process.MainWindowHandle -ne 0) { throw 'fb63 has a visible window. Close it normally first.' }
        if (-not $fb63Process.HasExited) {
            $fb63Process.Kill()
            if (-not $fb63Process.WaitForExit(10000)) { throw 'fb63 did not exit. No second browser was opened.' }
        }
    } finally { $fb63Process.Dispose() }
}
& 'E:\FB-AutoUpload\.venv\Scripts\python.exe' -u -c "import sys,subprocess;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from chrome_profile_guard import require_profile_free;from add_fb_accounts import find_chrome;p=Path(sys.argv[1])/'profiles'/'fb63';require_profile_free(p,'fb63');subprocess.Popen([str(find_chrome()),'--user-data-dir='+str(p),'--profile-directory=Default','--no-first-run','--no-default-browser-check','--new-window','https://www.facebook.com/?locale=en_US'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)" 'E:\FB-AutoUpload'
if ($LASTEXITCODE -ne 0) { throw 'fb63 is still blocked. Send the output above; do not delete the profile.' }
Write-Host 'Requested fb63 login window. No videos were uploaded.'
