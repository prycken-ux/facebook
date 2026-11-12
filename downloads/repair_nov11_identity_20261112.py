"""Explicit repair retry of the failed 7a07c8cc recovery; never reset a ledger."""
import contextlib
import hashlib
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

if __name__ == '__main__':
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import recover_nov11_missed_20261112 as old
import recovery_numeric_identity as identity

upload = old.upload
SCHEMA = 'nov11-numeric-identity-repair-v1'
POINTER = 'nov11-identity-repair-on-20261112.json'
FAILED_PREFIX = '7a07c8cc'
EXACT_FILES = {'fb16': '1109 (1)-1.mp4', 'fb18': '1109 (1)-3.mp4'}
ORIGINAL_VALIDATE = old.validate


def failed_source(parent):
    pointer = upload.read_json(upload.ROOT / 'logs/nov11-missed-recovery-on-20261112.json', {})
    name = pointer.get('manifest', '')
    if not re.fullmatch('frozen-material-' + old.RUN_DATE + '-' + FAILED_PREFIX + r'[a-f0-9]{8}\.json', name):
        raise ValueError('未找到这次10条发布前失败的确切恢复清单。')
    path = upload.ROOT / 'logs' / name
    value = upload.read_json(path, {})
    ORIGINAL_VALIDATE(path, value, parent)
    if pointer.get('sha256') != value['sha256'] or pointer.get('source_sha256') != parent['sha256']:
        raise ValueError('失败恢复清单与原批次绑定不一致。')
    if {(j['account'], j['target']) for j in value['payload']['jobs']} != {('fb09', f'page{n:02d}') for n in range(1, 11)} or len(value['payload']['jobs']) != 10:
        raise ValueError('失败恢复清单不是这次fb09的10条。')
    return path, value


def require_before_post(job, state):
    row = state.get(job['key'], {})
    if (row.get('status') != 'failed_before_post' or any(row.get(f) for f in old.PROOF_FIELDS + ('today_first_retry_used',))
            or (row.get('account'), row.get('target')) != (job['account'], job['target'])
            or upload.target_key(row.get('url', '')) != upload.target_key(job['url'])
            or str(row.get('video', '')).replace('\\', '/').rsplit('/', 1)[-1] != job['filename']):
        raise ValueError('原任务并非尚未补发的发布前失败；未重新上传：' + job['account'] + '/' + job['target'])


def personal_records(parent, failed):
    state = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
    previous = old.safe_failed_fb17(parent, state)
    records = []
    for account in sorted(old.PERSONALS):
        folder = upload.ROOT / 'videos' / account / 'personal/inbox'
        if account == 'fb17':
            files = [folder / previous['filename']]
        elif account in EXACT_FILES:
            filename = EXACT_FILES[account]
            if not any(i.get('account') == account and i.get('filename') == filename for i in failed.get('issues', [])):
                raise ValueError('未找到日志中被日期筛选排除的原文件：' + account)
            files = [folder / filename]
        else:
            files = [f for f in folder.glob('*.mp4') if old.yesterday_file(f.stat())]
            if len(files) != 1:
                raise ValueError(account + '昨日遗漏素材不唯一，未从今天新文件中猜选。')
        for video in files:
            if not video.is_file() or video.is_symlink() or not video.stat().st_size:
                raise ValueError('遗漏原文件不存在或为空：' + account + '/' + video.name)
            if account == 'fb17' and upload.job_key(dict(url=previous['url']), video) != previous['key']:
                raise ValueError('fb17昨天原失败视频内容已变化。')
            records.append(dict(account=account, target='personal', filename=video.name,
                                video_sha256=old.batch.file_hash(video), size=video.stat().st_size,
                                source_old_key=previous['key'] if account == 'fb17' else None))
    return records, previous


