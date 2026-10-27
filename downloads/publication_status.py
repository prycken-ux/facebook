"""Combine exact-material round manifests with the current local ledger.

This tool never publishes, clears a ledger record, or infers success from an
empty inbox. Opening a profile is solely for the user's online verification.
"""
import argparse
import csv
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime

import fb_upload as upload
from add_fb_accounts import find_chrome, locked

SCHEMAS = {'fourteen-current-publication-v1', 'available-current-publication-v1'}
LABELS = {
    'published': '已记录成功', 'needs_review': '结果待核实，勿重发',
    'posting': '提交中断，待核实，勿重发', 'preparing': '任务中断，待核实，勿重发',
    'failed_before_post': '发布前失败', 'needs_check': '准备未完成或记录异常',
}
REVIEW = {'needs_review', 'posting', 'preparing'}


def date_value(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('日期格式应为 YYYY-MM-DD')
    datetime.strptime(value, '%Y-%m-%d')
    return value


def basename(value):
    return str(value).replace('\\', '/').rsplit('/', 1)[-1]


def manual_action(status, error):
    if status == 'published':
        return '保留成功记录，不重发'
    if status in REVIEW:
        return '在对应主页的 Reels/视频中核对这条实际内容；确认存在后提供编号及视频链接，缺失则明确回复编号＋未发布'
    if '资料仍被占用' in error or 'profile busy' in error:
        return '正常退出该账号全部 Chrome 窗口，再检查当前占用；不使用截图中的旧 PID 强制结束进程'
    if 'ERR_PROXY' in error or 'ERR_TUNNEL' in error:
        return '手动确认此账号原网络/代理可联网'
    if 'ERR_TIMED_OUT' in error or 'Page.goto' in error:
        return '先手动检查网络和目标主页；新版只在选视频前重试主页打开一次'
    if '身份' in error or '头像' in error:
        return '从头像菜单切到此目标的确切身份，再执行原身份核验；显示相同名称不足以证明身份'
    return '检查目标主页及失败截图/日志；保留任务，按确切视频处理'


def collect(date):
    date_value(date)
    config = upload.read_json(upload.CONFIG, {})
    if not isinstance(config, dict) or not isinstance(config.get('targets'), list):
        raise ValueError('缺少有效上传配置')
    if any(not isinstance(entry,dict) for entry in config['targets']):
        raise ValueError('上传配置包含无效条目')
    state = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
    if not isinstance(state, dict):
        raise ValueError('发布记录格式异常')
    configured = {}
    for entry in config['targets']:
        pair = (entry.get('account'), entry.get('target'))
        configured.setdefault(pair, []).append(entry)
    jobs, no_material, issues, sources = {}, {}, [], []
    paths = list((upload.ROOT / 'logs').glob('current-audit-*.json'))
    paths += list((upload.ROOT / 'logs').glob('available-today-*.json'))
    reports = []
    for path in paths:
        try:
            report = upload.read_json(path, {})
            if not isinstance(report,dict):
                raise ValueError('报告格式异常')
            if (report.get('schema') in SCHEMAS and report.get('phase') != 'plan_only'
                    and report.get('created', '')[:10] == date):
                for field in ('rows','results','resume_results','final_rows'):
                    values=report.get(field,[])
                    if not isinstance(values,list) or any(not isinstance(value,dict) for value in values):
                        raise ValueError('报告条目格式异常：'+field)
                reports.append((report.get('created', ''), path, report))
        except (ValueError, OSError) as error:
            issues.append(dict(source=path.name, error='报告无法读取：' + str(error).splitlines()[0][:200]))
    for created, path, report in sorted(reports, key=lambda item: (item[0], item[1].name)):
        sources.append(path.name)
        results = report.get('results', []) + report.get('resume_results', [])
        for source in report.get('rows', []):
            account, target = source.get('account'), source.get('target')
            pair = (account, target)
            key = source.get('key')
            if not key:
                no_material[pair] = dict(account=account, target=target, status=source.get('status'),
                    reason=source.get('reason', ''), source=path.name)
                continue
            if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key):
                issues.append(dict(source=path.name, error='素材缺少有效完整指纹：' + str(pair)))
                continue
            entry_list = configured.get(pair, [])
            entry = entry_list[0] if len(entry_list) == 1 else {}
            row = dict(account=account, target=target, name=entry.get('name', source.get('name', '')),
                filename=source.get('filename', ''), key=key, url=source.get('url') or entry.get('url', ''),
                source=path.name, round_created=created, status='needs_check', reason='没有本次任务完成记录')
            record = state.get(key)
            attempts = [result for result in results if result.get('key') == key]
            try:
                if len(entry_list) != 1:
                    raise ValueError('当前目标配置缺失或重复，未按名称推测身份')
                upload.validate_entry(entry)
                upload.validate_video_filename(row['filename'])
                if upload.target_key(row['url']) != upload.target_key(entry['url']):
                    raise ValueError('报告目标网址与当前配置不一致')
                if record is not None:
                    if (not isinstance(record, dict) or (record.get('account'), record.get('target')) != pair
                            or upload.target_key(record.get('url', '')) != upload.target_key(row['url'])):
                        raise ValueError('素材记录与目标身份冲突，未采信成功或失败状态')
                    row.update(status=record.get('status', 'needs_check'), reason=record.get('error', ''))
                    if row['status']=='failed_before_post' and attempts and attempts[-1].get('error'):
                        row['reason']=attempts[-1]['error']
                    if row['status']=='failed_before_post' and any(record.get(field) for field in
                            ('permalink','success_message','confirmation_method')):
                        row.update(status='needs_review',reason='失败状态中同时存在成功证据，请本人检查，勿重发')
                    if row['status'] == 'published':
                        row['reason'] = '当前确切素材已有成功记录；以此记录为准'
                        row['permalink'] = record.get('permalink', '')
                else:
                    if attempts:
                        row['reason'] = attempts[-1].get('error') or attempts[-1].get('reason') or row['reason']
                    cached=[item for item in report.get('final_rows',[]) if item.get('key')==key]
                    if cached and cached[-1].get('status') in REVIEW:
                        row.update(status=cached[-1]['status'],reason='本地任务记录缺失，但原报告显示结果未知；勿重发。'+str(row['reason']))
                # A missing ledger row does not turn a cached final-row success
                # or an attempt_finished return into evidence of publication.
            except (KeyError, TypeError, ValueError) as error:
                row.update(status='needs_check', reason=str(error).splitlines()[0][:500])
            if key in jobs and ((jobs[key]['account'], jobs[key]['target']) != pair
                    or jobs[key]['url'] != row['url'] and row['status']=='needs_check'):
                jobs[key].update(status='needs_check', reason='同一素材指纹被不同目标报告引用，未猜选')
                issues.append(dict(source=path.name, error='素材指纹的跨目标报告冲突：' + key))
                continue
            jobs[key] = row
    rows = sorted(jobs.values(), key=lambda row: (row['account'], row['target'], row['round_created'], row['key']))
    for row in rows:
        row['reason'] = str(row['reason']).split('\n', 1)[0][:500]
        row['label'] = LABELS.get(row['status'], '需要检查：' + str(row['status']))
        row['action'] = manual_action(row['status'], row['reason'])
    return dict(schema='publication-status-v1', date=date, created=datetime.now().astimezone().isoformat(),
        sources=sources, rows=rows, counts=dict(Counter(row['status'] for row in rows)),
        no_material_rows=list(no_material.values()), issues=issues,
        note='按目标和完整视频指纹合并指定日期的实际发布批次；没有新素材不等于成功；不重置记录或发布')


