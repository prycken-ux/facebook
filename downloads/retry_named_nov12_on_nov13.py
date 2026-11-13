"""User-confirmed absent Nov12 videos, selected by 15 exact saved names; no comments."""
import contextlib
import copy
import re
import shutil
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

if __name__ == '__main__':
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import scheduled_priority_workflow as workflow
import normal_chrome_batch as normal
import local_file_input as local
import personal_owner_routes as personal
import recovery_numeric_identity as numeric
import page_reel_ai_compat as editor
import actual_reels_comment_lookup as actual
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

DAY = '2026-11-13'
SOURCE_DAY = '2026-11-12'
SOURCE_SCOPE = 'nov12-current-materials-fb01-to-fb24-v1'
GRANT = 'nov12-fifteen-user-confirmed-absent-video-only-20261113-v1'
NAMES = (
    'Alice Luther', 'Prycken June', 'Prycken BK', 'Andrew Judd', 'Marlene Camp',
    'Daniel Vasquez', 'Keith Lawrence', 'Johnny Utah', 'Cyrus Marlene',
    'Donna Merrill', 'Drascreflo Chajundfro', 'Thockspiwem Thimbrojospo',
    'Thoslilda Changrabro', 'Hacrasnite Hacaldcirtsle', 'Swackgespa Roltceblu',
)
PROTECTED_ACCOUNTS = {'fb16', 'fb17', 'fb18', 'fb21', 'fb24'}
SUCCESS_FIELDS = ('permalink', 'success_message', 'confirmation_method', 'confirmed_at', 'published_at', 'archived_video')


def require_day():
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat() != DAY:
        raise ValueError('本指令仅授权11月13日补发这15个目标的11月12日原视频。')


def normalized(name):
    return ' '.join(unicodedata.normalize('NFKC', str(name or '')).split()).casefold()


def source():
    control = upload.read_json(upload.ROOT/'logs/nov12-current-materials-original-accounts.json', {})
    payload = control.get('payload', {})
    if (payload.get('scope') != SOURCE_SCOPE or payload.get('date') != SOURCE_DAY
            or control.get('sha256') != batch.digest(payload) or not isinstance(control.get('plans'), list)):
        raise ValueError('缺少有效11月12日原素材快照，未扫描其他素材。')
    snapshots = {}
    for row in payload.get('records', []):
        pair = row.get('account'), row.get('target'), row.get('filename')
        if pair in snapshots:
            raise ValueError('原快照存在重复条目。')
        snapshots[pair] = row
    plans = {row.get('manifest'): row.get('sha256') for row in control['plans']}
    for path in (upload.ROOT/'logs').glob('frozen-material-'+SOURCE_DAY+'-*.json'):
        value = upload.read_json(path, {})
        if (value.get('payload', {}).get('current_material_scope') == SOURCE_SCOPE
                and value['payload'].get('current_snapshot_sha256') == control['sha256']):
            plans.setdefault(path.name, value.get('sha256'))
    by_pair = {}
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
            raise ValueError('原清单与原素材快照不一致。')
        if template is not None and any(original.get(k) != template.get(k) for k in ('publication_content_sha256', 'comment_text')):
            raise ValueError('原批次文案版本不一致。')
        template = original
        bindings.append(dict(manifest=name, sha256=checksum))
        for job in original['jobs']:
            record = snapshots.get((job['account'], job['target'], job['filename']), {})
            if (not re.fullmatch(r'[a-f0-9]{64}', str(job.get('video_sha256', '')))
                    or job.get('video_sha256') != record.get('video_sha256') or job.get('video_size') != record.get('size')):
                raise ValueError('原视频快照指纹不一致。')
            rows = by_pair.setdefault((job['account'], job['target']), {})
            if job['key'] in rows and rows[job['key']] != job:
                raise ValueError('同一视频的原冻结条目不一致。')
            rows[job['key']] = job
    if template is None:
        raise ValueError('没有11月12日原冻结任务。')
    config = upload.read_json(upload.CONFIG, {})
    jobs, labels, issues = [], {}, []
    for name in NAMES:
        entries = [e for e in config.get('targets', []) if normalized(e.get('name')) == normalized(name)]
        if len(entries) != 1:
            issues.append(dict(name=name, reason='没有唯一同名登记目标，未猜选账号'))
            continue
        entry = entries[0]
        pair = entry.get('account'), entry.get('target')
        if (not re.fullmatch(r'fb(?:0[1-9]|1[0-9]|2[0-4])', str(pair[0]))
                or pair[0] in PROTECTED_ACCOUNTS or pair[0] == 'fb09'):
            issues.append(dict(name=name, reason='目标不属于本次15个指定失败账号的可发布范围'))
            continue
        candidates = list(by_pair.get(pair, {}).values())
        if len(candidates) != 1 or candidates[0].get('entry_sha256') != batch.digest(entry):
            issues.append(dict(name=name, reason='没有唯一原冻结视频，或账号配置已变化'))
            continue
        job = copy.deepcopy(candidates[0])
        if job['key'] in labels:
            issues.append(dict(name=name, reason='两个名称对应同一原任务，未重复添加'))
            continue
        jobs.append(job)
        labels[job['key']] = name
    origin = dict(snapshot_sha256=control['sha256'], date=SOURCE_DAY, plans=bindings)
    return sorted(jobs, key=lambda j: (j['account'], j['target'])), labels, issues, origin, template


