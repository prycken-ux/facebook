"""Requeue one retracted, URL-free user confirmation after verified absence.

Never opens a browser. Keeps the complete original ledger and media in backup.
"""
import argparse
import copy
import hashlib
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import fb_upload as upload
from mark_verified_post import validate_filename


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def reopen_confirmation(entry, filename, verified_absent=False):
    """Caller holds upload.lock; verified_absent is an explicit user assertion."""
    if not verified_absent:
        raise ValueError('需要 --verified-absent，确认该目标上没有这条视频后才能恢复待发。')
    upload.validate_entry(entry)
    validate_filename(filename)
    state_path = upload.ROOT / 'logs' / 'publish_state.json'
    original = upload.read_json(state_path, {})
    matches = [(key, row) for key, row in original.items()
               if (row.get('account'), row.get('target')) == (entry['account'], entry['target'])
               and Path(row.get('video', '')).name == filename]
    if len(matches) != 1:
        raise ValueError('没有唯一匹配的账号、目标和文件记录；未撤销。')
    key, row = matches[0]
    if (row.get('status') != 'published'
            or row.get('confirmation_method') != 'user_confirmed_existing_post_no_link'
            or row.get('permalink') or row.get('success_message')):
        raise ValueError('仅能撤销无链接、无成功回执的用户补记；此记录不符合，未修改。')

    inbox = upload.inbox_for(entry)
    completed = inbox.parent / 'completed'
    names = (filename, Path(filename).with_suffix('.txt').name)
    sources = []
    fingerprints = {}
    for name in names:
        candidates = [folder / name for folder in (inbox, completed) if (folder / name).exists()]
        if not candidates or any(not path.is_file() or path.stat().st_size == 0 for path in candidates):
            raise ValueError('找不到完整非空的视频及同名文案：' + name)
        values = {file_digest(path) for path in candidates}
        if len(values) != 1:
            raise ValueError('inbox 与 completed 的同名文件内容冲突，未覆盖：' + name)
        sources.append(candidates[0])
        fingerprints[name] = values.pop()
    if upload.job_key(entry, sources[0]) != key:
        raise ValueError('源视频内容与原任务指纹不一致，未撤销。')
    if not sources[1].read_text(encoding='utf-8-sig').strip():
        raise ValueError('文案为空，未恢复待发。')

    backup = upload.ROOT / 'backups' / ('retracted-confirmation-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(state_path, backup / state_path.name)
    audit = dict(action='reopen_user_confirmation_after_verified_absence', job=key,
                 account=entry['account'], target=entry['target'], filename=filename,
                 assertion='user_verified_absent', original_record=copy.deepcopy(row),
                 retracted_at=datetime.now().astimezone().isoformat())
    upload.save_json(backup / 'retraction.json', audit)
    media_backup = backup / 'media'
    media_backup.mkdir()
    for source in sources:
        shutil.copy2(source, media_backup / source.name)
        if file_digest(media_backup / source.name) != fingerprints[source.name]:
            raise RuntimeError('备份期间源文件变化，原发布记录仍保留。')

    inbox.mkdir(parents=True, exist_ok=True)
    for source in sources:
        destination = inbox / source.name
        if not destination.exists():
            # Exclusive creation never replaces an existing inbox file.
            with source.open('rb') as reader, destination.open('xb') as writer:
                shutil.copyfileobj(reader, writer)
            shutil.copystat(source, destination)
        if file_digest(destination) != fingerprints[source.name]:
            raise RuntimeError('恢复期间文件发生变化，原发布记录仍保留。')
    if upload.job_key(entry, inbox / filename) != key:
        raise RuntimeError('恢复后视频指纹不一致，原发布记录仍保留。')

    # Retain the original completed files in backup; free their names so a
    # successful new upload can archive normally without overwriting anything.
    for name in names:
        archived = completed / name
        if archived.exists():
            if file_digest(archived) != fingerprints[name]:
                raise RuntimeError('归档文件发生变化，原发布记录仍保留。')
            archived.rename(backup / ('completed-' + name))
    if upload.read_json(state_path, {}) != original:
        raise RuntimeError('发布记录在操作期间发生变化，未覆盖；请检查备份和待发文件。')
    state = copy.deepcopy(original)
    del state[key]
    upload.save_json(state_path, state)
    print('已撤销这一条用户补记并恢复待发：', entry['account'], entry['target'], filename)
    print('原记录和视频备份：', backup)
    print('本工具没有上传或发布；其他任务记录保持原样。')
    return key


def main():
    parser = argparse.ArgumentParser(description='用户确认视频不存在后，撤销一条无链接的手工成功补记')
    parser.add_argument('--account', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--filename', required=True)
    parser.add_argument('--verified-absent', action='store_true')
    args = parser.parse_args()
    lock = upload.ROOT / 'logs' / 'upload.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print('STOP：上传程序正在运行或有遗留锁，未撤销记录。')
        return 2
    try:
        with os.fdopen(fd, 'w') as writer:
            writer.write(str(os.getpid()))
        config = upload.read_json(upload.CONFIG, {'targets': []})
        entries = [entry for entry in config.get('targets', [])
                   if (entry.get('account'), entry.get('target')) == (args.account, args.target)]
        if len(entries) != 1:
            raise ValueError('没有唯一匹配的目标配置。')
        reopen_confirmation(entries[0], args.filename, args.verified_absent)
        return 0
    except Exception as error:
        print('STOP：', error)
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
