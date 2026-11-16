"""Real-footage new50 queue with immutable authorization and actual execution timestamps.

These are scope-local variants of the existing validators/freezer/runner. The
original real-footage workflows remain strict and unchanged on disk.
"""
import contextlib,copy,re,shutil,sys,time,traceback,uuid
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import publish_distributed_nov13_first24 as first
upload=first.upload
batch=first.batch
retry=first.priority.retry
daily=first.priority.daily
DAY=None
MATERIAL_DAY=None
CONTENT_SHA=None
QUEUE_ID=None
SCOPE=None
AUTH='user-confirmed-real-new50-request-20261116-v1'
GRANT=None
STAGE_SHA=None
VERSION='1.0-source-bound-cross-midnight-real50'



def has_submission(row):
    if isinstance(row,list):return any(has_submission(r) for r in row)
    if not isinstance(row,dict):return False
    return row.get('status') in {'published','posting','needs_review'} or any(row.get(k) for k in ('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at')) or any(has_submission(v) for v in row.values() if isinstance(v,(dict,list)))

def load_queue(path):
    path=Path(path);path.resolve().relative_to((upload.ROOT/'logs').resolve())
    value=upload.read_json(path,{})
    validate_queue(path,value,DAY)
    return path,value

def validate_run_manifest(path,value):
    p=value.get('payload',{});sha=batch.digest(p)
    if path.name.startswith('frozen-material-'):return validate_queue(path,value,DAY)
    if (value.get('sha256')!=sha or path.name!='automatic-retry-'+DAY+'-'+sha[:16]+'.json' or p.get('run_kind')!='automatic-safe-retry-v1'
            or value.get('comment_timing')!=first.priority.TIMING):raise ValueError('实拍新增50补发执行队列校验失败。')
    parent,source=load_queue(upload.ROOT/'logs'/p.get('source_manifest',''))
    if p.get('source_sha256')!=source['sha256']:raise ValueError('实拍新增50补发队列原清单变化。')
    original={j['key']:j for j in source['payload']['jobs']};jobs=p.get('jobs',[])
    if not jobs or len({j['key'] for j in jobs})!=len(jobs) or any(original.get(j['key'])!=j for j in jobs):raise ValueError('实拍新增50补发队列混入其他任务。')
    expected=copy.deepcopy(source['payload']);expected.update(jobs=jobs,run_kind='automatic-safe-retry-v1',source_manifest=parent.name,source_sha256=source['sha256'])
    if p!=expected:raise ValueError('实拍新增50补发队列策略、素材或文案变化。')

@contextlib.contextmanager
def installed(stage_sha,material_day,content_sha,queue_id,scope,stamp_day,grant):
    if not re.fullmatch('[a-f0-9]{64}',str(stage_sha)):raise ValueError('排队素材指纹缺失。')
    with patch(__name__+'.STAGE_SHA',stage_sha),patch(__name__+'.MATERIAL_DAY',material_day),patch(__name__+'.CONTENT_SHA',content_sha),patch(__name__+'.QUEUE_ID',queue_id),patch(__name__+'.SCOPE',scope),patch(__name__+'.DAY',stamp_day),patch(__name__+'.GRANT',grant),patch.object(first.priority,'validate',side_effect=validate_queue),patch.object(batch,'run',side_effect=run_queue),patch.object(retry,'load_source',side_effect=load_queue),patch.object(retry,'decide',side_effect=decide_queue),patch.object(first,'freeze',side_effect=freeze_queue):
        yield