def prepare():
    require_day()
    jobs, labels, issues, origin, template = source()
    if not jobs:
        raise ValueError('未找到可唯一对应的指定失败视频：'+str(issues))
    pointer = upload.ROOT/'logs'/(GRANT+'.json')
    saved = upload.read_json(pointer, None)
    def validate(path, value):
        workflow.validate(path, value)
        payload = value['payload']
        if (payload.get('date') != DAY or payload.get('named_absent_grant') != GRANT
                or payload.get('source_origin') != origin or payload.get('jobs') != jobs
                or payload.get('selected_names') != labels or payload.get('comment_policy') != 'do_not_send'
                or value.get('issues') != issues):
            raise ValueError('本次15个目标的原素材、名称或仅视频范围已变化，未重建任务。')
    if saved is not None:
        name = saved.get('manifest', '')
        if not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json', name):
            raise ValueError('指定补发清单名称异常。')
        path = upload.ROOT/'logs'/name
        value = upload.read_json(path, {})
        validate(path, value)
        if saved.get('sha256') != value['sha256']:
            raise ValueError('指定补发清单指纹异常。')
        return path, value
    orphans = []
    for path in (upload.ROOT/'logs').glob('frozen-material-'+DAY+'-*.json'):
        value = upload.read_json(path, {})
        if value.get('payload', {}).get('named_absent_grant') == GRANT:
            validate(path, value)
            orphans.append((path, value))
    if len(orphans) > 1:
        raise ValueError('存在多个指定补发清单，未重建。')
    if orphans:
        path, value = orphans[0]
    else:
        now = datetime.now(timezone.utc)
        policy = batch.preferences.load(DAY)
        payload = dict(schema=batch.SCHEMA, date=DAY, start=now.isoformat(), requested_start=now.isoformat(),
                       ai_label=False, include_fb10_pages=True, excluded_accounts=sorted(batch.excluded_accounts(DAY)),
                       jobs=jobs, publication_preferences_sha256=policy['sha256'],
                       publication_content_sha256=template['publication_content_sha256'], comment_text=template['comment_text'],
                       named_absent_grant=GRANT, source_origin=origin, selected_names=labels, comment_policy='do_not_send')
        state = upload.read_json(upload.ROOT/'logs/publish_state.json', {})
        payload['authorized_state_sha256'] = {job['key']: batch.digest(state.get(job['key'])) for job in jobs}
        value = dict(payload=payload, sha256=batch.digest(payload), created_at=now.isoformat(), issues=issues,
                     workflow='future-video-comments-v1', auto_retry_policy=workflow.retry.POLICY,
                     comment_timing=workflow.priority.TIMING, priority_workflow=workflow.priority.PRIORITY_WORKFLOW_VERSION,
                     report_format='text', scheduled_priority_runner=workflow.VERSION,
                     browser_launch_mode=normal.NORMAL_CHROME_VERSION, local_file_input_mode=local.VERSION)
        path = upload.ROOT/'logs'/('frozen-material-'+DAY+'-'+value['sha256'][:16]+'.json')
        validate(path, value)
        upload.save_json(path, value)
    upload.save_json(pointer, dict(manifest=path.name, sha256=value['sha256']))
    return path, value


