"""Noninteractive daily batch entry point with logs and readiness checking."""
import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import batch_upload as batch
import fb_upload as upload

ROOT = Path(__file__).resolve().parent
DEFAULT_ACCOUNTS = 'fb01,fb02,fb03,fb04,fb05,fb06,fb07'


def check_ready(accounts):
    config = upload.read_json(ROOT / 'upload_config.json', {'targets': []})
    state = upload.read_json(ROOT / 'logs' / 'publish_state.json', {})
    entries, errors = batch.select_targets(config, accounts, 'publish', state)
    for lock_name in ('upload.lock', 'batch.lock', 'scheduled.lock'):
        if (ROOT / 'logs' / lock_name).exists():
            errors.append('存在运行锁，请先结束原任务或核对失效锁：' + lock_name)
    for entry in entries:
        print(entry['account'], entry['target'], entry['name'])
    for error in errors:
        print('STOP：', error)
    if not errors:
        print('定时发布预检查通过；本次未上传或发布。')
    return 1 if errors else 0


def run(accounts, rounds):
    logs = ROOT / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    lock = logs / 'scheduled.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print('STOP：已有定时批次正在运行或遗留 scheduled.lock；未开始发布。')
        return 2
    try:
        with os.fdopen(fd, 'w') as file:
            file.write(str(os.getpid()))
        log_path = logs / ('scheduled-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
        final_code = 0
        with log_path.open('w', encoding='utf-8') as log:
            log.write('每轮每个账号最多一条；按各自 inbox 文件名排序，不固定历史日期。\n')
            log.flush()
            for index in range(rounds):
                log.write(f'\n开始第 {index+1}/{rounds} 轮\n')
                log.flush()
                command = [sys.executable, str(ROOT / 'batch_upload.py'), 'publish',
                           '--accounts=' + ','.join(accounts), '--continue-on-review']
                result = subprocess.run(command, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT, check=False,
                                        env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1'))
                log.write(f'\n本轮返回码：{result.returncode}\n')
                log.flush()
                if result.returncode not in (0, 3):
                    final_code = result.returncode
                    break
                if result.returncode == 3:
                    final_code = 3
        print('定时发布日志：', log_path)
        return final_code
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='七账号定时批量入口；不需要输入，不会自动解除待核对任务')
    parser.add_argument('--accounts', default=DEFAULT_ACCOUNTS)
    parser.add_argument('--rounds', type=int, default=1, help='本次运行轮数，每轮每个账号最多一条')
    parser.add_argument('--check', action='store_true', help='只检查设置与待核对记录，不发布')
    args = parser.parse_args()
    accounts = list(dict.fromkeys(value.strip() for value in args.accounts.split(',') if value.strip()))
    if not accounts or args.rounds < 1:
        parser.error('账号不能为空，轮数必须大于等于1')
    if args.check:
        return check_ready(accounts)
    return run(accounts, args.rounds)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