def validate_queue(path, value, date):
    payload = value.get('payload', {})
    # date is the immutable planned/frozen date, not a fabricated system clock.
    # Execution after midnight is authorized only for this exact new50 source.
    date=payload.get('date','')
    actual_day=datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) or not MATERIAL_DAY<=date<=actual_day:raise ValueError('排队执行日期或来源异常。')
    checksum = batch.digest(payload)
    jobs = payload.get('jobs', [])
    content = batch.content_for_payload(payload)
    expected_comment = content['payload']['comment'] if content else daily.COMMENT
    if payload.get('comment_retry_policy') not in {None, first.priority.COMMENT_RECOVERY_VERSION}:
        raise ValueError('本批补评规则不匹配')
    if value.get('sha256') != checksum or payload.get('schema') != batch.SCHEMA or payload.get('date') != date or (not re.fullmatch('frozen-material-' + re.escape(date) + '-' + checksum[:16] + '\\.json', path.name)) or (value.get('workflow') != 'future-video-comments-v1') or (value.get('auto_retry_policy') != retry.POLICY) or (value.get('comment_timing') != first.priority.TIMING) or (value.get('priority_workflow') != first.priority.PRIORITY_WORKFLOW_VERSION) or (value.get('report_format') != 'text') or (payload.get('ai_label') is not False) or (payload.get('include_fb10_pages') is not True) or (payload.get('comment_text') != expected_comment) or (set(payload.get('excluded_accounts', [])) != batch.excluded_accounts(date)) or (not jobs) or (len({j.get('key') for j in jobs}) != len(jobs)) or any((not batch.eligible(j, True, date=date) or not re.fullmatch('[a-f0-9]{64}', str(j.get('key', ''))) for j in jobs)):
        raise ValueError('今天优先发布批次的清单、范围或策略校验失败')
    policy = batch.preferences.load(date)
    caption = content['payload']['caption'] if content else policy['payload']['caption'] if policy else None
    if policy and (payload.get('publication_preferences_sha256') != policy['sha256'] or any((j.get('caption_text') != caption for j in jobs))):
        raise ValueError('本批统一正文或后续发布规则已变化，未使用旧文案')
    if payload.get('queue_authorization') != AUTH or payload.get('queue_scope') != SCOPE or payload.get('stage_sha256') != STAGE_SHA or (payload.get('material_source_date') != MATERIAL_DAY) or payload.get('real_footage_confirmed') is not True or payload.get('queue_id')!=QUEUE_ID or any((j['account'] not in first.ALLOWED for j in jobs)):
        raise ValueError('本批实拍新增50标签开启授权、素材来源或范围不符。')
    if any(not batch.eligible(j,True,date=actual_day) for j in jobs):raise ValueError('当前账号发布授权已变化，保留队列。')
    if payload.get('distributed_scope') != SCOPE:
        bindings = payload.get('source_bindings', [])
        if payload.get('explicit_prepost_grant') != GRANT or len(bindings) != 1:
            raise ValueError('实拍新增50补发许可来源异常。')
        parent = upload.ROOT / 'logs' / bindings[0]['manifest']
        original = first.archive.checked_json(parent)
        if original['payload'].get('distributed_scope') != SCOPE or original['sha256'] != bindings[0]['sha256']:
            raise ValueError('实拍新增50补发不属于原批次。')
        validate_queue(parent, original, date)
        if jobs != original['payload']['jobs'] or payload.get('distribution_sha256') != original['payload'].get('distribution_sha256'):
            raise ValueError('实拍新增50补发原视频范围发生变化。')

