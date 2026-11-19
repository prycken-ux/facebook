"""One additional attempt for twelve exact Nov18 pre-Post failures only."""
import contextlib
import copy
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

if __name__ == '__main__':
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import publish_eligible62_materials_20261118 as app

first = app.first
VERSION = '1.0-nov18-twelve-extra-once-skip40-43'
SOURCE_PREFIX = '244766c38beaa3ad'
SKIP_RETRY = {'fb40', 'fb43'}
SPEC = {
    ('fb03', 'personal'): '20261118-ec7402de-eligible62-2026-04-17_7629543428300311838.mp4',
    ('fb11', 'personal'): '20261118-ec7402de-eligible62-2026-05-06_7636711594071739662.mp4',
    ('fb31', 'personal'): '20261118-ec7402de-eligible62-2026-05-08_7637428596042190093.mp4',
    ('fb32', 'personal'): '20261118-ec7402de-eligible62-2026-05-08_7637429270331084045.mp4',
    ('fb37', 'personal'): '20261118-ec7402de-eligible62-2026-05-08_7637473836170038542.mp4',
    ('fb46', 'personal'): '20261118-ec7402de-eligible62-2026-05-09_7637842951002983694.mp4',
    ('fb49', 'personal'): '20261118-ec7402de-eligible62-2026-05-09_7637865622734507277.mp4',
    ('fb54', 'personal'): '20261118-ec7402de-eligible62-2026-05-10_7638161620727876878.mp4',
    ('fb60', 'personal'): '20261118-ec7402de-eligible62-2026-05-11_7638563188182617358.mp4',
    ('fb63', 'personal'): '20261118-ec7402de-eligible62-2026-05-11_7638564610588675341.mp4',
    ('fb66', 'personal'): '20261118-ec7402de-eligible62-2026-05-11_7638577854187392269.mp4',
    ('fb70', 'personal'): '20261118-ec7402de-eligible62-2026-05-11_7638588955310443789.mp4',
}
BOOTSTRAP = re.compile(app.workers.BOOTSTRAP.pattern.replace(
    'start_distribute_first24_materials_20261116', 'start_retry_nov18_twelve_on_nov19').replace(
    'verified-first24-material-distribution', 'verified-nov18-twelve-prepost-retry'))


def paused_now(root):
    excluded = set(app.PAUSED) | SKIP_RETRY
    value = first.upload.read_json(root / app.AVAILABILITY, None)
    if value is not None:
        p = value.get('payload', {})
        if (value.get('sha256') != first.batch.digest(p)
                or p.get('schema') != 'publication-account-exclusions-v1'
                or not isinstance(p.get('excluded_accounts'), list)):
            raise ValueError('当前暂停名单记录异常，未补发。')
        excluded.update(p['excluded_accounts'])
    return excluded


def descendants(parent_path, parent):
    """Bind failures written by the existing automatic retry to its exact parent."""
    bindings = [dict(manifest=parent_path.name, sha256=parent['sha256'])]
    for path in sorted((first.upload.ROOT / 'logs').glob('automatic-retry-*.json')):
        raw = first.upload.read_json(path, {})
        p = raw.get('payload', {})
        if p.get('source_manifest') != parent_path.name:
            continue
        if p.get('source_sha256') != parent['sha256']:
            raise ValueError('自动补发来源指纹变化，未重建原任务。')
        app.queued.validate_run_manifest(path, raw)
        bindings.append(dict(manifest=path.name, sha256=raw['sha256']))
    return bindings


def retry_validator(parent_path, parent, jobs, bindings, grant, day):
    """Validate only this exact subset grant without weakening base queue checks."""
    def validate(path, value, date):
        p = value.get('payload', {})
        if path.name == parent_path.name:
            return app.queued.validate_queue(path, value, parent['payload']['date'])
        if (value.get('sha256') != first.batch.digest(p)
                or path.name != 'frozen-material-' + day + '-' + value['sha256'][:16] + '.json'
                or p.get('explicit_prepost_grant') != grant):
            raise ValueError('本次12条补发清单或许可不符。')
        expected = copy.deepcopy(parent['payload'])
        expected.update(date=day, start=p.get('start'), requested_start=p.get('requested_start'),
                        jobs=jobs, explicit_prepost_grant=grant,
                        publication_preferences_sha256=first.batch.preferences.load(day)['sha256'],
                        excluded_accounts=sorted(first.batch.excluded_accounts(day)),
                        source_bindings=bindings, authorized_state_sha256=p.get('authorized_state_sha256'))
        for field in ('distributed_scope', 'intended_accounts', 'old_material_files'):
            expected.pop(field, None)
        stamps = [datetime.fromisoformat(p.get(k, '')) for k in ('start', 'requested_start')]
        if any(s.tzinfo is None or s.astimezone(first.batch.BJ).date().isoformat() != day for s in stamps):
            raise ValueError('补发执行时间不符，未伪造旧日期。')
        states = p.get('authorized_state_sha256', {})
        if (p != expected or set(states) != {j['key'] for j in jobs}
                or any(not re.fullmatch('[a-f0-9]{64}', str(v)) for v in states.values())):
            raise ValueError('补发原视频、正文评论或状态授权变化。')
        metadata = dict(workflow='future-video-comments-v1', auto_retry_policy=first.priority.retry.POLICY,
                        comment_timing=first.priority.TIMING,
                        priority_workflow=first.priority.PRIORITY_WORKFLOW_VERSION, report_format='text')
        if any(value.get(k) != v for k, v in metadata.items()):
            raise ValueError('补发执行策略不符。')
    return validate