def ledger(value):
    path = upload.ROOT/'logs'/(GRANT+'-claims.json')
    result = upload.read_json(path, dict(grant=GRANT, source_sha256=value['sha256'], jobs={},
                                        authorized_state_sha256=value['payload']['authorized_state_sha256']))
    if (result.get('grant') != GRANT or result.get('source_sha256') != value['sha256'] or not isinstance(result.get('jobs'), dict)
            or result.get('authorized_state_sha256') != value['payload']['authorized_state_sha256']):
        raise ValueError('明确补发许可账本异常，未重新发放机会。')
    return path, result


def success_proof(row):
    if isinstance(row, list):
        return any(success_proof(v) for v in row)
    if not isinstance(row, dict):
        return False
    return row.get('status') == 'published' or any(row.get(k) for k in SUCCESS_FIELDS) or any(
        success_proof(v) for v in row.values() if isinstance(v, (dict, list)))


def own_attempt(row):
    if isinstance(row, list):
        return any(own_attempt(v) for v in row)
    return isinstance(row, dict) and (row.get('repair_authorization') == GRANT or any(
        own_attempt(v) for v in row.values() if isinstance(v, (dict, list))))


def checked(job, state, claims):
    row = state.get(job['key'])
    prior = claims['jobs'].get(job['key'])
    if row is not None and success_proof(row):
        return None, '已有成功或确切链接，保留，不再上传'
    if prior is None and own_attempt(row):
        return None, '此视频已有本次补发记录，许可账本缺失，保留不重发'
    if prior is None and batch.digest(row) != claims['authorized_state_sha256'].get(job['key']):
        raise ValueError('原任务在本次授权快照后变化，未解除新记录。')
    if prior is not None and prior.get('phase') == 'consumed':
        return None, '本次已尝试，保留结果，不重复提交'
    if prior is not None and (prior.get('phase') not in {'reserved', 'not_started'}
                             or row not in (prior.get('original_record'), prior.get('replacement_record'))):
        return None, '本次许可已有新任务记录，保留待核实'
    if row is not None:
        if ((row.get('account'), row.get('target')) != (job['account'], job['target'])
                or upload.target_key(row.get('url', '')) != upload.target_key(job['url'])
                or str(row.get('video', '')).replace('\\', '/').split('/')[-1] != job['filename']
                or row.get('status') not in {'failed_before_post', 'needs_review'}):
            raise ValueError('原任务身份不一致或仍在进行中，未解除记录。')
    if any(r.get('account') == job['account'] and r.get('status') in {'preparing', 'posting'} for r in state.values()):
        raise ValueError('此账号还有进行中任务，未关闭或覆盖。')
    entry = batch.validate_job(job, date=DAY)
    video = upload.inbox_for(entry)/job['filename']
    if video.is_symlink() or video.stat().st_size != job['video_size'] or batch.file_hash(video) != job['video_sha256']:
        raise ValueError('原视频内容变化，未选择新素材。')
    selected = upload.named_job(entry, {k: v for k, v in state.items() if k != job['key']}, job['filename'])
    if not selected or selected[0] != job['key'] or selected[3] != job['caption_text']:
        raise ValueError('原视频或原文案不一致。')
    return dict(entry, enabled=True, auto_switch_personal=True), 'ready'


def reserve(job, state, claims_path, claims):
    entry, status = checked(job, state, claims)
    if status != 'ready':
        return None, None
    original = copy.deepcopy(state.get(job['key']))
    prior = claims['jobs'].get(job['key'])
    if prior is not None:
        original = copy.deepcopy(prior['original_record'])
    replacement = dict(account=job['account'], target=job['target'], url=job['url'],
                       video=str(upload.inbox_for(entry)/job['filename']), status='failed_before_post',
                       ai_label_requested=False, uploader_version=upload.VERSION,
                       repair_authorization=GRANT, repair_previous_attempt=original)
    claims['jobs'][job['key']] = dict(phase='reserved', assertion='user_confirmed_nov12_video_absent',
                                    source_job=copy.deepcopy(job), original_record=original, replacement_record=replacement,
                                    reserved_at=datetime.now(timezone.utc).isoformat())
    upload.save_json(claims_path, claims)  # Save original/permission before replacing its retry guard.
    state[job['key']] = replacement
    upload.save_json(upload.ROOT/'logs/publish_state.json', state)
    return entry, replacement