def freeze_queue():
    pointer = upload.ROOT / 'logs' / first.POINTER
    saved = upload.read_json(pointer, None)
    if saved:
        name = saved.get('manifest', '')
        if not re.fullmatch('frozen-material-' + DAY + '-[a-f0-9]{16}\\.json', name):
            raise ValueError('今天续跑指针异常。')
        path = upload.ROOT / 'logs' / name
        value = upload.read_json(path, {})
        _, material, _, _ = first.distribution(value.get('payload', {}).get('distribution_manifest'))
        first.validate(path, value, material)
        if saved.get('sha256') != value['sha256']:
            raise ValueError('今天续跑清单校验失败。')
        return (path, value)
    owned = []
    for path in (upload.ROOT / 'logs').glob('frozen-material-' + DAY + '-*.json'):
        value = upload.read_json(path, {})
        if value.get('payload', {}).get('distributed_scope') == SCOPE:
            _, material, _, _ = first.distribution(value['payload'].get('distribution_manifest'))
            first.validate(path, value, material)
            owned.append((path, value))
    if len(owned) > 1:
        raise ValueError('今天有多个同范围清单，未猜选。')
    if owned:
        path, value = owned[0]
        upload.save_json(pointer, dict(manifest=path.name, sha256=value['sha256']))
        return (path, value)
    material_path, material, rows, duplicates = first.distribution()
    content = batch.preferences.content_policy(MATERIAL_DAY,CONTENT_SHA)
    policy = batch.preferences.load(DAY)
    if not content or content['payload']['caption'] != batch.preferences.EVERYDAY_CAPTION or content['payload']['comment'] != batch.preferences.EVERYDAY_COMMENT:
        raise ValueError('已保存正文和评论不是之前确认的版本，未擅自替换。')
    config = upload.read_json(upload.CONFIG, {})
    state = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
    urls = Counter((upload.target_key(e['url']) for e in config.get('targets', []) if e.get('account') in first.ALLOWED and e.get('url')))
    previous = batch.previous_plan_keys(DAY)
    for old in (upload.ROOT / 'logs').glob('frozen-material-' + DAY + '-*.json'):
        if not re.fullmatch('frozen-material-' + DAY + '-[a-f0-9]{16}\\.json', old.name):
            continue
        candidate = first.archive.checked_json(old)
        if candidate.get('payload', {}).get('schema') == batch.SCHEMA:
            previous.update({j['key']: old.name for j in candidate['payload'].get('jobs', [])})
    jobs = []
    issues = []
    old_files = []
    backup = upload.ROOT / 'backups' / ('new50-real-materials-' + uuid.uuid4().hex[:12])
    protected = first.archive.today_files()
    for index, assignment in enumerate(rows, 1):
        account, target = (assignment['account'], assignment['target'])
        file = assignment.get('files', [{}])[-1]
        print('核对今天分配素材：', index, '/', len(rows), account, target, file.get('destination_name', ''), flush=True)
        try:
            filename = file.get('destination_name', '')
            upload.validate_video_filename(filename)
            entries = [e for e in config.get('targets', []) if (e.get('account'), e.get('target')) == (account, target)]
            if len(entries) != 1:
                raise ValueError('没有唯一已登记目标，不要求重新填写名称，也不猜选账号')
            entry = entries[0]
            upload.validate_entry(entry)
            if urls[upload.target_key(entry['url'])] != 1:
                raise ValueError('同一主页配置到多个目标，未猜选重复发布')
            if assignment.get('url') and upload.target_key(assignment['url']) != upload.target_key(entry['url']):
                raise ValueError('分配后账号身份已变化')
            if not batch.eligible(entry, True, date=DAY):
                raise ValueError('目标未完成发布登记或尚未允许发布')
            if not (upload.ROOT / 'profiles' / account).is_dir():
                raise ValueError('原登录资料缺失')
            video = first.archive.safe(upload.inbox_for(entry) / filename)
            if first.archive.info(video) != dict(size=file['size'], sha256=file['sha256']):
                raise ValueError('今天分配视频已变化或缺失')
            key = upload.job_key(entry, video)
            if key in state or key in previous or account + '/' + target in duplicates:
                raise ValueError('今天分配的内容与已有任务重复，保留旧记录，不重发或另选其他视频')
            caption = video.with_suffix('.txt')
            text = content['payload']['caption']
            if not caption.is_file() or caption.read_text(encoding='utf-8-sig').strip() != text:
                backup.mkdir(parents=True, exist_ok=True)
                if caption.exists():
                    shutil.copy2(caption, backup / (account + '-' + target + '-' + caption.name))
                first.atomic_caption(caption, text)
            job = dict(account=account, target=target, filename=filename, key=key, url=entry['url'], entry_sha256=batch.digest(entry), caption_text=text, caption_sha256=batch.file_hash(caption), video_size=file['size'], video_sha256=file['sha256'], publication_content_sha256=content['sha256'])
            jobs.append(job)
            for older in sorted(video.parent.iterdir(), key=lambda p: p.name):
                if not older.is_file() or older.suffix.lower() != '.mp4' or older == video or (str(older).casefold() in protected):
                    continue
                old_info = first.archive.info(older)
                identity = batch.digest(dict(account=account, target=target, name=older.name, **old_info))
                destination = first.archive.safe(video.parent.parent / 'archive' / ('before-' + DAY) / identity[:16])
                if destination.exists():
                    destination = destination.with_name(identity[:16] + '-' + uuid.uuid4().hex[:8])
                files = []
                for source in (older.with_suffix('.txt'), older.with_suffix('.comment.txt'), older):
                    if source.is_file() and str(source).casefold() not in protected:
                        files.append(dict(source=first.archive.relative(source), destination=first.archive.relative(destination / source.name), kind='video' if source == older else 'text', **first.archive.info(source)))
                related = []
                for old_key, row in state.items():
                    if (row.get('account'), row.get('target')) == (account, target) and str(row.get('video', '')).replace('\\', '/').split('/')[-1] == older.name:
                        try:
                            if upload.job_key(dict(url=row['url']), older) == old_key:
                                related.append(old_key)
                        except ValueError:
                            pass
                old_files.append(dict(id=identity, account=account, target=target, files=files, state_keys=related))
        except Exception as error:
            issues.append(dict(account=account, target=target, filename=file.get('destination_name', ''), reason=str(error) or type(error).__name__))
    if not jobs:
        raise ValueError('没有可发布的今天新素材：' + str(issues))
    now = datetime.now(timezone.utc)
    payload = dict(schema=batch.SCHEMA, date=DAY, start=(now + timedelta(seconds=75)).isoformat(), requested_start=now.isoformat(), ai_label=False, include_fb10_pages=True, excluded_accounts=sorted(batch.excluded_accounts(DAY)), comment_text=content['payload']['comment'], jobs=jobs, publication_content_sha256=content['sha256'], publication_preferences_sha256=policy['sha256'], comment_retry_policy=first.priority.COMMENT_RECOVERY_VERSION, distributed_scope=SCOPE, distribution_manifest=first.archive.relative(material_path), distribution_sha256=material['sha256'], old_material_files=old_files, intended_accounts=sorted(first.ALLOWED), queue_authorization=AUTH, queue_scope=SCOPE, stage_sha256=STAGE_SHA, material_source_date=MATERIAL_DAY, real_footage_confirmed=True, queue_id=QUEUE_ID)
    value = dict(payload=payload, sha256=batch.digest(payload), created_at=now.isoformat(), issues=issues, workflow='future-video-comments-v1', auto_retry_policy=first.priority.retry.POLICY, comment_timing=first.priority.TIMING, priority_workflow=first.priority.PRIORITY_WORKFLOW_VERSION, report_format='text', scheduled_priority_runner=first.workflow.VERSION, browser_launch_mode=first.normal.NORMAL_CHROME_VERSION, local_file_input_mode=first.local.VERSION)
    path = upload.ROOT / 'logs' / ('frozen-material-' + DAY + '-' + value['sha256'][:16] + '.json')
    first.validate(path, value, material)
    upload.save_json(path, value)
    upload.save_json(pointer, dict(manifest=path.name, sha256=value['sha256']))
    return (path, value)

