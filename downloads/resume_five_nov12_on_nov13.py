"""Explicit Nov13 continuation of five unchanged, frozen Nov12 personal videos."""
import contextlib
import copy
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

if __name__ == '__main__':
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import scheduled_priority_workflow as workflow
import publish_priority_batch as priority
import normal_chrome_batch as normal
import local_file_input as local
import personal_owner_routes as owners
import page_reel_ai_compat as editor
from add_fb_accounts import locked

DAY = '2026-11-13'
SOURCE_DAY = '2026-11-12'
SOURCE_SCOPE = 'nov12-current-materials-fb01-to-fb24-v1'
SCOPE = 'nov13-explicit-five-nov12-personal-videos-v1'
CONTROLLER = 'nov12-current-materials-original-accounts.json'
POINTER = 'nov12-five-personals-on-nov13.json'
EXPECTED = {
    'fb16': '2026-05-20_7641888881230482702.mp4',
    'fb17': '2026-05-20_7641915762092952845.mp4',
    'fb18': '2026-05-21_7642264438749416717.mp4',
    'fb21': '2026-05-25_7643761018920865037.mp4',
    'fb24': '1111-4.mp4',
}


def require_day():
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat() != DAY:
        raise ValueError('此指令只授权11月13日续发指定的11月12日五条新视频。')


def source_jobs():
    """Read original frozen records; never scan the inbox or rewrite the parent."""
    control = upload.read_json(upload.ROOT/'logs'/CONTROLLER, {})
    payload = control.get('payload', {})
    if (payload.get('scope') != SOURCE_SCOPE or payload.get('date') != SOURCE_DAY
            or control.get('sha256') != batch.digest(payload)
            or not isinstance(control.get('plans'), list)):
        raise ValueError('缺少完整的11月12日原素材快照，未猜选其他文件。')
    snapshots = {}
    for row in payload.get('records', []):
        pair = row.get('account'), row.get('target'), row.get('filename')
        if pair in snapshots:
            raise ValueError('原素材快照有重复条目。')
        snapshots[pair] = row
    plans = {row.get('manifest'): row.get('sha256') for row in control['plans']}
    # A committed original plan may precede its controller pointer after a crash.
    for path in (upload.ROOT/'logs').glob('frozen-material-'+SOURCE_DAY+'-*.json'):
        value = upload.read_json(path, {})
        original = value.get('payload', {})
        if original.get('current_material_scope') == SOURCE_SCOPE and original.get('current_snapshot_sha256') == control['sha256']:
            plans.setdefault(path.name, value.get('sha256'))
    selected = {}
    bindings = []
    template = None
    for name, checksum in sorted(plans.items()):
        if not isinstance(name, str) or not re.fullmatch('frozen-material-'+SOURCE_DAY+r'-[a-f0-9]{16}\.json', name):
            raise ValueError('原清单文件名异常。')
        path = upload.ROOT/'logs'/name
        value = upload.read_json(path, {})
        workflow.validate(path, value)
        original = value['payload']
        if (value['sha256'] != checksum or original.get('current_material_scope') != SOURCE_SCOPE
                or original.get('current_snapshot_sha256') != control['sha256']):
            raise ValueError('原清单与11月12日素材快照不一致。')
        used = False
        for job in original['jobs']:
            if job.get('account') not in EXPECTED or job.get('target') != 'personal':
                continue
            account = job['account']
            record = snapshots.get((account, 'personal', EXPECTED[account]), {})
            if (job.get('filename') != EXPECTED[account] or not re.fullmatch(r'[a-f0-9]{64}', str(job.get('video_sha256', '')))
                    or job.get('video_sha256') != record.get('video_sha256')
                    or job.get('video_size') != record.get('size')):
                raise ValueError('指定账号的原视频文件名、大小或指纹不一致：'+account)
            if account in selected and selected[account] != job:
                raise ValueError('同一账号存在不同的原冻结任务：'+account)
            selected[account] = copy.deepcopy(job)
            if template is not None and any(original.get(field) != template.get(field) for field in ('comment_text', 'publication_content_sha256')):
                raise ValueError('五条原任务的正文评论版本不一致。')
            template = original
            used = True
        if used:
            bindings.append(dict(manifest=name, sha256=checksum))
    if set(selected) != set(EXPECTED):
        raise ValueError('原冻结清单缺少指定的五条视频：'+','.join(sorted(set(EXPECTED)-set(selected))))
    content = batch.preferences.content_policy(SOURCE_DAY, template.get('publication_content_sha256'))
    if (not content or content['payload']['caption'] != batch.preferences.EVERYDAY_CAPTION
            or content['payload']['comment'] != batch.preferences.EVERYDAY_COMMENT):
        raise ValueError('原任务正文或评论不是之前确认的实拍文案。')
    origin = dict(controller=CONTROLLER, snapshot_sha256=control['sha256'], date=SOURCE_DAY, plans=bindings)
    return [selected[account] for account in EXPECTED], origin, template