def settle(job, replacement, claims_path, claims):
    path = upload.ROOT/'logs/publish_state.json'
    state = upload.read_json(path, {})
    item = claims['jobs'][job['key']]
    current = state.get(job['key'])
    if current is None or current == replacement:
        if item['original_record'] is None:
            state.pop(job['key'], None)
        else:
            state[job['key']] = copy.deepcopy(item['original_record'])
        item['phase'] = 'not_started'
        upload.save_json(path, state)
    else:
        item['phase'] = 'consumed'
        if current.get('status') == 'published' and current.get('comment_status') not in {'sent', 'already_present', 'sending', 'verifying', 'needs_review'}:
            current.update(comment_status='not_requested', comment_policy='user_requested_video_only')
            upload.save_json(path, state)
    item['result_status'] = state.get(job['key'], {}).get('status', 'not_started')
    upload.save_json(claims_path, claims)


def reconcile_videos(value, claims):
    """One read-only lookup pass, only for this grant's submitted receipt timeouts."""
    from playwright.sync_api import sync_playwright
    state_path = upload.ROOT/'logs/publish_state.json'
    jobs = value['payload']['jobs']
    finder = actual.make_finder(jobs, True, interactive=False, total_timeout_ms=60000)
    for job in jobs:
        state = upload.read_json(state_path, {})
        original = copy.deepcopy(state.get(job['key'], {}))
        if (claims['jobs'].get(job['key'], {}).get('phase') != 'consumed'
                or original.get('status') != 'needs_review' or not own_attempt(original)
                or original.get('review_reason') != 'publication_receipt_timeout'):
            continue
        if any(row.get('account') == job['account'] and row.get('status') in {'preparing', 'posting'} for row in state.values()):
            continue
        context = None
        try:
            require_day()
            entry = batch.validate_job(job, date=DAY)
            since = datetime.fromisoformat(original['post_intent_at']).timestamp()-5
            end = datetime.now(timezone.utc).timestamp()+5
            print('仅只读核实刚才的发布结果，不重新上传、不发送评论：', entry['name'], flush=True)
            close_selected_window(entry['account'])
            with sync_playwright() as pw:
                context = upload.launch_context(pw, dict(entry, enabled=True, auto_switch_personal=True))
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    proof = upload.ensure_identity(page, entry)
                    verified = finder(page, context, entry, job['caption_text'], since, end,
                                      diagnostic_path=upload.ROOT/'logs'/(GRANT+'-'+job['key'][:12]+'-lookup.json'))
                    # The finder verifies a unique exact author/caption/time match.
                    # The login must also remain the one proven before lookup.
                    if proof.get('recovery_login_marker') and numeric.picker.login_marker(page) != proof['recovery_login_marker']:
                        raise ValueError('只读核对期间登录身份变化，未改记录。')
                    current = upload.read_json(state_path, {})
                    if current.get(job['key']) != original:
                        raise ValueError('只读核对期间任务记录变化，未覆盖。')
                    row = current[job['key']]
                    now = datetime.now(timezone.utc).isoformat()
                    row.update(status='published', confirmation_method='readonly_unique_author_caption_post_time',
                               confirmed_at=now, confirmed_batch_lookup_cutoff=now, permalink=verified[0],
                               comment_link_job_key=job['key'], comment_link_method=verified[1],
                               comment_status='not_requested', comment_policy='user_requested_video_only',
                               error='', review_reason='')
                    upload.save_json(state_path, current)
                    print('只读核实发布成功：', entry['name'], verified[0], flush=True)
                    try:
                        batch.validate_job(job, date=DAY)
                        video = upload.inbox_for(entry)/job['filename']
                        archived = upload.archive(video, video.with_suffix('.txt'))
                        row.update(archived_video=str(archived/video.name), archived_caption=str(archived/video.with_suffix('.txt').name), archived_at=now)
                        upload.save_json(state_path, current)
                    except Exception as error:
                        print('视频已确认成功，归档需检查：', str(error).split('\n', 1)[0], flush=True)
                finally:
                    context.close()
        except KeyboardInterrupt:
            raise
        except Exception as error:
            print('保留待核实，不重新上传：', job['account'], job['target'], str(error).split('\n', 1)[0], flush=True)


