"""Read-only Windows Chrome profile ownership checks; never terminate a process."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Only the exact browser profile is compared locally. Never return a command
# line, environment, cookies or credentials from Win32_Process.
QUERY = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$fbInput = [Console]::In.ReadToEnd() | ConvertFrom-Json
$fbExpected = [IO.Path]::GetFullPath([string]$fbInput.profile).TrimEnd('\')
$fbRows = @()
foreach ($fbProcess in @(Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction Stop)) {
    $fbCommand = [string]$fbProcess.CommandLine
    if ($fbCommand -match '(?:^|\s)--type=') { continue }
    $fbMatch = [regex]::Match($fbCommand, '(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
    if (-not $fbMatch.Success) { continue }
    $fbActual = if ($fbMatch.Groups[1].Success) { $fbMatch.Groups[1].Value } else { $fbMatch.Groups[2].Value }
    $fbActual = [IO.Path]::GetFullPath($fbActual).TrimEnd('\')
    if ([string]::Equals($fbExpected, $fbActual, [StringComparison]::OrdinalIgnoreCase)) {
        $fbRows += [pscustomobject]@{ pid = [long]$fbProcess.ProcessId; name = 'chrome.exe' }
    }
}
ConvertTo-Json -InputObject @($fbRows) -Compress
'''


def profile_owners(profile):
    if sys.platform != 'win32':
        return []
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', QUERY],
                                input=json.dumps({'profile': str(profile)}).encode('utf-8'),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
        if result.returncode:
            raise ValueError('query failed')
        rows = json.loads(result.stdout.decode('utf-8-sig'))
        if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != {'pid', 'name'}
                or type(row['pid']) is not int or row['pid'] <= 0 or row['name'] != 'chrome.exe' for row in rows):
            raise ValueError('invalid process data')
        return rows
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError):
        raise RuntimeError('无法核对该 Chrome 资料的占用状态，尚未启动浏览器；请检查本机 PowerShell/CIM 服务。') from None


def require_profile_free(profile, account):
    owners = profile_owners(profile)
    if owners:
        pids = ', '.join(str(row['pid']) for row in owners)
        raise RuntimeError(f'{account} 的 Chrome 资料仍被占用（进程 PID：{pids}）。请关闭该账号所有 Chrome 窗口；本次尚未启动浏览器或选择视频。')


def main():
    parser = argparse.ArgumentParser(description='只检查指定账号的 Chrome 浏览器资料占用，不关闭任何程序')
    parser.add_argument('--accounts', default='fb10,fb11')
    args = parser.parse_args()
    accounts = args.accounts.split(',')
    if any(not re.fullmatch(r'fb(?:0[1-9]|1[0-3])', account) for account in accounts):
        raise ValueError('请使用 fb01～fb13 账号编号。')
    for account in accounts:
        owners = profile_owners(ROOT / 'profiles' / account)
        print(account, '仍被占用，Chrome PID：' + ', '.join(str(row['pid']) for row in owners) if owners else '未发现 Chrome 进程占用')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