def run_queue(path, output_dir=None, before_job=None, defer_comments=False, retry_before_post=False, resume=False):
    path = Path(path)
    path.resolve().relative_to((upload.ROOT / 'logs').resolve())
    manifest = upload.read_json(path, {})
    validate_run_manifest(path, manifest)
    payload = manifest.get('payload', {})
    if payload.get('schema') != batch.SCHEMA or batch.digest(payload) != manifest.get('sha256'):
        raise ValueError('冻结计划校验失败')
    batch.content_for_payload(payload)
    now = datetime.now(timezone.utc)
    if now < datetime.fromisoformat(payload['start']):
        raise ValueError('尚未到指定开始时间，不提前发布')
    if upload.VERSION not in {'2.38', '2.39', '2.40', '2.41', '2.42', '2.43', '2.44', '2.45', '2.46', '2.47'}:
        raise ValueError('上传核心版本不匹配')
    with first.locked(), path.with_suffix('.log').open('a', encoding='utf-8') as log:
        attempts = []
        if resume:
            report = upload.read_json(path.with_name(path.stem + '-results.json'), None)
            if report is not None:
                keys = {j['key'] for j in payload['jobs']}
                if not isinstance(report, dict) or report.get('manifest') != path.name or (not isinstance(report.get('attempts'), list)) or any((not isinstance(a, dict) or a.get('key') not in keys or (not a.get('action')) for a in report['attempts'])):
                    raise ValueError('续跑结果与原批次不一致，未重新发布')
                attempts = report['attempts']
        attempted = {a['key'] for a in attempts}
        with contextlib.redirect_stdout(batch.Tee(sys.stdout, log)), contextlib.redirect_stderr(batch.Tee(sys.stderr, log)):
            try:
                for job in payload['jobs']:
                    if job['key'] in attempted:
                        print('本批首轮已有尝试，保留结果，补发统一留给一次补发阶段：', job['account'], job['target'], job['filename'], flush=True)
                        continue
                    attempt = dict(account=job['account'], target=job['target'], key=job['key'], started_at=datetime.now(timezone.utc).isoformat())
                    try:
                        state_path = upload.ROOT / 'logs/publish_state.json'
                        state = upload.read_json(state_path, {})
                        old = state.get(job['key'], {})
                        can_retry = (retry_before_post and old.get('status') == 'failed_before_post' and (not any((old.get(k) for k in ('success_message', 'permalink', 'confirmation_method', 'confirmed_at', 'post_intent_at', 'today_first_retry_used'))))) and (not has_submission(old))
                        if job['key'] in state and (not can_retry):
                            print('原素材已有记录，不重发：', job['account'], job['filename'], state[job['key']].get('status'), flush=True)
                            attempt['action'] = 'existing_record'
                            continue
                        if any((r.get('account') == job['account'] and r.get('status') in {'preparing', 'posting'} for r in state.values())):
                            raise RuntimeError('该账号仍有准备中或提交中的旧任务，不关闭其浏览器、不解除记录；需手动核实')
                        entry = batch.validate_job(job, date=payload['date'])
                        if before_job is not None:
                            before_job(job)
                            state = upload.read_json(state_path, {})
                        batch.close_selected_window(entry['account'])
                        entry = dict(entry, enabled=True, auto_switch_personal=True, _authorized_comment_text=payload['comment_text'])
                        if manifest.get('comment_timing') == 'immediate-after-publication-v1' and (not defer_comments):
                            entry['_immediate_verified_comment'] = True
                        print('\n开始本批原视频：', job['account'], job['target'], job['filename'], flush=True)
                        if payload.get('run_kind') == 'automatic-safe-retry-v1':
                            entry['_automatic_retry'] = dict(source_manifest=payload['source_manifest'], source_sha256=payload['source_sha256'], retry_number=1)
                        upload.run_entry(entry, state, state_path, True, filename=job['filename'], ai_label_override=False, expected_job_key=job['key'], preserve_old_review_for_exact_job=True, defer_comments=defer_comments, retry_before_post=can_retry)
                        attempt['action'] = 'finished'
                    except KeyboardInterrupt:
                        attempt.update(action='interrupted', error='用户中断，保留原状态，禁止直接重复发布')
                        raise
                    except Exception as error:
                        message = str(error).strip() or type(error).__name__
                        attempt.update(action='manual_required', error=message)
                        try:
                            (upload.ROOT / 'logs' / ('batch-' + job['key'][:12] + '-error.txt')).write_text(traceback.format_exc(), encoding='utf-8')
                        except OSError:
                            pass
                        print('此目标停止并保留记录，继续其他确切素材：', message.split('\n', 1)[0], flush=True)
                    finally:
                        attempts.append(attempt)
                        batch.results(path, manifest, attempts, output_dir)
            finally:
                rows = batch.results(path, manifest, attempts, output_dir, final=True)
    return 0 if all((r['video_status'] == 'published' and r['comment_status'] in {'sent', 'already_present'} for r in rows)) else 3

