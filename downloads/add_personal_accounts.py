"""Add separately logged-in personal accounts after fb13; never creates Facebook identities."""
import argparse
import copy
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import add_fb_accounts as legacy
import fb_upload as upload

ROOT = Path(__file__).resolve().parent
MANIFEST = 'additional_personal_accounts.json'
SCHEMA = 'additional-personal-logins-v1'
SHORTCUTS = '新增账号登录'


def number(account):
    if not isinstance(account, str) or not re.fullmatch(r'fb(?:0[1-9]|[1-9][0-9]+)', account.lower()):
        raise ValueError('账号编号格式无效。')
    return int(account[2:])


def documents():
    config = upload.read_json(ROOT / 'upload_config.json', None)
    registry = upload.read_json(ROOT / 'account_registry.json', None)
    for doc, key in ((config, 'targets'), (registry, 'accounts')):
        if not isinstance(doc, dict) or not isinstance(doc.get(key), list) or any(not isinstance(row, dict) for row in doc[key]):
            raise ValueError('缺少或无法识别原上传配置/账号对应表，未覆盖。')
    manifest = upload.read_json(ROOT / MANIFEST, dict(schema=SCHEMA, slots={}, batches={}))
    if (not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA
            or not isinstance(manifest.get('slots'), dict) or not isinstance(manifest.get('batches'), dict)):
        raise ValueError('新增个人账号登记文件异常。')
    for account, slot in manifest['slots'].items():
        if number(account) < 14 or not isinstance(slot, dict) or slot.get('state') not in {'pending', 'registered'}:
            raise ValueError('新增个人账号登记条目异常。')
    return config, registry, manifest


def occupied_numbers(config, registry, manifest):
    accounts = [row.get('account', '') for row in config['targets'] + registry['accounts']]
    accounts += list(manifest['slots'])
    old = upload.read_json(ROOT / legacy.MANIFEST, {})
    if isinstance(old, dict) and isinstance(old.get('slots'), dict):
        accounts += list(old['slots'])
    for base in ('profiles', 'videos'):
        folder = ROOT / base
        if folder.is_dir():
            accounts += [p.name for p in folder.iterdir()]
    for name in {SHORTCUTS, legacy.SHORTCUT_FOLDER}:
        folder = ROOT / name
        if folder.is_dir():
            accounts += [p.name.split(' ', 1)[0] for p in folder.glob('*.lnk')]
    result = {13}
    for account in accounts:
        try:
            result.add(number(account))
        except ValueError:
            pass
    return result


def reserve(count, batch_id):
    if type(count) is not int or count < 1:
        raise ValueError('新增数量必须是正整数。')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
        raise ValueError('新增批次编号格式无效。')
    config, registry, original = documents()
    manifest = copy.deepcopy(original)
    batch = manifest['batches'].get(batch_id)
    if batch is not None:
        accounts = batch.get('accounts', [])
        if (batch.get('count') != count or len(accounts) != count or len(set(accounts)) != count
                or any(account not in manifest['slots'] or manifest['slots'][account].get('batch_id') != batch_id for account in accounts)):
            raise ValueError('同一新增批次的数量或账号已变化，未另建账号。')
        for account in accounts:
            if manifest['slots'][account]['state'] == 'registered' and not (ROOT / 'profiles' / account).is_dir():
                raise ValueError(account + ' 已登记但浏览器资料缺失，未创建空白资料代替。')
    else:
        start = max(occupied_numbers(config, registry, manifest)) + 1
        accounts = ['fb%02d' % i for i in range(start, start + count)]
        for account in accounts:
            for path in (ROOT / 'profiles' / account, ROOT / 'videos' / account,
                         ROOT / SHORTCUTS / (account + ' 登录.lnk')):
                if path.exists():
                    raise ValueError('账号路径已存在，未接管：' + str(path))
        manifest['batches'][batch_id] = dict(accounts=accounts, count=count,
            created=datetime.now().astimezone().isoformat())
        for account in accounts:
            manifest['slots'][account] = dict(state='pending', batch_id=batch_id, type='personal')
    # Persist ownership first, so a partial mkdir/shortcut failure can resume.
    if manifest != original:
        upload.save_json(ROOT / MANIFEST, manifest)
    for account in accounts:
        (ROOT / 'profiles' / account).mkdir(parents=True, exist_ok=True)
        for folder in ('inbox', 'completed', 'failed'):
            (ROOT / 'videos' / account / 'personal' / folder).mkdir(parents=True, exist_ok=True)
    return accounts


