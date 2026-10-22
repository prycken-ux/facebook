"""Audit physical inbox content; optionally publish new or pre-Post-failed material."""
import argparse
from datetime import datetime
import sys

import fb_upload as upload
from add_fb_accounts import locked
from publish_current_inbox import publish_current

ORIGINAL_TARGETS = tuple((f'fb{i:02d}', 'personal' if i in {3, 4, 7, 8, 9, 10, 11} else 'page01')
                         for i in range(1, 14))
LABELS = {'unrecorded': '未尝试', 'failed_before_post': '发布前失败', 'needs_review': '结果待核对',
          'published': '已记录成功', 'preparing': '准备中/中断', 'posting': '发布中/中断',
          'inbox_empty': '当前目录为空', 'invalid': '需要检查', 'excluded': '排除素材'}


def scan(config, state, pairs=ORIGINAL_TARGETS):
    rows, old_reviews = [], []
    common_path = upload.ROOT / 'common_caption_today.txt'
    common = common_path.read_text(encoding='utf-8-sig').strip() if common_path.is_file() else ''
    for account, target in pairs:
        base = dict(account=account, target=target, filename='', key=None, status='invalid',
                    eligible=False, reason='', created='')
        matches = [entry for entry in config.get('targets', [])
                   if (entry.get('account'), entry.get('target')) == (account, target)]
        if len(matches) != 1:
            rows.append({**base, 'reason': '账号/目标配置缺失或重复'})
            continue
        entry = matches[0]
        try:
            upload.validate_entry(entry)
            folder = upload.inbox_for(entry)
            videos = sorted((file for file in folder.iterdir() if file.is_file()
                             and file.suffix.lower() == '.mp4'), key=upload.queue_order)
        except Exception as error:
            rows.append({**base, 'reason': str(error)})
            continue
        live_keys = set()
        target_rows = []
        for video in videos:
            row = {**base, 'filename': video.name}
            try:
                video.resolve().relative_to(folder.resolve())
                before = video.stat()
                key = upload.job_key(entry, video)
                after = video.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('视频正在变化，请等待复制完成')
                row['key'] = key
                live_keys.add(key)
                record = state.get(key)
                if record and ((record.get('account'), record.get('target')) != (account, target)
                               or upload.target_key(record.get('url', '')) != upload.target_key(entry['url'])):
                    raise ValueError('素材指纹记录属于其他目标，未安排发布')
                row['status'] = record.get('status', 'invalid') if record else 'unrecorded'
                row['created'] = record.get('created', '') if record else ''
                if video.name.lower() in {value.lower() for value in entry.get('excluded_files', [])}:
                    row.update(status='excluded', reason='该素材在排除列表中')
                elif row['status'] in {'unrecorded', 'failed_before_post'}:
                    if not entry.get('prepared_at') or not entry.get('enabled'):
                        raise ValueError('目标尚未完成 prepare 或启用')
                    if record and any(record.get(field) for field in ('permalink', 'success_message', 'confirmation_method')):
                        raise ValueError('失败记录同时含有成功证据，需核对')
                    validation = dict(state)
                    validation.pop(key, None)
                    selected = upload.named_job(entry, validation, video.name)
                    if not common or selected is None or selected[3] != common:
                        raise ValueError('同名 TXT 与已保存统一文案不一致')
                    row['eligible'] = True
                    row['reason'] = '可处理当前素材；不重试结果未知的内容'
                elif row['status'] == 'needs_review':
                    row['reason'] = '已尝试但结果未知，需先核对 Facebook，未自动重发'
                elif row['status'] == 'published':
                    row['reason'] = '该内容已记录成功，未重发'
                else:
                    row['reason'] = '保留原任务，请先检查该状态'
            except Exception as error:
                row.update(eligible=False, reason=str(error))
            target_rows.append(row)
        eligible = [row for row in target_rows if row['eligible']]
        if len(eligible) > 1:
            for row in eligible:
                row.update(eligible=False, reason='当前目标有多条可处理素材，未自动猜选')
        if not videos:
            published = [row for row in state.values()
                         if (row.get('account'), row.get('target')) == (account, target)
                         and row.get('status') == 'published']
            latest = max(published, key=lambda row: row.get('created', ''), default=None)
            reason = '没有当前素材，无法仅凭旧成功记录判定本轮全部完成'
            if latest:
                name = str(latest.get('video', '')).replace('\\', '/').rsplit('/', 1)[-1]
                reason = '最近成功记录：%s；%s' % (name, latest.get('created', ''))
            target_rows.append({**base, 'status': 'inbox_empty', 'reason': reason})
        for key, record in state.items():
            if ((record.get('account'), record.get('target')) == (account, target)
                    and record.get('status') == 'needs_review' and key not in live_keys):
                old_reviews.append(dict(account=account, target=target, key=key,
                    filename=str(record.get('video', '')).replace('\\', '/').rsplit('/', 1)[-1],
                    created=record.get('created', '')))
        rows.extend(target_rows)
    return rows, old_reviews