def decide_queue(job, value, state, attempt, claims):
    if has_submission(state.get(job['key'], {})):
        return (False, '已有提交证据，保留不重发')
    if job['key'] in claims['jobs']:
        return (False, '此视频已使用自动补发机会')
    if not isinstance(attempt, dict) or attempt.get('key') != job['key'] or attempt.get('action') != 'manual_required':
        return (False, '本批首轮没有可恢复的失败尝试')
    since = datetime.fromisoformat(value['created_at']).timestamp() - 5
    try:
        if datetime.fromisoformat(attempt['started_at']).timestamp() < since:
            return (False, '失败尝试不属于本批次')
    except (KeyError, TypeError, ValueError):
        return (False, '失败尝试缺少批次时间证据')
    record = state.get(job['key'])
    if record is not None:
        if not isinstance(record, dict) or record.get('status') != 'failed_before_post' or any((record.get(k) for k in retry.PROOF_FIELDS)):
            return (False, '已成功、已提交、待核实或已经重试，保留不重发')
        if (record.get('account'), record.get('target')) != (job['account'], job['target']) or upload.target_key(record.get('url', '')) != upload.target_key(job['url']) or str(record.get('video', '')).replace('\\', '/').split('/')[-1] != job['filename'] or (record.get('uploader_version') not in {'2.46', '2.47'}) or (record.get('ai_label_requested') is not False):
            return (False, '原任务身份或发布日志版本不满足自动补发要求')
        try:
            if datetime.fromisoformat(record['created']).timestamp() < since:
                return (False, '任务早于本批次')
        except (KeyError, TypeError, ValueError):
            return (False, '任务缺少本批次时间证据')
    if any((r.get('account') == job['account'] and r.get('status') in {'preparing', 'posting'} for r in state.values())):
        return (False, '该账号仍有准备或提交中的任务，未关闭浏览器')
    reason = str(record.get('error', '') if record else '') or str(attempt.get('error', ''))
    stage = record.get('failure_stage', '') if record else ''
    if retry.DENY.search(reason):
        return (False, '需要人工处理身份、安全验证或文件配置，未自动重试')
    recoverable = bool(retry.RECOVER.search(reason))
    recoverable |= bool(re.search('Timeout\\s+\\d+\\s*ms\\s+exceeded', reason, re.I)) and stage in retry.TIMEOUT_STAGES
    recoverable |= 'intercepts pointer events' in reason and stage in retry.POINTER_STAGES
    recoverable |= bool(re.search('Locator expected to be visible|element is not attached to the DOM', reason, re.I)) and stage in retry.POINTER_STAGES | {'wait_reel_editor', 'verify_selected_media', 'verify_public_audience', 'verify_ai_label'}
    recoverable |= bool(re.search('未捕获到选文件窗口.*未找到\\s*Reels\\s*上传框', reason)) and stage in {'open_reel_menu', 'select_exact_video'}
    recoverable |= 'net::ERR_ABORTED' in reason and stage in {'open_target_profile', 'verify_identity'}
    if not recoverable:
        return (False, '错误不在可恢复范围，保留给人工核实')
    return (True, '首轮发布前的可恢复错误：' + reason.split('\n', 1)[0][:260])
