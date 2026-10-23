"""Resume exact unattempted/before-Post-failed material from the latest real fourteen run."""
import argparse
import sys
from datetime import datetime

import fb_upload as upload
import publish_fourteen_current as driver
from publish_current_inbox import publish_current
from add_fb_accounts import locked


def load_round():
    paths = sorted((upload.ROOT / 'logs').glob('current-audit-*.json'), reverse=True)
    for path in paths:
        report = upload.read_json(path, {})
        if report.get('schema') == 'fourteen-current-publication-v1' and report.get('phase') != 'plan_only':
            pairs = [(r.get('account'), r.get('target')) for r in report.get('rows', [])]
            if len(pairs) != 14 or set(pairs) != set(driver.TARGETS):
                raise ValueError('最近一轮实际发布报告的 14 个目标不完整，未选择更旧报告。')
            if report.get('ai_label') not in {'off', 'on'}:
                raise ValueError('本轮没有明确的 AI 标签设置，未猜测。')
            return path, report
    raise ValueError('没有找到本轮 14 个目标的实际发布报告。')


def candidates(report, state):
    jobs = []
    for row in report['rows']:
        key = row.get('key')
        if not key:
            continue
        record = state.get(key)
        if record:
            if ((record.get('account'), record.get('target')) != (row['account'], row['target'])):
                raise ValueError('任务指纹对应的账号/目标不一致。')
            if record.get('status') != 'failed_before_post':
                continue
            if any(record.get(field) for field in ('permalink', 'success_message', 'confirmation_method')):
                raise ValueError('发布前失败记录同时含成功证据，未重试。')
        elif row.get('status') != 'unrecorded' or not row.get('eligible'):
            continue
        jobs.append(dict(row))
    return jobs


def save_results(path, report):
    state = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
    results = report.get('results', []) + report.get('resume_results', [])
    report['final_rows'] = driver.final_rows(report['rows'], state, results)
    upload.save_json(path, report)
    driver.save_csv(path.with_suffix('.csv'), report['final_rows'])
    return state


def resume(publish=False):
    with locked():
        path, report = load_round()
        config = upload.read_json(upload.CONFIG, {})
        driver.validate_scope(config)
        state = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
        jobs = candidates(report, state)
        if publish:
            backup = upload.ROOT / 'backups' / ('resume-fourteen-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            upload.save_json(backup / path.name, report)
            upload.save_json(backup / 'publish_state.json', state)
    print('续发来源：', path, flush=True)
    print('沿用本轮 AI 标签：', report['ai_label'], '；当前可处理：', len(jobs), '个。', flush=True)
    for row in jobs:
        record = state.get(row['key'], {})
        reason = record.get('error', '').split('\n', 1)[0][:220]
        print(row['account'] + '/' + row['target'], row['filename'], '任务 ' + row['key'][:12], reason, flush=True)
    if not publish:
        print('只检查计划，没有修改记录或发布。')
        return 0
    print('原有 published / needs_review / posting / preparing 全部保留，不会在本次重发。', flush=True)
    report.setdefault('resume_results', [])
    try:
        for row in jobs:
            # Re-read under the cooperative lock before each attempt: another completed
            # publication can make an initially failed job ineligible while we continue.
            with locked():
                current = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
                still = candidates({'rows': [row]}, current)
            if not still:
                print('状态已变化，本次跳过：', row['account'], row['target'], flush=True)
                continue
            result = dict(account=row['account'], target=row['target'], key=row['key'],
                          filename=row['filename'], attempted_at=datetime.now().astimezone().isoformat())
            try:
                print('正在续发：', row['account'], row['target'], row['filename'], flush=True)
                publish_current(row['account'], row['target'], report['ai_label'],
                                retry_before_post=True, expected_key=row['key'])
                result['attempt'] = 'finished'
            except upload.ReceiptNeedsReview as error:
                result.update(attempt='needs_review', error=str(error))
                print('本次结果待核对，保留记录，继续下一个：', error, flush=True)
            except Exception as error:
                result.update(attempt='stopped', error=str(error))
                print('该目标仍需检查，保留记录，继续下一个：', error, flush=True)
            report['resume_results'].append(result)
            save_results(path, report)
        report['last_resume_finished_at'] = datetime.now().astimezone().isoformat()
    finally:
        actual = save_results(path, report)
        print('\n本轮完整 14 目标当前结果：', flush=True)
        for row in report['final_rows']:
            print(row['account'] + '/' + row['target'], row['status'], row['filename'], row['reason'], flush=True)
        print('已更新本轮汇总：', path.with_suffix('.csv'), flush=True)
        print('待核对/发布中不能当作未发布，本工具没有重置这些任务。', flush=True)
    return 0 if all(actual.get(row.get('key'), {}).get('status') == 'published' for row in report['rows']) else 3


def main():
    parser = argparse.ArgumentParser(description='只续发本轮未尝试和明确在点击 Post 前失败的视频；不重发未知结果')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    return resume(args.run)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('续发已中断，保留现有记录；勿直接重试结果未知的视频。')
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