def execute():
    require_day()
    workflow.require_versions()
    with locked():
        path, value = prepare()
        jobs = value['payload']['jobs']
        claims_path, claims = ledger(value)
        report_path = path.with_name(path.stem+'-results.json')
        report = upload.read_json(report_path, dict(manifest=path.name, attempts=[]))
        if report.get('manifest') != path.name or not isinstance(report.get('attempts'), list):
            raise ValueError('本次补发报告异常。')
        if report.get('attempts') and not claims_path.is_file():
            raise ValueError('已有本次执行报告但许可账本缺失，未重新发放补发机会。')
        attempts = report['attempts']
        backup = upload.ROOT/'backups'/(GRANT+'-'+uuid.uuid4().hex[:12])
        backup.mkdir(parents=True)
        for file in (upload.CONFIG, upload.ROOT/'logs/publish_state.json', claims_path, path):
            if file.is_file():
                shutil.copy2(file, backup/file.name)
        print('本次仅补发你列名及截图中的失败视频，共对应', len(jobs), '条；不发送任何评论。原记录备份：', backup, flush=True)
        for issue in value['issues']:
            print('未能确定目标，已跳过：', issue['name'], issue['reason'], flush=True)
        pages = {(j['account'], j['target']) for j in jobs if j['target'] != 'personal'}
        numeric_ensure = numeric.ensure
        with personal.scoped({j['account'] for j in jobs if j['target'] == 'personal'}), numeric.scoped(pages), editor.installed(), \
                patch.object(numeric, 'ensure', side_effect=lambda page, entry: numeric_ensure(page, entry, interactive=False)), \
                patch.object(upload, 'launch_context', normal.launcher_for_jobs(jobs, date=DAY)):
            try:
                for job in jobs:
                    attempt = dict(key=job['key'], account=job['account'], target=job['target'], started_at=datetime.now(timezone.utc).isoformat())
                    replacement = None
                    try:
                        require_day()
                        state = upload.read_json(upload.ROOT/'logs/publish_state.json', {})
                        entry, status = checked(job, state, claims)
                        if status != 'ready':
                            print('保留：', value['payload']['selected_names'][job['key']], status, flush=True)
                            attempt.update(action='existing_record', error=status)
                            continue
                        close_selected_window(entry['account'])
                        if upload.read_json(upload.ROOT/'logs/publish_state.json', {}) != state:
                            raise ValueError('关闭窗口期间任务记录变化，未覆盖。')
                        entry, replacement = reserve(job, state, claims_path, claims)
                        entry['_authorized_comment_text'] = value['payload']['comment_text']  # Link capture only; all sends deferred/disabled.
                        print('补发指定原视频：', value['payload']['selected_names'][job['key']], job['account'], job['target'], job['filename'], flush=True)
                        upload.run_entry(entry, state, upload.ROOT/'logs/publish_state.json', True,
                                         filename=job['filename'], expected_job_key=job['key'], ai_label_override=False,
                                         preserve_old_review_for_exact_job=True, retry_before_post=True, defer_comments=True)
                        attempt['action'] = 'finished'
                    except KeyboardInterrupt:
                        attempt.update(action='interrupted', error='用户暂停，保留已提交记录。')
                        raise
                    except Exception as error:
                        attempt.update(action='manual_required', error=str(error) or type(error).__name__)
                        print('此条保留结果，继续其他指定视频：', attempt['error'].split('\n', 1)[0], flush=True)
                    finally:
                        if replacement is not None:
                            settle(job, replacement, claims_path, claims)
                        attempts.append(attempt)
                        batch.results(path, value, attempts, None)
                reconcile_videos(value, claims)
            finally:
                final = batch.results(path, value, attempts, None, final=True)
                print('本次仅处理视频；没有发送、补发或重新核验评论。', flush=True)
    return 0 if not value['issues'] and all(row['video_status'] == 'published' for row in final) else 3


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    try:
        if upload.ROOT.resolve() != Path(sys.argv[1]).resolve():
            raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:
        print('已暂停；保留所有发布记录，重跑同一命令继续本次确切视频。', flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', str(error) or type(error).__name__, flush=True)
        raise SystemExit(1)
