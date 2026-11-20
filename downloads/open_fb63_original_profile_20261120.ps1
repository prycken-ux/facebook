$ErrorActionPreference = 'Stop'
$fbRoot = 'E:\FB-AutoUpload'
$fbProfile = Join-Path $fbRoot 'profiles\fb63'
$fbConfig = Join-Path $fbRoot 'upload_config.json'
$fbShortcutFolder = Join-Path $fbRoot '新增账号登录'
$fbShortcut = Join-Path $fbShortcutFolder 'fb63 登录.lnk'
$fbOwnedLocks = @()
$fbToken = [string]$PID

function Assert-Fb63OriginalPath([string]$Path, [bool]$Directory = $true) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'A managed path is a link. Nothing was changed.' }
    if ($Directory -and -not $item.PSIsContainer) { throw 'Original fb63 directory is missing. No replacement profile was created.' }
    if (-not $Directory -and $item.PSIsContainer) { throw 'A required file is not a normal file.' }
}

function Assert-FbUploadIdle {
    $busy = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop | Where-Object {
        ((-not $_.ExecutablePath) -and (-not $_.CommandLine)) -or
        (([string]$_.ExecutablePath).Replace('/','\').StartsWith($fbRoot + '\', [StringComparison]::OrdinalIgnoreCase)) -or
        (([string]$_.CommandLine).Replace('/','\').IndexOf($fbRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
    if ($busy.Count) { throw ('An uploader/login task is running (PID: ' + (($busy | ForEach-Object { $_.ProcessId }) -join ',') + '). Wait for it to finish, then run this same command again. No process was stopped.') }
}

function Get-Fb63Owners {
    foreach ($row in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction Stop)) {
        $command = [string]$row.CommandLine
        if (-not $command) { throw 'A Chrome process cannot be inspected. Nothing was stopped.' }
        if ($command -match '(?i)(?:^|\s)--type(?:=|\s)') { continue }
        $match = [regex]::Match($command, '(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
        if (-not $match.Success) { continue }
        $actual = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value }
        if ([string]::Equals([IO.Path]::GetFullPath($actual).TrimEnd('\'), $fbProfile, [StringComparison]::OrdinalIgnoreCase)) { $row }
    }
}

function Get-Fb63WindowAction($Row, $Process) {
    if ($Process.HasExited) { throw 'Chrome exited before inspection. Nothing was stopped.' }
    if ($Process.MainWindowHandle -ne 0) { return 'restore' }
    if ([string]$Row.CommandLine -match '(?i)(?:^|\s)--headless(?:=new|=old)?(?:\s|$)') { return 'close_idle_headless' }
    return 'blocked'
}

function Get-Fb63PinnedProcess($Row) {
    $process = Get-Process -Id $Row.ProcessId -ErrorAction Stop
    try {
        $null = $process.Handle
        if ($process.HasExited -or $process.ProcessName -ne 'chrome' -or
            $process.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $Row.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')) {
            throw 'Chrome process identity changed. Nothing was stopped.'
        }
        return $process
    } catch { $process.Dispose(); throw }
}

try {
    foreach ($path in @($fbRoot, (Join-Path $fbRoot 'profiles'), $fbProfile, (Join-Path $fbProfile 'Default'), (Join-Path $fbRoot 'logs'))) { Assert-Fb63OriginalPath $path }
    Assert-Fb63OriginalPath $fbConfig $false
    Assert-FbUploadIdle
    foreach ($name in @('batch.lock','upload.lock')) {
        $path = Join-Path $fbRoot ('logs\' + $name)
        try { $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read) }
        catch { throw ('Upload lock exists or is unavailable: ' + $path + '. No browser was stopped. Finish the current task first; do not delete a live task lock.') }
        try { $data = [Text.Encoding]::ASCII.GetBytes($fbToken); $stream.Write($data,0,$data.Length); $stream.Flush() }
        finally { $stream.Dispose() }
        $fbOwnedLocks += $path
    }
    Assert-FbUploadIdle
    $chromePaths = @(foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ($base) { Join-Path $base 'Google\Chrome\Application\chrome.exe' }
    })
    $fbChrome = $chromePaths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $fbChrome) { throw 'Installed Google Chrome was not found. No original profile was changed.' }
    $fbChrome = [IO.Path]::GetFullPath($fbChrome)
    $fbArgs = '--user-data-dir="' + $fbProfile + '" --profile-directory=Default --no-first-run --no-default-browser-check --new-window https://www.facebook.com/?locale=en_US'
    $owners = @(Get-Fb63Owners)
    if ($owners.Count -gt 1) { throw 'More than one fb63 browser parent was found. Nothing was stopped.' }
    $fbVisible = $null
    if ($owners.Count -eq 1) {
        $row = $owners[0]
        $process = Get-Fb63PinnedProcess $row
        try {
            $action = Get-Fb63WindowAction $row $process
            if ($action -eq 'restore') {
                $fbVisible = $process.MainWindowHandle
            } elseif ($action -eq 'close_idle_headless') {
                Assert-FbUploadIdle
                Write-Host ('Closing verified idle fb63 background Chrome PID ' + $row.ProcessId + ' only...')
                $process.Refresh()
                if ($process.HasExited -or $process.MainWindowHandle -ne 0) { throw 'fb63 process/window changed. Nothing was stopped.' }
                $process.Kill()
                if (-not $process.WaitForExit(10000)) { throw 'fb63 did not exit. No second browser was opened.' }
            } else {
                throw ('fb63 Chrome is still starting or has a hidden interactive window (PID ' + $row.ProcessId + '). No process was stopped. Close this account normally and retry.')
            }
        } finally { $process.Dispose() }
    }
    if (-not (Test-Path -LiteralPath $fbShortcutFolder)) { [void][IO.Directory]::CreateDirectory($fbShortcutFolder) }
    Assert-Fb63OriginalPath $fbShortcutFolder
    if (Test-Path -LiteralPath $fbShortcut) {
        Assert-Fb63OriginalPath $fbShortcut $false
        $backup = Join-Path $fbRoot ('backups\fb63-login-entry-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff'))
        Assert-Fb63OriginalPath (Join-Path $fbRoot 'backups')
        [void][IO.Directory]::CreateDirectory($backup)
        Copy-Item -LiteralPath $fbShortcut -Destination (Join-Path $backup 'fb63-original.lnk') -ErrorAction Stop
    }
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($fbShortcut)
    $link.TargetPath = $fbChrome
    $link.Arguments = $fbArgs
    $link.WorkingDirectory = $fbRoot
    $link.Description = 'fb63 original Facebook login - normal Chrome window'
    $link.WindowStyle = 1
    $link.Save()
    if ($fbVisible) {
        if (-not ('Fb63OriginalWindow' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class Fb63OriginalWindow {
 [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr window, int command);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
}
'@
        }
        [void][Fb63OriginalWindow]::ShowWindowAsync($fbVisible,9)
        [void][Fb63OriginalWindow]::SetForegroundWindow($fbVisible)
        Write-Host 'fb63 already has a normal window; restored it without closing any tab.'
    } else {
        $remaining = @(Get-Fb63Owners)
        if ($remaining.Count) { throw 'fb63 was opened elsewhere. No second browser was opened.' }
        $start = New-Object Diagnostics.ProcessStartInfo
        $start.FileName = $fbChrome
        $start.Arguments = $fbArgs
        $start.WorkingDirectory = $fbRoot
        $start.UseShellExecute = $false
        $started = [Diagnostics.Process]::Start($start)
        try {
            [void]$started.WaitForInputIdle(15000)
            if ($started.HasExited) { throw 'Chrome exited during startup. Original data was retained; send this output for diagnosis.' }
            Write-Host 'fb63 normal Chrome launch requested with its original profile.'
        } finally { $started.Dispose() }
    }
    Write-Host ('Login shortcut repaired: ' + $fbShortcut)
    Write-Host 'Original login/profile, extensions, videos and publication records were retained. No video or comment was sent.'
    Write-Host 'If Facebook shows login/security verification, complete it manually in this fb63 window.'
} catch {
    Write-Host ('STOP: ' + $_.Exception.Message) -ForegroundColor Red
} finally {
    foreach ($path in $fbOwnedLocks) {
        if ((Test-Path -LiteralPath $path -PathType Leaf) -and [IO.File]::ReadAllText($path) -eq $fbToken) { Remove-Item -LiteralPath $path -ErrorAction Stop }
    }
}
