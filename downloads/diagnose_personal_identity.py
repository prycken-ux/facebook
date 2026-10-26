"""Read-only identity diagnostics; optional graceful closure of selected windows."""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import fb_upload as upload
from add_fb_accounts import locked
from chrome_profile_guard import require_profile_free

ROOT = Path(__file__).resolve().parent
NEW_ONBOARDING = tuple((f'fb{n:02d}', 'personal') for n in range(14, 24)) + tuple(
    ('fb10', f'page{n:02d}') for n in range(1, 11))

# Resolve the current process and exact profile locally before requesting a normal
# window close. No Stop-Process/taskkill, process-tree termination or raw output.
CLOSE_WINDOWS = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$fbInput = [Console]::In.ReadToEnd() | ConvertFrom-Json
$fbExpected = [IO.Path]::GetFullPath([string]$fbInput.profile).TrimEnd('\')
foreach ($fbRow in @(Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'")) {
    $fbCommand = [string]$fbRow.CommandLine
    if ($fbCommand -match '(?:^|\s)--type=') { continue }
    $fbMatch = [regex]::Match($fbCommand, '(?i)(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
    if (-not $fbMatch.Success) { continue }
    $fbActual = if ($fbMatch.Groups[1].Success) { $fbMatch.Groups[1].Value } else { $fbMatch.Groups[2].Value }
    $fbActual = [IO.Path]::GetFullPath($fbActual).TrimEnd('\')
    if (-not [string]::Equals($fbExpected, $fbActual, [StringComparison]::OrdinalIgnoreCase)) { continue }
    $fbProcess = Get-Process -Id $fbRow.ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $fbProcess -or $fbProcess.ProcessName -ne 'chrome') { continue }
    if ($fbProcess.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssfff') -ne $fbRow.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssfff')) { continue }
    [void]$fbProcess.CloseMainWindow()
}
'''


def close_selected_window(account):
    if sys.platform != 'win32':
        raise RuntimeError('关闭账号窗口需在 Windows 上传电脑运行。')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', CLOSE_WINDOWS],
        input=json.dumps({'profile': str(ROOT / 'profiles' / account)}).encode('utf-8'),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError('无法正常请求关闭此账号窗口，请手动关闭后重试。')
    for attempt in range(10):
        try:
            require_profile_free(ROOT / 'profiles' / account, account)
            return
        except RuntimeError:
            if attempt == 9:
                raise
            time.sleep(1)


def safe_url(value):
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    return urlunparse((parsed.scheme, parsed.hostname or '', parsed.path, '',
        urlencode({key: query[key][0] for key in ('id', 'locale') if query.get(key)}), ''))


def evidence(page, folder, label):
    record = {'url': safe_url(page.url)}
    try:
        record.update(title=page.title(), ready_state=page.evaluate('document.readyState'),
            headings=page.get_by_role('heading').all_text_contents()[:12])
    except Exception:
        record['metadata_unavailable'] = True
    upload.save_json(folder / (label + '.json'), record)
    try:
        page.screenshot(path=str(folder / (label + '.png')), timeout=10000)
    except Exception:
        pass


def inspect_entry(playwright, entry, folder, refresh_once=False, heading_timeout_ms=20000):
    folder.mkdir(parents=True, exist_ok=True)
    context = upload.launch_context(playwright, entry)
    page = None
    try:
        page = context.pages[0] if context.pages else context.new_page()
        response = page.goto(upload.english_url(entry['url']), wait_until='domcontentloaded', timeout=90000)
        upload.save_json(folder / 'navigation.json', {'status': response.status if response else None})
        upload.checkpoint(page)
        if refresh_once:
            from playwright.sync_api import TimeoutError as BrowserTimeout
            try:
                page.get_by_role('heading', name=entry['name'], exact=True).first.wait_for(timeout=heading_timeout_ms)
            except BrowserTimeout:
                evidence(page, folder, 'before-refresh')
                upload.checkpoint(page)
                print('主页标题未加载，刷新一次：', entry['account'], flush=True)
                page.reload(wait_until='domcontentloaded', timeout=90000)
        proof = upload.ensure_identity(page, entry)
        proof['checked_at'] = datetime.now().astimezone().isoformat()
        upload.save_json(ROOT / 'logs' / ('identity-' + entry['account'] + '-' + entry['target'] + '.json'), proof)
        evidence(page, folder, 'passed')
        return {'account': entry['account'], 'target': entry['target'], 'result': 'PASS'}
    except Exception as error:
        if page is not None:
            evidence(page, folder, 'failed')
        return {'account': entry['account'], 'target': entry['target'], 'result': 'CHECK_REQUIRED',
                'error': str(error).splitlines()[0][:500] or type(error).__name__}
    finally:
        context.close()


def selected_entries(accounts):
    if (not accounts or len(set(accounts)) != len(accounts)
            or any(not re.fullmatch(r'fb(?:0[1-9]|[1-9][0-9]+)', a) for a in accounts)):
        raise ValueError('请使用不重复的账号编号。')
    return select_pairs([(account, 'personal') for account in accounts])[0]


def select_pairs(pairs, allow_missing=False):
    config = upload.read_json(ROOT / 'upload_config.json', None)
    if not isinstance(config, dict) or not isinstance(config.get('targets'), list):
        raise ValueError('找不到有效上传配置。')
    if any(not isinstance(row, dict) for row in config['targets']):
        raise ValueError('上传配置含有无效条目。')
    selected, missing, urls = [], [], set()
    for account, target in pairs:
        rows = [r for r in config['targets'] if r.get('account') == account and r.get('target') == target]
        if not rows and allow_missing:
            missing.append(dict(account=account, target=target, result='NOT_REGISTERED'))
            continue
        if len(rows) != 1 or rows[0].get('type') != ('personal' if target == 'personal' else 'page'):
            raise ValueError(account + '/' + target + ' 没有唯一的对应主页配置。')
        upload.validate_entry(rows[0])
        identity = upload.target_key(rows[0]['url'])
        if identity in urls:
            raise ValueError('本批存在重复主页链接，未启动浏览器。')
        urls.add(identity)
        if not (ROOT / 'profiles' / account).is_dir():
            raise ValueError(account + ' 缺少原浏览器资料，未创建新资料。')
        selected.append(rows[0])
    return selected, missing


def main():
    parser = argparse.ArgumentParser(description='主页身份核验和诊断，不上传或发布视频')
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--accounts', help='只核验这些账号的个人主页，例如 fb14,fb15')
    scope.add_argument('--new-onboarding', action='store_true', help='继续 fb14～fb23 个人主页和 fb10/page01～page10；列出缺失配置并核验已登记目标')
    parser.add_argument('--close-windows', action='store_true', help='仅正常关闭指定账号的 Chrome 主窗口，不强制结束进程')
    parser.add_argument('--refresh-once', action='store_true', help='主页标题未加载时刷新一次，仍须通过原身份核验')
    args = parser.parse_args()
    with locked():
        if args.new_onboarding:
            entries, missing = select_pairs(NEW_ONBOARDING, allow_missing=True)
        else:
            entries, missing = selected_entries(args.accounts.split(',')), []
        print('已登记目标：', len(entries), '；尚未登记：', len(missing), flush=True)
        for entry in entries:
            print(entry['account'] + '/' + entry['target'], entry['name'], 'prepared=' + str(bool(entry.get('prepared_at'))),
                  'enabled=' + str(bool(entry.get('enabled'))), flush=True)
        for result in missing:
            print(result['account'] + '/' + result['target'], 'NOT_REGISTERED', flush=True)
        folder = ROOT / 'logs' / ('identity-diagnostic-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        folder.mkdir(parents=True)
        from playwright.sync_api import sync_playwright
        results = list(missing)
        upload.save_json(folder / 'results.json', results)
        with sync_playwright() as playwright:
            for entry in entries:
                account = entry['account']
                label = account + '/' + entry['target']
                print('Checking:', label, flush=True)
                try:
                    if args.close_windows:
                        close_selected_window(account)
                    result = inspect_entry(playwright, entry, folder / account / entry['target'], args.refresh_once)
                except Exception as error:
                    result = {'account': account, 'target': entry['target'], 'result': 'CHECK_REQUIRED',
                              'error': str(error).splitlines()[0][:500]}
                results.append(result)
                upload.save_json(folder / 'results.json', results)
                print(label, result['result'], result.get('error', ''), flush=True)
        print('诊断目录：', folder, flush=True)
        print('Target Result', flush=True)
        for result in sorted(results, key=lambda r: (r['account'], r['target'])):
            print(result['account'] + '/' + result['target'], result['result'], flush=True)
        print('核验结果不等于发布启用；本次没有准备视频、启用目标或改动发布记录。', flush=True)
        return 0 if all(r['result'] == 'PASS' for r in results) else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：', str(error).splitlines()[0], flush=True)
        raise SystemExit(1)
