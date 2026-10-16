"""Reconcile a user-verified existing post locally; never opens a browser."""
import argparse
import copy
import hashlib
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import fb_upload as upload


def validate_filename(filename):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._ -]*\.mp4', filename, re.I):
        raise ValueError('需指定 MP4 文件名，不能包含路径。')


def mark_verified(entry, filename, url, correct_from_filename=None):
    """Caller must hold upload.lock. Confirmation is supplied by the user."""
    upload.validate_entry(entry)
    validate_filename(filename)
    if correct_from_filename:
        validate_filename(correct_from_filename)
        if correct_from_filename == filename:
            raise ValueError('更正来源不能与实际发布的文件同名。')
    link = upload.normalize_video_permalink(url)
    inbox = upload.inbox_for(entry)
    video = next((path for path in (inbox / filename, inbox.parent / 'completed' / filename)
                  if path.is_file() and path.stat().st_size), None)
    if video is None:
        raise ValueError('inbox 和 completed 中都没有找到指定的非空视频，未修改记录。')
    state_path = upload.ROOT / 'logs' / 'publish_state.json'
    original = upload.read_json(state_path, {})
    state = copy.deepcopy(original)
    key = upload.job_key(entry, video)
    identity = (entry['account'], entry['target'])
    named = [other_key for other_key, row in state.items()
             if (row.get('account'), row.get('target')) == identity
             and Path(row.get('video', '')).name == filename]
    if named and key not in named:
        raise ValueError('当前视频内容与原任务的内容指纹不同，未修改记录。')
    row = state.get(key, {})
    if row and (row.get('account'), row.get('target')) != identity:
        raise ValueError('任务属于其他账号或目标，未修改记录。')
    if row.get('permalink') and str(row['permalink']).rstrip('/') != link:
        raise ValueError('指定视频已有不同链接，未覆盖。')
    owner = re.search(r'/([0-9]+)/videos/', link)
    proof = row.get('identity_validation') or {}
    if entry['type'] == 'personal' and owner and proof.get('session_marker'):
        if hashlib.sha256(('personal:' + owner.group(1)).encode('ascii')).hexdigest() != proof['session_marker']:
            raise ValueError('链接作者与原任务身份不一致，未修改记录。')
    now = datetime.now().astimezone().isoformat()
    corrected = []
    for other_key, other in state.items():
        if other_key == key or str(other.get('permalink', '')).rstrip('/') != link:
            continue
        if (not correct_from_filename or (other.get('account'), other.get('target')) != identity
                or Path(other.get('video', '')).name != correct_from_filename
                or other.get('status') != 'published'):
            raise ValueError('该链接已关联其他记录，且不符合指定的更正范围；未修改记录。')
        other['misidentified_permalink'] = other.pop('permalink')
        other.update(status='misidentified_post', corrected_to_job=key, corrected_at=now)
        corrected.append(other_key)
    if row.get('status') != 'published' or row.get('permalink') != link:
        row = dict(row)
        row.setdefault('created', now)
        row.update(account=entry['account'], target=entry['target'], url=entry['url'],
                   video=str(video), caption=str(video.with_suffix('.txt')), status='published',
                   permalink=link, confirmation_method='user_verified_existing_post', confirmed_at=now)
        state[key] = row
    if state != original:
        backup = upload.ROOT / 'backups' / ('verified-post-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True, exist_ok=False)
        if state_path.exists():
            shutil.copy2(state_path, backup / state_path.name)
        upload.save_json(state_path, state)
    for other_key in corrected:
        print('已更正误认的链接关联，保留原记录历史：', other_key[:12])
    print('已标记发布成功：', entry['account'], entry['target'], filename, link)
    if video.parent == inbox:
        caption = video.with_suffix('.txt')
        if caption.is_file():
            try:
                upload.archive(video, caption)
                print('视频和文案已归档。')
            except Exception as error:
                print('成功记录已保存；归档未完成，未覆盖已有文件：', error)
        else:
            print('成功记录已保存；没有找到同名 TXT，视频保留原位置。')
    return key


def main():
    parser = argparse.ArgumentParser(description='只补记用户已确认的发布结果，不上传或发布')
    parser.add_argument('--account', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--filename', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--correct-from-filename')
    args = parser.parse_args()
    lock = upload.ROOT / 'logs' / 'upload.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print('STOP：上传任务仍在运行或锁未清理，未修改任何发布记录。')
        return 2
    try:
        with os.fdopen(fd, 'w') as file:
            file.write(str(os.getpid()))
        config = upload.read_json(upload.CONFIG, {'targets': []})
        entries = [row for row in config.get('targets', [])
                   if (row.get('account'), row.get('target')) == (args.account, args.target)]
        if len(entries) != 1:
            raise ValueError('没有唯一匹配的目标配置。')
        mark_verified(entries[0], args.filename, args.url, args.correct_from_filename)
        return 0
    except Exception as error:
        print('STOP：', error)
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
