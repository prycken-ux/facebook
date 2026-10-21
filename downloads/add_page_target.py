"""Add a Page posting target to an existing personal login, without publishing."""
import argparse
import copy
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import fb_upload as upload
from add_fb_accounts import locked

ROOT = Path(__file__).resolve().parent


def plan(config, account, target, name, url):
    if (not isinstance(config, dict) or not isinstance(config.get('targets'), list)
            or any(not isinstance(row, dict) for row in config['targets'])):
        raise ValueError('原上传配置格式异常，未修改。')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', account) or not re.fullmatch(r'[A-Za-z0-9_-]+', target):
        raise ValueError('账号和目标编号格式无效。')
    if target == 'personal':
        raise ValueError('公共主页不能使用 personal 目标，未覆盖个人主页。')
    if not name.strip() or '\n' in name or '\r' in name:
        raise ValueError('请填写单行公共主页名称。')
    key = upload.target_key(url)
    if not key.startswith('id:'):
        raise ValueError('请使用含数字 id 的公共主页链接，以便核对发布身份。')
    url = 'https://www.facebook.com/profile.php?id=' + key[3:]
    owners = [row for row in config['targets'] if row.get('account') == account
              and row.get('target') == 'personal']
    if len(owners) != 1 or owners[0].get('type') != 'personal':
        raise ValueError('该账号没有唯一的个人主页配置，已停止。')
    upload.validate_entry(owners[0])
    current = [row for row in config['targets'] if row.get('account') == account
               and row.get('target') == target]
    if len(current) > 1:
        raise ValueError('已有重复目标编号，未修改。')
    for row in config['targets']:
        if upload.target_key(row.get('url', '')) == key and row not in current:
            raise ValueError('该公共主页已登记在其他目标，未重复添加。')
    if current:
        row = current[0]
        if (row.get('type') != 'page' or row.get('name') != name.strip()
                or upload.target_key(row.get('url', '')) != key):
            raise ValueError('目标编号已用于其他配置，未覆盖。')
        upload.validate_entry(row)
        return copy.deepcopy(config), False
    updated = copy.deepcopy(config)
    row = dict(account=account, target=target, type='page', name=name.strip(), url=url,
               enabled=False, ai_label=owners[0].get('ai_label', True), excluded_files=[],
               workflow='page_flow_configured')
    upload.validate_entry(row)
    updated['targets'].append(row)
    return updated, True


def apply(account, target, name, url):
    with locked():
        config_path = ROOT / 'upload_config.json'
        if not config_path.is_file() or not (ROOT / 'profiles' / account).is_dir():
            raise ValueError('缺少原上传配置或该账号的浏览器资料，请放在原上传工具目录运行。')
        config = upload.read_json(config_path, None)
        updated, changed = plan(config, account, target, name, url)
        for folder in ('inbox', 'completed', 'failed'):
            (ROOT / 'videos' / account / target / folder).mkdir(parents=True, exist_ok=True)
        if changed:
            backup = ROOT / 'backups' / ('add-page-target-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            backup.mkdir(parents=True, exist_ok=False)
            shutil.copy2(config_path, backup / config_path.name)
            try:
                upload.save_json(config_path, updated)
            except Exception:
                shutil.copy2(backup / config_path.name, config_path)
                raise
            print('已备份原配置：', backup)
            print('已新增公共主页目标，尚未启用发布：', account, target, name)
        else:
            print('该目标已登记，保留现有准备及启用状态：', account, target, name)
        for row in updated['targets']:
            if row.get('account') == account:
                print(row['account'], row['target'], row['name'], row['url'])
                print('待发布目录：', ROOT / 'videos' / account / row['target'] / 'inbox')
        print('登录账号数：', len({row['account'] for row in updated['targets']}),
              '；发布目标数：', len(updated['targets']))
        print('下一步单独检查新公共主页身份；有视频后 prepare，再 enable。')
        print('本工具仅登记本地配置，没有上传或发布。')
        return updated


def main():
    parser = argparse.ArgumentParser(description='为现有个人登录增加公共主页发布目标，保留个人主页')
    parser.add_argument('--account', required=True)
    parser.add_argument('--target', default='page01')
    parser.add_argument('--name', required=True)
    parser.add_argument('--url', required=True)
    args = parser.parse_args()
    apply(args.account, args.target, args.name, args.url)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