def previous_attempt(job, origin):
    for source in origin['plans']:
        path = upload.ROOT/'logs'/source['manifest']
        report = upload.read_json(path.with_name(path.stem+'-results.json'), None)
        if report is None:
            continue
        if not isinstance(report, dict) or report.get('manifest') != path.name or not isinstance(report.get('attempts'), list):
            raise ValueError('原批次执行记录异常，未重新发布。')
        if any(row.get('key') == job['key'] for row in report['attempts']):
            return True
    return False


def validate(path, value, jobs, origin):
    workflow.validate(path, value)
    payload = value['payload']
    if (payload.get('date') != DAY or payload.get('continuation_scope') != SCOPE
            or payload.get('continuation_origin') != origin or payload.get('jobs') != jobs):
        raise ValueError('五账号续发范围或原素材指纹发生变化。')


def prepare():
    require_day()
    jobs, origin, template = source_jobs()
    pointer = upload.ROOT/'logs'/POINTER
    saved = upload.read_json(pointer, None)
    if saved is not None:
        name = saved.get('manifest', '')
        if saved.get('scope') != SCOPE or not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json', name):
            raise ValueError('五账号续发记录异常，未另建发布任务。')
        path = upload.ROOT/'logs'/name
        value = upload.read_json(path, {})
        validate(path, value, jobs, origin)
        if saved.get('sha256') != value['sha256']:
            raise ValueError('续发清单校验失败。')
        return path, value
    orphans = []
    for path in (upload.ROOT/'logs').glob('frozen-material-'+DAY+'-*.json'):
        value = upload.read_json(path, {})
        if value.get('payload', {}).get('continuation_scope') == SCOPE:
            validate(path, value, jobs, origin)
            orphans.append((path, value))
    if len(orphans) > 1:
        raise ValueError('发现多个五账号续发清单，未猜选或重建。')
    if orphans:
        path, value = orphans[0]
    else:
        state = upload.read_json(upload.ROOT/'logs/publish_state.json', {})
        for job in jobs:
            # Existing records will be skipped by the core. Never grant them a
            # fresh retry merely by putting their key in a new dated manifest.
            if job['key'] not in state:
                if previous_attempt(job, origin):
                    raise ValueError('原任务已有尝试但缺少最终记录，需先核实：'+job['account'])
                entry = batch.validate_job(job, date=DAY)
                video = upload.inbox_for(entry)/job['filename']
                if video.is_symlink() or batch.file_hash(video) != job['video_sha256'] or video.stat().st_size != job['video_size']:
                    raise ValueError('原视频内容变化，未选择其他素材：'+job['account'])
        policy = batch.preferences.load(DAY)
        now = datetime.now(timezone.utc)
        payload = dict(schema=batch.SCHEMA, date=DAY, start=now.isoformat(), requested_start=now.isoformat(),
                       ai_label=False, include_fb10_pages=True, excluded_accounts=sorted(batch.excluded_accounts(DAY)),
                       comment_text=template['comment_text'], jobs=jobs,
                       publication_preferences_sha256=policy['sha256'],
                       publication_content_sha256=template['publication_content_sha256'],
                       comment_retry_policy=priority.COMMENT_RECOVERY_VERSION,
                       continuation_scope=SCOPE, continuation_origin=origin)
        value = dict(payload=payload, sha256=batch.digest(payload), created_at=now.isoformat(), issues=[],
                     workflow='future-video-comments-v1', auto_retry_policy=priority.retry.POLICY,
                     comment_timing=priority.TIMING, priority_workflow=priority.PRIORITY_WORKFLOW_VERSION,
                     report_format='text', scheduled_priority_runner=workflow.VERSION,
                     browser_launch_mode=normal.NORMAL_CHROME_VERSION, local_file_input_mode=local.VERSION)
        path = upload.ROOT/'logs'/('frozen-material-'+DAY+'-'+value['sha256'][:16]+'.json')
        validate(path, value, jobs, origin)
        upload.save_json(path, value)
    upload.save_json(pointer, dict(scope=SCOPE, manifest=path.name, sha256=value['sha256']))
    return path, value