def discover_personal(account):
    from playwright.sync_api import sync_playwright
    profile = upload.ROOT / 'profiles' / account
    if not profile.is_dir() or profile.is_symlink():
        raise ValueError('缺少该编号原登录资料，未新建空白登录。')
    old.assert_free(account)
    old.close_selected_window(account)
    probe = dict(account=account, target='personal', type='personal', workflow='personal_recording_v1',
                 name='Current personal identity', url='https://www.facebook.com/me', auto_switch_personal=True)
    with sync_playwright() as pw:
        context = old.normal.launch_normal(pw, probe)
        try:
            page = context.pages[-1] if context.pages else context.new_page()
            people = {c['value'] for c in context.cookies(['https://www.facebook.com/'])
                      if c.get('name') == 'c_user' and str(c.get('value', '')).isdecimal()}
            if len(people) != 1:
                raise ValueError('未找到唯一登录者，请先在该编号原窗口登录。')
            owner = next(iter(people))
            entry = dict(probe, url='https://www.facebook.com/profile.php?id=' + owner)
            upload.navigate_profile(page, entry['url'])
            marker = identity.picker.login_marker(page)
            deadline = time.monotonic() + 8
            name = None
            while time.monotonic() < deadline:
                identity.guard(page, entry, marker)
                name = identity.public_name(page)
                if name:
                    break
                page.wait_for_timeout(200)
            if not name:
                print('此账号主页没有可识别的标题。当前窗口为本人数字ID主页：', account, entry['url'], flush=True)
                name = input('填写此窗口显示的本人主页名称；S跳过，Q结束：').strip()
                if name.upper() == 'Q':
                    raise KeyboardInterrupt
                if name.upper() == 'S':
                    raise ValueError('用户跳过本人主页名称登记。')
            if not name or len(name) > 200 or any(ord(c) < 32 for c in name):
                raise ValueError('本人主页名称无效。')
            entry['name'] = name
            proof = identity.ensure(page, entry)
            if proof.get('session_marker') != hashlib.sha256(('personal:' + owner).encode()).hexdigest():
                raise ValueError('登记期间本人数字身份变化。')
            proof['checked_at'] = datetime.now(timezone.utc).isoformat()
            return entry, proof
        finally:
            context.close()


def page_preflight(entry):
    from playwright.sync_api import sync_playwright
    old.assert_free(entry['account'])
    old.close_selected_window(entry['account'])
    with sync_playwright() as pw:
        context = old.normal.launch_normal(pw, entry)
        try:
            page = context.pages[-1] if context.pages else context.new_page()
            upload.navigate_profile(page, entry['url'])
            upload.ensure_identity(page, entry)
        finally:
            context.close()


def validate(path, value, parent, failed=None):
    ORIGINAL_VALIDATE(path, value, parent)
    if failed is None:
        _, failed = failed_source(parent)
    payload = value['payload']
    if payload.get('repair_schema') != SCHEMA or payload.get('failed_recovery_sha256') != failed['sha256']:
        raise ValueError('身份修复清单没有绑定本次失败记录。')
    page_jobs = {j['key']: j for j in failed['payload']['jobs']}
    for job in payload['jobs']:
        if job['account'] == 'fb09':
            if job['key'] not in page_jobs or job != page_jobs[job['key']]:
                raise ValueError('公共主页补发文件或身份已偏离原失败任务。')
        elif job['account'] in EXACT_FILES and job['filename'] != EXACT_FILES[job['account']]:
            raise ValueError('个人号补发混入其他文件。')