def save(report):
    path = upload.ROOT / 'logs' / ('publication-status-' + report['date'] + '.json')
    upload.save_json(path, report)
    fields = ['account', 'target', 'name', 'filename', 'label', 'reason', 'action', 'key', 'source', 'url']
    with path.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(report['rows'])
    lines = ['需本人核实；这里只列出指定批次的确切素材，不会重新发布。']
    for row in report['rows']:
        if row['status'] != 'published':
            lines += ['', f"{row['account']}/{row['target']} {row['name']} | {row['filename']} | {row['key'][:12]}",
                row['label'], row['url'], row['reason'], row['action']]
    path.with_suffix('.txt').write_text('\n'.join(lines), encoding='utf-8-sig')
    return path


def open_reviews(report):
    if sys.platform != 'win32':
        raise RuntimeError('打开账号需在 Windows 上传电脑执行')
    chrome = find_chrome()
    opened = set()
    for row in report['rows']:
        pair = (row['account'], row['target'])
        if row['status'] not in REVIEW or pair in opened:
            continue
        try:
            if not re.fullmatch(r'fb(?:0[1-9]|[1-9][0-9]+)', row['account']):
                raise ValueError('账号编号无效')
            upload.target_key(row['url'])
            profile = upload.ROOT / 'profiles' / row['account']
            if not profile.is_dir():
                raise ValueError('缺少原浏览器资料，未创建空白资料')
            subprocess.Popen([str(chrome), '--user-data-dir=' + str(profile), '--profile-directory=Default',
                '--no-first-run', '--no-default-browser-check', '--new-window', row['url']])
            opened.add(pair)
            print('已请求打开待核实账号：', '/'.join(pair), row['name'], flush=True)
        except (OSError, ValueError) as error:
            print('需要手动打开：', '/'.join(pair), str(error).splitlines()[0], flush=True)
    return opened


def main():
    parser = argparse.ArgumentParser(description='按确切视频汇总两种发布批次，保留未知结果和历史成功')
    parser.add_argument('--date', required=True, type=date_value, help='所需批次日期，例如 2026-10-26')
    parser.add_argument('--open-review', action='store_true', help='用原 Chrome 资料打开结果未知的账号，不发布')
    args = parser.parse_args()
    with locked():
        report = collect(args.date)
        path = save(report)
        print('批次日期：', report['date'], '；合并报告：', len(report['sources']), flush=True)
        for row in report['rows']:
            print(row['account'] + '/' + row['target'], row['name'], row['filename'], row['label'], row['reason'], flush=True)
        print('计数（按视频任务）：', report['counts'], flush=True)
        print('没有新素材的记录另列，不计入成功。', flush=True)
        print('CSV 汇总：', path.with_suffix('.csv'), '；人工核实清单：', path.with_suffix('.txt'), flush=True)
        if args.open_review:
            open_reviews(report)
        for issue in report['issues']:
            print('报告异常需核实：', issue['source'], issue['error'], flush=True)
    return 0 if report['sources'] and not report['issues'] else 3


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', str(error).splitlines()[0], flush=True)
        raise SystemExit(1)