@contextlib.contextmanager
def launcher(value):
    with patch.object(upload, 'launch_context', normal.launcher_for_jobs(value['payload']['jobs'], date=DAY)):
        yield


def before_job(job, value):
    require_day()
    _, origin, _ = source_jobs()
    if origin != value['payload']['continuation_origin']:
        raise ValueError('原素材来源已变化，保留任务停止。')
    if previous_attempt(job, origin):
        raise ValueError('原批次此视频已有尝试，保留记录，需先核实：'+job['account'])
    entry = batch.validate_job(job, date=DAY)
    video = upload.inbox_for(entry)/job['filename']
    if video.is_symlink() or batch.file_hash(video) != job['video_sha256'] or video.stat().st_size != job['video_size']:
        raise ValueError('原视频内容变化，未替换发布素材。')


def execute():
    require_day()
    workflow.require_versions()
    with locked():
        path, value = prepare()
    print('仅续发11月12日这五条新视频：fb16、fb17、fb18、fb21、fb24。全部实拍，AI标签关闭。', flush=True)
    for job in value['payload']['jobs']:
        print(job['account']+'/personal', job['filename'], flush=True)
    print('复用已保存账号资料和文案；先发布五条视频，再安全补发一次，最后评论及补评。请保持窗口打开。', flush=True)
    with priority.daily.keep_awake(), owners.scoped(set(EXPECTED)), editor.installed():
        with launcher(value):
            batch.run(path, defer_comments=True, resume=True, before_job=lambda job: before_job(job, value))
        with launcher(value):
            priority.retry.run(path)
        rows = []
        with launcher(value), patch.object(priority.daily, 'find_published', priority.actual.make_finder(value['payload']['jobs'], True)):
            priority.daily.backfill(value, None, only_keys={job['key'] for job in value['payload']['jobs']},
                                    rows=rows, future_only=True, reporter=lambda *_: priority.comment_report(path, value, rows))
        with launcher(value):
            priority.comment_retry.run(path, reporter=lambda m, r, o: priority.comment_report(path, value, r))
    report = upload.read_json(path.with_name(path.stem+'-results.json'), {})
    final = batch.results(path, value, report.get('attempts', []), None, final=True)
    return 0 if final and all(row['video_status'] == 'published' and row['comment_status'] in {'sent', 'already_present'} for row in final) else 3


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    try:
        if upload.ROOT.resolve() != Path(sys.argv[1]).resolve():
            raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:
        print('已暂停；保留五条视频及评论记录，重跑继续此清单。', flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', str(error) or type(error).__name__, flush=True)
        raise SystemExit(1)