def prepare(parent_path, parent):
    with old.locked():
        failed_path, failed = failed_source(parent)
        pointer = upload.ROOT / 'logs' / POINTER
        saved = upload.read_json(pointer, None)
        if saved:
            if saved.get('schema') != SCHEMA or not re.fullmatch('frozen-material-' + old.RUN_DATE + r'-[a-f0-9]{16}\.json', str(saved.get('manifest', ''))):
                raise ValueError('身份修复续跑指针异常。')
            path = upload.ROOT / 'logs' / saved['manifest']
            value = upload.read_json(path, {})
            if saved.get('sha256') != value.get('sha256'):
                raise ValueError('身份修复续跑指纹不一致。')
            validate(path, value, parent, failed)
            return path, value
        state = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
        for job in failed['payload']['jobs']:
            require_before_post(job, state)
            old.batch.validate_job(job, date=old.RUN_DATE)
        records, previous = personal_records(parent, failed)
        config = upload.read_json(upload.CONFIG, {})
        first = old.batch.validate_job(failed['payload']['jobs'][0], date=old.RUN_DATE)
        print('先验证fb09第一个公共主页的身份切换；通过后才处理10条视频。', flush=True)
        page_preflight(first)
        jobs = [dict(j) for j in failed['payload']['jobs']]
        issues = []
        reserved = old.batch.previous_plan_keys(old.RUN_DATE)
        with patch.object(old, 'discover_personal', side_effect=discover_personal):
            for record in records:
                account = record['account']
                try:
                    old.connect(account, previous, already_locked=True)
                    config = upload.read_json(upload.CONFIG, {})
                    entries = [e for e in config['targets'] if (e['account'], e['target']) == (account, 'personal')]
                    if len(entries) != 1 or not old.batch.eligible(entries[0], True, date=old.RUN_DATE):
                        raise ValueError('当前个人号未完成发布登记。')
                    entry = entries[0]
                    video = upload.inbox_for(entry) / record['filename']
                    if old.batch.file_hash(video) != record['video_sha256'] or video.stat().st_size != record['size']:
                        raise ValueError('身份核验期间原视频内容变化。')
                    key = upload.job_key(entry, video)
                    if key in state or key in reserved:
                        raise ValueError('素材已有其他记录或冻结任务；未重新上传。')
                    content = old.prefs.content_policy(old.RUN_DATE)
                    text = content['payload']['caption']
                    caption = video.with_suffix('.txt')
                    if not caption.is_file() or caption.read_text(encoding='utf-8-sig', errors='replace').strip() != text:
                        backup = upload.ROOT / 'backups' / ('identity-repair-caption-' + uuid.uuid4().hex[:10])
                        backup.mkdir(parents=True)
                        if caption.is_file():
                            shutil.copy2(caption, backup / caption.name)
                        old.prefs.atomic_caption(caption, text)
                    jobs.append(dict(record, key=key, url=entry['url'], entry_sha256=old.batch.digest(entry),
                                     caption_text=text, caption_sha256=old.batch.file_hash(caption),
                                     video_size=record['size'], publication_content_sha256=content['sha256']))
                except Exception as error:
                    issues.append(dict(record, reason=str(error).split('\n', 1)[0]))
                    print('此个人号未选入，继续其他目标：', account, str(error).split('\n', 1)[0], flush=True)
        # The failed Pages retain their exact source jobs and content revision.
        payload = dict(failed['payload'], jobs=jobs, repair_schema=SCHEMA,
                       failed_recovery_sha256=failed['sha256'], failed_recovery_manifest=failed_path.name,
                       start=datetime.now(timezone.utc).astimezone(old.batch.BJ).isoformat())
        if any(j['publication_content_sha256'] != payload['publication_content_sha256'] for j in jobs):
            raise ValueError('补发正文版本不一致，未混用新旧文案。')
        checksum = old.batch.digest(payload)
        path = upload.ROOT / 'logs' / ('frozen-material-' + old.RUN_DATE + '-' + checksum[:16] + '.json')
        value = dict(failed, payload=payload, sha256=checksum, issues=issues, created_at=datetime.now(timezone.utc).isoformat())
        validate(path, value, parent, failed)
        upload.save_json(path, value)
        upload.save_json(pointer, dict(schema=SCHEMA, manifest=path.name, sha256=checksum))
        return path, value


def execute():
    with identity.scoped(old.PAIRS), patch.object(old, 'prepare', side_effect=prepare), patch.object(old, 'validate', side_effect=validate):
        return old.execute()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    try:
        if upload.ROOT.resolve() != Path(sys.argv[1]).resolve() or '--real-footage' not in sys.argv[2:]:
            raise ValueError('需使用原上传目录及已确认的昨日实拍设置。')
        with (upload.ROOT / 'logs/nov11-identity-repair-20261112.log').open('a', encoding='utf-8') as log:
            with contextlib.redirect_stdout(old.batch.Tee(sys.stdout, log)), contextlib.redirect_stderr(old.batch.Tee(sys.stderr, log)):
                raise SystemExit(execute())
    except KeyboardInterrupt:
        print('已停止，所有原记录保留；重跑同一命令仅继续本次冻结补发。', flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', str(error) or type(error).__name__, flush=True)
        raise SystemExit(1)
