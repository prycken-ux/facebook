"""Publish one current video per established fourteen destinations, using saved caption."""
import argparse
import csv
import sys
import time
from datetime import datetime

import apply_common_caption as captions
import audit_current_round as audit
import fb_upload as upload
from add_fb_accounts import locked

TARGETS = (*audit.ORIGINAL_TARGETS, ('fb10', 'page01'))


def validate_scope(config):
    selected, urls = [], set()
    for pair in TARGETS:
        matches = [row for row in config.get('targets', [])
                   if (row.get('account'), row.get('target')) == pair]
        if len(matches) != 1:
            raise ValueError('14 目标配置缺失或重复：' + '/'.join(pair))
        entry = matches[0]
        upload.validate_entry(entry)
        key = upload.target_key(entry['url'])
        if key in urls:
            raise ValueError('14 目标中存在重复主页网址。')
        if pair == ('fb10', 'page01') and key != 'id:61595024556188':
            raise ValueError('fb10/page01 不是已接入的公共主页。')
        urls.add(key)
        selected.append(entry)
    return selected


def final_rows(rows, state, results):
    errors = {row['key']: row.get('error', '') for row in results}
    final = []
    for row in rows:
        item = dict(row)
        record = state.get(item['key']) if item['key'] else None
        if record:
            item['status'] = record.get('status', item['status'])
            item['created'] = record.get('created', '')
            item['reason'] = ('本轮确切素材已记录成功' if item['status'] == 'published' else
                              '已点击发布但结果待核对；勿重发' if item['status'] == 'needs_review' else
                              record.get('error', '').split('\n', 1)[0][:180])
        elif errors.get(item['key']):
            item['reason'] = errors[item['key']].split('\n', 1)[0][:180]
        final.append(item)
    return final


def save_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        fields = ['account', 'target', 'filename', 'status', 'reason', 'key', 'created']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, '') for field in fields})


def new_material_rows(scanned):
    """Keep exactly one manifest slot per target; never put old jobs in this round."""
    rows, preserved = [], []
    for account, target in TARGETS:
        group=[row for row in scanned if (row['account'],row['target'])==(account,target)]
        fresh=[row for row in group if row['status']=='unrecorded']
        if len(fresh)==1:
            rows.append(dict(fresh[0]))
            preserved.extend(dict(row) for row in group if row is not fresh[0])
            continue
        base=dict(group[0])
        base.update(filename='',key=None,created='',eligible=False)
        if len(fresh)>1:
            base.update(status='invalid',reason='当前目标有多条未记录素材，未自动猜选')
        elif any(row['status']=='invalid' for row in group):
            base.update(status='invalid',reason=next(row['reason'] for row in group if row['status']=='invalid'))
        elif len(group)==1 and group[0]['status']=='inbox_empty':
            base=dict(group[0])
        else:
            base.update(status='no_new_video',reason='没有未记录的新视频，未用以前的任务代替本轮')
        rows.append(base)
        preserved.extend(dict(row) for row in group if row.get('key'))
    return rows,preserved


def run(publish=False, ai_label=None, new_only=False):
    if publish and ai_label not in {'off', 'on'}:
        raise ValueError('实际发布必须明确指定本轮 --ai-label off 或 on。')
    caption_path = upload.ROOT / 'common_caption_today.txt'
    text = caption_path.read_text(encoding='utf-8-sig').strip()
    if not text:
        raise ValueError('已保存的统一文案为空，未发布。')
    if new_only:
        print('本次只处理当前 inbox 中未记录的新视频；以前的失败、待核对和成功记录全部保留。', flush=True)
    with locked():
        config = upload.read_json(upload.CONFIG, {})
        validate_scope(config)
        if publish:
            accounts = list(dict.fromkeys(account for account, _ in TARGETS))
            captions.apply(accounts, text, target_filter=set(TARGETS))
    if publish:
        print('沿用已保存的统一文案。等待 61 秒，让视频、文案和评论文件稳定。', flush=True)
        for seconds in (30, 31):
            time.sleep(seconds)
            print('文件稳定等待中。' if seconds == 30 else '等待完成，开始核对本轮素材。', flush=True)
    with locked():
        config = upload.read_json(upload.CONFIG, {})
        validate_scope(config)
        state = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
        rows, old = audit.scan(config, state, pairs=TARGETS, retry_before_post=not new_only)
        rows,preserved=(new_material_rows(rows) if new_only else (rows,[]))
    report = dict(schema='fourteen-current-publication-v1', created=datetime.now().astimezone().isoformat(),
                  targets=[dict(account=a, target=t) for a, t in TARGETS], ai_label=ai_label,
                  caption_source=str(caption_path), caption_text=text, new_only=new_only, rows=rows,
                  older_reviews_not_current=old, results=[], final_rows=rows,
                  preserved_inbox_rows=preserved,
                  phase='publishing' if publish else 'plan_only')
    path = upload.ROOT / 'logs' / ('current-audit-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    upload.save_json(path, report)
    audit.show(rows, '本轮 14 个目标：按当前文件内容核对；fb10 个人主页先于公共主页执行')
    print('历史待核对保留：', len(old), '条。新素材最多每目标一条，未知结果不重发。', flush=True)
    if new_only:
        print('另有已记录或无法唯一选择的 inbox 素材保留：',len(preserved),'条。',flush=True)
    if not publish:
        print('本次仅检查，没有发布或修改文案。报告：', path)
        return 0
    try:
        for row in rows:
            if not row['eligible']:
                continue
            report['results'].extend(audit.execute([row], ai_label, retry_before_post=not new_only))
            actual = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
            report['final_rows'] = final_rows(rows, actual, report['results'])
            upload.save_json(path, report)
        report['phase'] = 'attempts_finished'
    finally:
        actual = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
        report['final_rows'] = final_rows(rows, actual, report['results'])
        upload.save_json(path, report)
        csv_path = path.with_suffix('.csv')
        save_csv(csv_path, report['final_rows'])
        audit.show(report['final_rows'], '本轮发布结果（按确切文件指纹，不用旧成功记录代替）')
        for label, statuses in [('本轮已记录成功', {'published'}), ('本轮待核对', {'needs_review', 'posting', 'preparing'}),
                                ('本轮未发成/未尝试', {'unrecorded', 'failed_before_post', 'invalid'})]:
            targets = sorted({r['account'] + '/' + r['target'] for r in report['final_rows']
                              if r['key'] and r['status'] in statuses})
            print(label + '：' + ('、'.join(targets) if targets else '无'), flush=True)
        print('本轮汇总：', csv_path)
        print('详细核对：', path)
        print('未配置自动评论发送；评论文案若已绑定，仅保留为待办。')
    eligible = [row for row in rows if row['eligible']]
    succeeded = sum(actual.get(row['key'], {}).get('status') == 'published' for row in eligible)
    print('本轮实际安排素材：', len(eligible), '；已记录成功：', succeeded, flush=True)
    return 0 if len(eligible) == 14 and succeeded == 14 else 3


def main():
    parser = argparse.ArgumentParser(description='发布原有 13 个目标和 fb10 新公共主页的当前视频；不包含未登记的新主页')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--ai-label', choices=['off', 'on'])
    parser.add_argument('--new-only', action='store_true', help='只处理未记录的新素材，保留以前的发布前失败记录')
    args = parser.parse_args()
    return run(args.run, args.ai_label, args.new_only)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('操作已中断；保留现有发布记录，先核对本轮报告，勿直接重复发。')
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