def run_wave(root, req, source, journal, material, wave, controller):
    with app.wave_context(req, source, journal, material, wave, controller):
        parent_path = root / 'logs' / wave['manifest']
        parent = first.archive.checked_json(parent_path)
        if parent['sha256'] != wave['sha256']:
            raise ValueError('原发布清单指纹变化。')
        first.validate(parent_path, parent, material)
        jobs = [copy.deepcopy(j) for j in parent['payload']['jobs']
                if (j['account'], j['target']) in SPEC]
        if not jobs:
            return 0
        if any(j['filename'] != SPEC[j['account'], j['target']] for j in jobs):
            raise ValueError('原视频文件名与昨天的失败记录不一致，未另选视频。')
        bindings = descendants(parent_path, parent)
        grant = 'nov18-twelve-prepost-extra-on-nov19-v1-' + req['sha256'][:12] + '-' + parent['sha256'][:12]
        saved = first.upload.read_json(root / 'logs' / (grant + '.json'), {})
        day = '2026-11-19'
        if saved:
            child = first.archive.checked_json(root / 'logs' / saved.get('manifest', ''))
            day = child['payload']['date']
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) or not '2026-11-19' <= day <= app.today():
            raise ValueError('补发日期尚未到或固定执行日期异常。')
        validate = retry_validator(parent_path, parent, jobs, bindings, grant, day)
        checked = app.extra.checked

        def checked_scoped(job, state, claims, value):
            if ((job['account'], job['target']) not in SPEC
                    or job['account'] in paused_now(root)):
                return None, '用户排除或暂停此账号，直接跳过，不验证或补发'
            return checked(job, state, claims, value)

        def require_authorization():
            current = first.archive.checked_json(root / app.REQUEST)
            if current != req:
                raise ValueError('原62条发布授权发生变化，未继续补发。')

        with patch.object(first.priority, 'validate', side_effect=validate), \
             patch.object(app.extra, 'DAY', day), patch.object(app.extra, 'GRANT', grant), \
             patch.object(app.extra, 'source', return_value=(jobs, bindings, parent['payload'])), \
             patch.object(app.extra, 'require_day', side_effect=require_authorization), \
             patch.object(app.extra, 'checked', side_effect=checked_scoped):
            return app.extra.execute()


def execute(root):
    root = Path(root).resolve()
    app.stage.setup(root)
    if not (root / app.REQUEST).is_file():
        raise ValueError('缺少昨天新62条视频的原发布授权，未新建发布任务。')
    with patch.object(app.workers, 'BOOTSTRAP', BOOTSTRAP):
        live = app.workers.active_workers(root, Path(__file__).resolve())
    if live:
        raise ValueError('仍有发布或登录检查任务，先等原任务退出：' + ','.join(str(r['pid']) for r in live))
    app.browser.staged.lock_recovery.recover_locks(root)
    with app.response_guard.installed(), app.background_policy.installed(), \
         patch.object(first.batch, 'excluded_accounts', side_effect=app.exclusions), \
         patch.object(app.owned, 'reservation', side_effect=app.active_reservation):
        _, source, journal, material = app.allocation(root)
        req = app.request(root, source, journal, material)
        if (req['sha256'][:16] != SOURCE_PREFIX or req['payload']['material_date'] != '2026-11-18'):
            raise ValueError('不是日志指定的11月18日62条原视频批次。')
        control_path = root / 'logs' / ('eligible62-real-publication-' + req['sha256'][:16] + '.json')
        controller = first.upload.read_json(control_path, {})
        if controller.get('request_sha256') != req['sha256'] or not controller.get('waves'):
            raise ValueError('缺少原发布进度，不重建冻结任务。')
        all_jobs = {}
        for wave in controller['waves']:
            parent = first.archive.checked_json(root / 'logs' / wave['manifest'])
            for job in parent['payload']['jobs']:
                pair = job['account'], job['target']
                if pair in all_jobs:
                    raise ValueError('原冻结任务有重复目标，未继续补发。')
                all_jobs[pair] = job
        if not set(SPEC) <= set(all_jobs):
            raise ValueError('原批次缺少指定失败视频。')
        print('本次仅再尝试12条原视频，各一次；排除原32个停用账号及fb40、fb43。', flush=True)
        print('后台运行；登录验证先跳过；已成功及47条旧待核实视频不重新上传。', flush=True)
        result = 0
        for wave in controller['waves']:
            result = max(result, run_wave(root, req, source, journal, material, wave, controller))
        app.report(req, material, controller, control_path)
        print('本次补发结束。登录验证事项仅记录，本入口不弹人工检查窗口。', flush=True)
        return result


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    try:
        if sys.platform != 'win32':
            raise ValueError('请在原Windows上传电脑的PowerShell窗口运行。')
        raise SystemExit(execute(Path(sys.argv[1])))
    except KeyboardInterrupt:
        print('已暂停，补发许可与进度保留；重跑同一指令继续，不增加次数。', flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', str(error) or type(error).__name__, flush=True)
        raise SystemExit(1)
