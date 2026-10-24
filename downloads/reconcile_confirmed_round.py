"""Locally reconcile the explicitly user-confirmed original thirteen + fb10 Page."""
import argparse
import copy
import csv
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import fb_upload as upload
from add_fb_accounts import locked

ORIGINAL = tuple((f'fb{i:02d}', 'personal' if i in {3, 4, 7, 8, 9, 10, 11} else 'page01')
                 for i in range(1, 14))
EXTRA = ('fb10', 'page01')


def basename(value):
    return str(value).replace('\\', '/').rsplit('/', 1)[-1]


def instant(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('报告或记录缺少时区，未猜选历史任务。')
    return result


def fingerprint(entry, path):
    before = path.stat()
    if not before.st_size:
        raise ValueError('视频为空：' + str(path))
    key = upload.job_key(entry, path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('视频正在变化：' + str(path))
    return key


def source_for(entry, filename, key, published):
    inbox = upload.inbox_for(entry)
    current = inbox / filename
    if current.exists():
        if not current.is_file() or fingerprint(entry, current) != key:
            raise ValueError('inbox 同名视频已变化，未归档其他素材：' + str(current))
        candidates = [current]
    elif published:
        completed = inbox.parent / 'completed'
        candidates = [completed / filename, *completed.glob('*/' + filename)]
    else:
        raise ValueError('待核对记录的原视频不在 inbox：' + str(current))
    for path in candidates:
        if path.is_file() and fingerprint(entry, path) == key:
            caption = path.with_suffix('.txt')
            if not caption.is_file() or not caption.read_text(encoding='utf-8-sig').strip():
                raise ValueError('视频缺少非空同名 TXT：' + str(path))
            path.resolve().relative_to(inbox.parent.resolve())
            return path
    raise ValueError('找不到与任务指纹一致的已归档视频：' + filename)


def make_plan(config, state, report, allow_confirmed_before_post=False):
    audited_at = instant(report['created'])
    rows = report.get('final_rows')
    if not isinstance(rows, list) or len(rows) not in {13, 14}:
        raise ValueError('最新核对报告不含完整的本轮 13/14 个结果，未用旧报告代替。')
    expected_pairs = set(ORIGINAL) if len(rows) == 13 else set((*ORIGINAL, EXTRA))
    if {(r.get('account'), r.get('target')) for r in rows} != expected_pairs:
        raise ValueError('核对报告目标范围不匹配。')
    if len(rows) == 14 and any(not row.get('key') for row in rows):
        raise ValueError('本轮 14 目标报告有空目录或缺失素材，不能用旧成功记录代替本轮。')
    entries = {}
    for pair in (*ORIGINAL, EXTRA):
        found = [e for e in config['targets'] if (e.get('account'), e.get('target')) == pair]
        if len(found) != 1:
            raise ValueError('缺少或重复目标：' + '/'.join(pair))
        upload.validate_entry(found[0])
        entries[pair] = found[0]
    if upload.target_key(entries[EXTRA]['url']) != 'id:61595024556188':
        raise ValueError('fb10/page01 不是本次新增公共主页。')
    choices = []
    for audited in rows:
        pair = (audited['account'], audited['target'])
        key = audited.get('key')
        if not key:
            if audited.get('status') != 'inbox_empty':
                raise ValueError('报告中存在未明确的本轮素材。')
            successes = [(k, r) for k, r in state.items()
                         if (r.get('account'), r.get('target')) == pair and r.get('status') == 'published'
                         and instant(r['created']) <= audited_at]
            if not successes:
                raise ValueError('目录为空且没有对应成功记录：' + '/'.join(pair))
            key, _ = max(successes, key=lambda item: instant(item[1]['created']))
        choices.append((pair, key, audited.get('filename') or None))
    if len(rows) == 13:
        extra_entry = entries[EXTRA]
        video = upload.inbox_for(extra_entry) / 'k1.mp4'
        if video.is_file():
            extra_key = fingerprint(extra_entry, video)
        else:
            extra_matches = [k for k, r in state.items()
                             if (r.get('account'), r.get('target')) == EXTRA
                             and basename(r.get('video', '')) == 'k1.mp4' and r.get('status') == 'published']
            if len(extra_matches) != 1:
                raise ValueError('新增公共主页 k1.mp4 没有唯一的成功记录或待归档原文件。')
            extra_key = extra_matches[0]
        choices.append((EXTRA, extra_key, 'k1.mp4'))
    plan = []
    for pair, key, expected_name in choices:
        row, entry = state.get(key), entries[pair]
        if not re.fullmatch(r'[a-f0-9]{64}', key) or not isinstance(row, dict):
            raise ValueError('缺少核对报告对应的确切任务。')
        if ((row.get('account'), row.get('target')) != pair
                or upload.target_key(row.get('url', '')) != upload.target_key(entry['url'])):
            raise ValueError('任务账号或主页链接不一致。')
        allowed = {'needs_review', 'published'}
        if allow_confirmed_before_post:
            allowed.add('failed_before_post')
        if row.get('status') not in allowed:
            raise ValueError('任务尚未处于已确认的待核对/成功状态：' + '/'.join(pair))
        filename = basename(row.get('video', ''))
        upload.validate_video_filename(filename)
        if expected_name and filename != expected_name:
            raise ValueError('报告和发布任务的视频文件名不一致。')
        source = source_for(entry, filename, key, row['status'] == 'published')
        if not expected_name and source.parent == upload.inbox_for(entry):
            raise ValueError('报告为空目录，但成功视频现在仍在 inbox，需重新核对范围。')
        plan.append(dict(account=pair[0], target=pair[1], name=entry['name'], key=key,
                         filename=filename, previous_status=row['status'], source=str(source),
                         entry=entry))
    if len({r['key'] for r in plan}) != 14:
        raise ValueError('14 个目标的任务指纹发生重复。')
    return sorted(plan, key=lambda r: (r['account'], r['target']))


def reconcile(verified=False, round_start=None, allow_confirmed_before_post=False):
    if not verified:
        raise ValueError('需要 --verified-all-fourteen-published：用户已确认本轮 14 个目标实际发布成功。')
    with locked():
        root = upload.ROOT
        reports = list((root / 'logs').glob('current-audit-*.json'))
        if not reports:
            raise ValueError('没有找到本轮 current-audit 核对报告。')
        if round_start is None:
            audit_path = max(reports, key=lambda p: p.stat().st_mtime_ns)
            audit = upload.read_json(audit_path, {})
        else:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', round_start):
                raise ValueError('指定批次时间格式无效。')
            actual_reports = []
            for candidate in sorted(reports, reverse=True):
                payload = upload.read_json(candidate, {})
                if payload.get('schema') == 'fourteen-current-publication-v1' and payload.get('phase') != 'plan_only':
                    actual_reports.append((candidate, payload))
            if not actual_reports or actual_reports[0][1].get('created', '')[:19] != round_start:
                raise ValueError('最近实际发布批次与本次确认的批次不同，未用旧确认归档另一轮视频。')
            audit_path, audit = actual_reports[0]
        state_path = root / 'logs/publish_state.json'
        original = upload.read_json(state_path, {})
        config = upload.read_json(upload.CONFIG, {})
        plan = make_plan(config, original, audit, allow_confirmed_before_post=allow_confirmed_before_post)
        now = datetime.now().astimezone().isoformat()
        backup = root / 'backups' / ('confirmed-fourteen-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True)
        for path in (state_path, upload.CONFIG, audit_path, root / 'common_caption_today.txt'):
            if path.is_file():
                shutil.copy2(path, backup / path.name)
        selected = {r['key'] for r in plan}
        report = dict(confirmed_at=now, confirmation_method='user_confirmed_all_fourteen_existing_posts_no_links',
                      source_audit=str(audit_path), backup=str(backup), status='in_progress',
                      rows=[{k: v for k, v in r.items() if k != 'entry'} for r in plan],
                      preserved_older_reviews=[k for k, r in original.items()
                          if r.get('status') == 'needs_review' and k not in selected])
        output = root / 'logs' / ('confirmed-fourteen-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        upload.save_json(output, report)
        state = copy.deepcopy(original)
        for item in plan:
            if item['previous_status'] != 'published':
                row = state[item['key']]
                row.update(status='published', confirmation_method='user_confirmed_existing_post_no_link',
                           confirmed_at=now, status_before_user_confirmation=item['previous_status'])
                if item['previous_status'] == 'failed_before_post':
                    row['user_verified_post_despite_before_post_error'] = True
        if state != original:
            upload.save_json(state_path, state)
        errors = []
        for item, result in zip(plan, report['rows']):
            try:
                source = Path(item['source'])
                if fingerprint(item['entry'], source) != item['key']:
                    raise ValueError('素材在预检后发生变化，未移动。')
                if source.parent == upload.inbox_for(item['entry']):
                    folder = upload.archive(source, source.with_suffix('.txt'))
                    source = folder / item['filename']
                if fingerprint(item['entry'], source) != item['key'] or not source.with_suffix('.txt').is_file():
                    raise ValueError('归档结果未通过核验。')
                result.update(status='published', archived_video=str(source), archived_caption=str(source.with_suffix('.txt')))
                print(item['account'] + '/' + item['target'], '已发布并归档', item['filename'], flush=True)
            except Exception as error:
                result.update(status='published_archive_incomplete', error=str(error))
                errors.append(str(error))
                print('归档需处理：', item['account'], error, flush=True)
            upload.save_json(output, report)
        report['status'] = 'archive_incomplete' if errors else 'completed'
        upload.save_json(output, report)
        csv_path = output.with_suffix('.csv')
        with csv_path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['account', 'target', 'name', 'filename', 'status', 'key', 'archived_video'])
            writer.writeheader()
            for row in report['rows']:
                writer.writerow({k: row.get(k, '') for k in writer.fieldnames})
        # Synchronize the original fourteen-file manifest too, retaining its
        # original immutable rows and all attempt/error histories.
        if audit.get('schema') == 'fourteen-current-publication-v1':
            synced = []
            for item in audit['final_rows']:
                item = dict(item)
                if item.get('key') in selected:
                    item.update(status='published', reason='该本轮视频已确认发布成功')
                synced.append(item)
            audit.update(final_rows=synced, user_confirmed_all_fourteen_at=now, confirmation_report=str(output))
            upload.save_json(audit_path, audit)
            source_fields = ['account', 'target', 'filename', 'status', 'reason', 'key', 'created']
            with audit_path.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=source_fields)
                writer.writeheader()
                for item in synced:
                    writer.writerow({field: item.get(field, '') for field in source_fields})
        print('本轮：14 个发布目标已记录成功；归档完成：', 14 - len(errors), '/14')
        print('历史待核对记录保留：', len(report['preserved_older_reviews']), '条；不属于此次确认范围。')
        print('原记录备份：', backup)
        print('本轮汇总：', csv_path)
        print('详细核验：', output)
        print('本工具只处理本地记录和文件，没有上传或发布。')
        return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description='仅归档用户已明确确认成功的本轮 14 个发布目标')
    parser.add_argument('--verified-all-fourteen-published', action='store_true')
    parser.add_argument('--round-start', required=True, help='本次已经核对的原发布报告开始时间，精确到秒')
    parser.add_argument('--allow-confirmed-before-post', action='store_true',
                        help='用户已在 Facebook 看到确切视频，允许补记此前显示发布前失败的记录')
    args = parser.parse_args()
    return reconcile(args.verified_all_fourteen_published, args.round_start, args.allow_confirmed_before_post)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