def show(rows, heading):
    print('\n' + heading, flush=True)
    for row in rows:
        print('%s/%s | %s | %s | %s' % (row['account'], row['target'],
            LABELS.get(row['status'], row['status']), row['filename'] or '-', row['reason']), flush=True)
    for status, label in [('unrecorded', '当前未尝试'), ('failed_before_post', '当前发布前失败'),
                          ('needs_review', '当前结果待核对'), ('published', '当前所查素材已记录成功')]:
        accounts = sorted({row['account'] for row in rows if row['key'] and row['status'] == status})
        print(label + '：' + ('、'.join(accounts) if accounts else '无'), flush=True)


def execute(rows, ai_label='off'):
    results = []
    for row in rows:
        if not row['eligible']:
            continue
        result = dict(account=row['account'], target=row['target'], filename=row['filename'], key=row['key'])
        try:
            print('\n正在处理当前素材：', row['account'], row['filename'], flush=True)
            publish_current(row['account'], row['target'], ai_label, retry_before_post=True,
                            expected_key=row['key'])
            result['attempt'] = 'finished'
        except upload.ReceiptNeedsReview as error:
            result.update(attempt='needs_review', error=str(error))
            print('本次结果待核对，保留记录，继续下一个：', error, flush=True)
        except Exception as error:
            result.update(attempt='stopped', error=str(error))
            print('该目标停止，保留记录，继续下一个：', error, flush=True)
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description='按当前 inbox 内容检查原 13 目标，可处理未尝试或发布前失败素材')
    parser.add_argument('--run', action='store_true', help='实际处理可安全尝试的素材；不重发 needs_review')
    parser.add_argument('--ai-label', choices=['off', 'on'], default='off')
    args = parser.parse_args()
    state_path = upload.ROOT / 'logs/publish_state.json'
    print('正在按当前 inbox 视频内容核对原 13 个发布目标，请等待素材指纹检查。', flush=True)
    with locked():
        config = upload.read_json(upload.CONFIG, {'targets': []})
        state = upload.read_json(state_path, {})
        rows, old_reviews = scan(config, state)
    report = dict(created=datetime.now().astimezone().isoformat(), rows=rows,
                  older_reviews_not_current=old_reviews, results=[])
    report_path = upload.ROOT / 'logs' / ('current-audit-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    upload.save_json(report_path, report)
    show(rows, '当前素材核对（按内容匹配发布记录）')
    print('另有不对应当前 inbox 素材的旧待核对记录：', len(old_reviews), '条；保留原样。', flush=True)
    if args.run:
        report['results'] = execute(rows, args.ai_label)
        actual = upload.read_json(state_path, {})
        final = []
        errors = {row['key']: row.get('error', '') for row in report['results']}
        for row in rows:
            item = dict(row)
            record = actual.get(item['key']) if item['key'] else None
            if record:
                item['status'] = record.get('status', item['status'])
                item['created'] = record.get('created', '')
                if item['status'] == 'published':
                    item['reason'] = '当前素材已记录成功'
                elif item['status'] == 'needs_review':
                    item['reason'] = '结果未知，请核对 Reels；任务 ' + item['key'][:12]
                else:
                    item['reason'] = record.get('error', '').split('\n', 1)[0][:120]
            elif errors.get(item['key']):
                item['reason'] = errors[item['key']]
            final.append(item)
        report['final_rows'] = final
        upload.save_json(report_path, report)
        show(final, '本轮处理后结果（仍按最初核对的素材内容，不用旧文件代替）')
    print('\n核对报告：', report_path, flush=True)
    print('needs_review/结果待核对不能当作未发布；核对 Facebook 后再决定是否补发。', flush=True)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