def shortcut_items(accounts, chrome):
    return [dict(path=str(ROOT / SHORTCUTS / (account + ' 登录.lnk')), chrome=str(chrome),
                 working=str(ROOT), description=account + ' 新增个人账号独立登录',
                 arguments=subprocess.list2cmdline([
                     '--user-data-dir=' + str(ROOT / 'profiles' / account), '--profile-directory=Default',
                     '--no-first-run', '--no-default-browser-check', '--new-window',
                     'https://www.facebook.com/?locale=en_US'])) for account in accounts]


def prepare(count, batch_id):
    if sys.platform != 'win32':
        raise ValueError('登录入口需在原 Windows 上传电脑上创建。')
    chrome = legacy.find_chrome()
    with legacy.locked():
        accounts = reserve(count, batch_id)
        folder = ROOT / SHORTCUTS
        folder.mkdir(exist_ok=True)
        items = shortcut_items(accounts, chrome)
        existing = [Path(item['path']) for item in items if Path(item['path']).is_file()]
        if existing:
            backup = ROOT / 'backups' / ('personal-shortcuts-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            backup.mkdir(parents=True)
            for path in existing:
                shutil.copy2(path, backup / path.name)
        legacy.write_shortcuts(items)
    os.startfile(str(folder))
    print('新增个人账号登录入口：', ', '.join(accounts))
    print('入口文件夹：', folder)
    print('同一批次重复运行复用这些编号；原账号配置和发布记录保持原样。')
    print('请逐个双击入口，在 Facebook 正常登录；每个编号只登录对应账号。')
    print('记下每个账号的本人主页名称和链接，登记后再核验身份、prepare 和 enable。')
    return accounts


def canonical_url(url):
    identity = upload.target_key(url.strip())
    return ('https://www.facebook.com/profile.php?id=' + identity[3:] if identity.startswith('id:')
            else 'https://www.facebook.com/' + identity[5:])


def register(account, name, url):
    if number(account) < 14 or account != account.lower():
        raise ValueError('此工具只登记 fb14 以后的新个人账号，不改原有账号。')
    name = name.strip()
    if not name or any(ord(char) < 32 for char in name):
        raise ValueError('本人主页名称必须是非空单行文字。')
    url = canonical_url(url)
    mapping = dict(account=account, target='personal', type='personal', name=name, url=url,
                   workflow='personal_recording_v1')
    upload.validate_entry(mapping)
    with legacy.locked():
        original = documents()
        config, registry, manifest = copy.deepcopy(original)
        slot = manifest['slots'].get(account)
        if not slot or not (ROOT / 'profiles' / account).is_dir():
            raise ValueError('该编号尚未预留独立登录资料，请先 prepare。')
        current = [row for row in config['targets'] if row.get('account') == account and row.get('target') == 'personal']
        known = [row for row in registry['accounts'] if row.get('account') == account]
        if current or known:
            if (slot.get('state') != 'registered' or slot.get('mapping') != mapping
                    or len(current) != 1 or len(known) != 1
                    or any(any(row.get(field) != mapping[field] for field in mapping) for row in current + known)):
                raise ValueError('新账号对应关系与已有记录冲突，未覆盖。')
            print('该个人账号已登记，保留准备/启用状态：', account, name)
            return False
        if any(row.get('account') == account for row in config['targets']):
            raise ValueError('该编号已配置其他目标，未接管。')
        identity = upload.target_key(url)
        if any(upload.target_key(row.get('url', '')) == identity for row in config['targets'] + registry['accounts']):
            raise ValueError('该本人主页已登记，未重复添加。')
        config['targets'].append(dict(mapping, enabled=False, ai_label=True, excluded_files=[]))
        registry['accounts'].append(dict(mapping, profile='profiles/' + account,
            inbox='videos/' + account + '/personal/inbox'))
        slot.update(state='registered', mapping=mapping)
        paths = [ROOT / 'upload_config.json', ROOT / 'account_registry.json', ROOT / MANIFEST]
        backup = ROOT / 'backups' / ('new-personal-register-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True)
        for path in paths:
            shutil.copy2(path, backup / path.name)
        try:
            for path, doc in zip(paths, (config, registry, manifest)):
                upload.save_json(path, doc)
        except Exception:
            for path in paths:
                shutil.copy2(backup / path.name, path)
            raise
        print('已登记个人发布目标：', account, name, url)
        print('待发布目录：', ROOT / 'videos' / account / 'personal/inbox')
        print('原配置备份：', backup)
        print('新目标尚未启用；下一步 check-identity，再有视频后 prepare 和 enable。')
        return True


def parse_accounts(value):
    accounts = value.split(',')
    if not accounts or len(set(accounts)) != len(accounts) or any(account != account.lower() for account in accounts):
        raise ValueError('请指定不重复的账号编号。')
    for account in accounts:
        number(account)
    return accounts


def open_accounts(accounts):
    if sys.platform != 'win32':
        raise ValueError('账号窗口需在 Windows 上传电脑上打开。')
    chrome = legacy.find_chrome()
    with legacy.locked():
        config, registry, manifest = documents()
        selected = []
        for account in accounts:
            number(account)
            if not (ROOT / 'profiles' / account).is_dir():
                raise ValueError(account + ' 没有原浏览器资料，未创建空白资料代替。')
            primary = [row for row in registry['accounts'] if row.get('account') == account]
            configured = [row for row in config['targets'] if row.get('account') == account]
            if len(configured) == 1 or len(primary) == 1:
                preferred = (primary[0].get('target') or ('personal' if primary[0].get('type') == 'personal' else 'page01')) if len(primary) == 1 else None
                entries = configured if len(configured) == 1 else [row for row in configured if row.get('target') == preferred]
                if len(entries) != 1:
                    raise ValueError(account + ' 缺少唯一原目标配置。')
                upload.validate_entry(entries[0])
                selected.append((account, entries[0]['name'], entries[0]['url']))
            elif not primary and account in manifest['slots'] and manifest['slots'][account]['state'] == 'pending':
                selected.append((account, '新增个人账号待登录', 'https://www.facebook.com/?locale=en_US'))
            else:
                raise ValueError(account + ' 缺少唯一账号对应关系。')
        for account, name, url in selected:
            print('正在打开：', account, name, flush=True)
            subprocess.Popen([str(chrome), '--user-data-dir=' + str(ROOT / 'profiles' / account),
                '--profile-directory=Default', '--no-first-run', '--no-default-browser-check', '--new-window', url])
    return selected


def main():
    parser = argparse.ArgumentParser(description='从 fb14 起接入新的个人账号，保留已有登录和发布配置')
    commands = parser.add_subparsers(dest='action', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--count', required=True, type=int)
    prep.add_argument('--batch-id', required=True, help='本次新增的固定编号；重复使用同编号不会另建一批')
    reg = commands.add_parser('register')
    reg.add_argument('--account', required=True)
    reg.add_argument('--name', required=True)
    reg.add_argument('--url', required=True)
    op = commands.add_parser('open')
    op.add_argument('--accounts', required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.count, args.batch_id)
    elif args.action == 'register':
        register(args.account, args.name, args.url)
    else:
        open_accounts(parse_accounts(args.accounts))
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
