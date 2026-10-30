"""One exact retry of current videos the user has freshly verified absent on Facebook."""
import argparse
import copy
import re
import shutil
import sys
from datetime import datetime

import fb_upload as upload
import resume_fourteen_round as rounds
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

ALLOWED = {'preparing', 'posting', 'needs_review', 'failed_before_post'}


def validate_record(entry, row, old):
    key = row.get('key', '')
    if not re.fullmatch(r'[a-f0-9]{64}', key) or not isinstance(old, dict):
        raise ValueError('缺少本轮确切任务记录，未选择其他视频代替。')
    if ((old.get('account'), old.get('target')) != (entry['account'], entry['target'])
            or upload.target_key(old.get('url', '')) != upload.target_key(entry['url'])):
        raise ValueError('任务账号、目标或主页链接不一致，未修改记录。')
    if old.get('status') not in ALLOWED or any(old.get(field) for field in
            ('permalink', 'success_message', 'confirmation_method', 'confirmed_at')):
        raise ValueError('任务状态不适合补发或已有成功证据，未解除限制。')
    name = str(old.get('video', '')).replace('\\', '/').rsplit('/', 1)[-1]
    upload.validate_video_filename(name)
    if name != row.get('filename'):
        raise ValueError('报告与原任务的文件名不一致。')
    return name


def select_pair(entry, state, row, old, expected_text=None):
    filename = validate_record(entry, row, old)
    selection_state = dict(state)
    selection_state.pop(row['key'], None)
    selected = upload.named_job(entry, selection_state, filename)
    common = expected_text if expected_text is not None else (upload.ROOT / 'common_caption_today.txt').read_text(encoding='utf-8-sig').strip()
    if selected is None or selected[0] != row['key'] or not common or selected[3] != common:
        raise ValueError('原视频指纹或统一文案不匹配，未选择其他素材代替。')
    return filename


def retry_one(pair, source_path, report, verified=False, confirmation_id='first-user-verification',
              direct_publication=False, close_windows=False, before_post_only=False):
    if not verified and not before_post_only:
        raise ValueError('只有本次已在 Facebook 核实对应视频不存在，才能使用 --verified-absent。')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', confirmation_id):
        raise ValueError('本次核验编号格式无效。')
    with locked():
        rows = [row for row in report['rows'] if (row.get('account'), row.get('target')) == pair]
        if len(rows) != 1:
            raise ValueError('本轮报告没有唯一匹配的目标。')
        row = rows[0]
        config = upload.read_json(upload.CONFIG, {})
        entries = [entry for entry in config.get('targets', [])
                   if (entry.get('account'), entry.get('target')) == pair]
        if len(entries) != 1:
            raise ValueError('目标配置缺失或重复。')
        entry = entries[0]
        upload.validate_entry(entry)
        expected_text=None
        preserve_caption=False
        if direct_publication:
            schema=report.get('schema')
            allowed=(schema=='fb10-pages-direct-publication-v1' and pair[0]=='fb10' and entry.get('type')=='page') or (
                schema=='other-accounts-direct-publication-v1' and re.fullmatch(r'fb(?:0[1-9]|1[0-9]|2[0-3])',pair[0])
                and pair[0] not in {'fb16','fb18','fb21'} and not (pair[0]=='fb10' and entry.get('type')=='page'))
            if (not allowed or upload.VERSION not in {'2.31','2.32','2.33','2.34','2.35','2.36','2.37','2.38','2.39','2.40','2.41'}
                    or upload.target_key(row.get('url',''))!=upload.target_key(entry['url'])
                    or report.get('ai_label') not in {'off','on'}
                    or not report.get('caption_text','').strip()):
                raise ValueError('缺少本轮公共主页直接发布的明确授权与确切来源')
            preserve_caption=schema=='other-accounts-direct-publication-v1' and pair[0]=='fb23'
            expected_text=(row.get('caption_text','') if preserve_caption else report['caption_text']).strip()
            if not expected_text:
                raise ValueError('原批次缺少此视频的确切文案，不补写或替换')
            entry=dict(entry,enabled=True,auto_switch_personal=True)
        elif not entry.get('enabled') or not entry.get('prepared_at'):
            raise ValueError('目标尚未完成准备或启用。')
        state_path = upload.ROOT / 'logs/publish_state.json'
        state = upload.read_json(state_path, {})
        key = row.get('key', '')
        claims_path = upload.ROOT / 'logs/verified-current-absence-claims.json'
        claims = upload.read_json(claims_path, {})
        claim_id = source_path.name + ':' + key + ':' + confirmation_id
        claim = claims.get(claim_id)
        if claim and claim.get('phase') == 'reserved':
            # Repair a crash between removing the old guard and creating the
            # replacement task. Never repair over a new task/intent record.
            saved = claim.get('original_record')
            validate_record(entry, row, saved)
            if key not in state or state[key] == saved:
                if key not in state:
                    state[key] = copy.deepcopy(saved)
                    upload.save_json(state_path, state)
                claim['phase'] = 'not_started'
                upload.save_json(claims_path, claims)
            else:
                print('此视频已按上次确认建立新任务；保留新结果，需重新核对 Facebook：', '/'.join(pair), flush=True)
                return False
        if claim and claim.get('phase') not in {'not_started'}:
            current_status=state.get(key,{}).get('status','missing')
            print('本次重试许可已使用；当前记录状态：',current_status,'；不重复提交：', '/'.join(pair), flush=True)
            return False
        old = state.get(key)
        if old and old.get('status') == 'published':
            print('本轮此视频已记录成功，未重发：', '/'.join(pair), flush=True)
            return False
        if before_post_only and (not isinstance(old,dict) or old.get('status')!='failed_before_post'):
            raise ValueError('只允许原记录明确在 Post 前失败的任务；未知结果不重试')
        filename = select_pair(entry, state, row, old,expected_text)
        def validate_direct(current):
            if direct_publication:
                common=(upload.ROOT/'common_caption_today.txt').read_text(encoding='utf-8-sig').strip() if not preserve_caption else None
                if not preserve_caption and common!=report['caption_text'].strip():
                    raise ValueError('统一文案与原发布批次不同，未补发')
                if any(other_key!=key and (record.get('account'),record.get('target'))==pair
                       and record.get('status') in {'preparing','posting','needs_review'}
                       for other_key,record in current.items()):
                    raise ValueError('此主页还有另一条待核实任务，未解除任何限制')
                if old.get('ai_label_requested') is not (report['ai_label']=='on'):
                    raise ValueError('原任务 AI 设置与原批次不一致，未补发')
        validate_direct(state)
        # Existing live worker/profile/login failures must leave the original
        # uncertain record intact. The upload lock is held for this check.
        if close_windows:
            close_selected_window(pair[0])
        upload.check_identity(entry)
        actual = upload.read_json(state_path, {})
        if actual.get(key) != old:
            raise ValueError('身份核验期间任务记录变化，未解除原限制。')
        filename = select_pair(entry, actual, row, old,expected_text)
        validate_direct(actual)
        backup = upload.ROOT / 'backups' / ('verified-current-absent-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True, exist_ok=False)
        shutil.copy2(state_path, backup / state_path.name)
        upload.save_json(backup / 'assertion.json', dict(assertion='ledger_failure_before_post' if before_post_only else 'user_freshly_verified_current_video_absent',
            account=pair[0], target=pair[1], key=key, filename=filename, source_report=str(source_path), original_record=old))
        if claims_path.is_file():
            shutil.copy2(claims_path, backup / claims_path.name)
        claim = dict(phase='reserved', asserted_at=datetime.now().astimezone().isoformat(),
                     original_record=copy.deepcopy(old), backup=str(backup))
        claims[claim_id] = claim
        upload.save_json(claims_path, claims)
        replacement = copy.deepcopy(actual)
        del replacement[key]
        try:
            upload.save_json(state_path, replacement)
        except Exception:
            shutil.copy2(backup / state_path.name, state_path)
            claim['phase'] = 'not_started'
            upload.save_json(claims_path, claims)
            raise
        print('只重试原记录明确在 Post 前失败的视频：' if before_post_only else '只补发已核实不存在的原视频：',
              '/'.join(pair), filename, key[:12], flush=True)
        try:
            return upload.run_entry(entry, replacement, state_path, True, filename=filename,
                                    ai_label_override=report['ai_label'] == 'on',
                                    new_video_with_old_review=not direct_publication, expected_job_key=key)
        finally:
            current = upload.read_json(state_path, {})
            if key not in current:
                current[key] = old
                upload.save_json(state_path, current)
                claim['phase'] = 'not_started'
                print('未建立新任务，原记录已恢复。', flush=True)
            else:
                claim.update(phase='consumed', new_video_status=current[key].get('status'),
                             completed_at=datetime.now().astimezone().isoformat())
            upload.save_json(claims_path, claims)


def run(targets, verified=False, confirmation_id='first-user-verification', round_start=None):
    if not verified:
        raise ValueError('请先核实所选视频未发布，再使用 --verified-absent。')
    if not targets or len(set(targets)) != len(targets):
        raise ValueError('请指定不重复的账号/目标。')
    with locked():
        path, report = rounds.load_round()
        if round_start is not None and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', round_start)
                or report.get('created', '')[:19] != round_start):
            raise ValueError('最近实际发布批次与本次核验指定的批次不同，未将旧核验用于另一轮视频。')
        scope = {(row['account'], row['target']) for row in report['rows']}
        if any(pair not in scope for pair in targets):
            raise ValueError('指定目标不在本轮报告中。')
    report.setdefault('resume_results', [])
    for pair in targets:
        row = next(row for row in report['rows'] if (row['account'], row['target']) == pair)
        result = dict(account=pair[0], target=pair[1], key=row['key'], filename=row['filename'],
                      attempted_at=datetime.now().astimezone().isoformat(), user_verified_absent=True)
        try:
            done = retry_one(pair, path, report, True, confirmation_id=confirmation_id)
            result['attempt'] = 'finished_or_recorded' if done is not False else 'skipped'
        except upload.ReceiptNeedsReview as error:
            result.update(attempt='needs_review', error=str(error))
            print('补发结果仍待核对，保留新记录，继续下一个：', error, flush=True)
        except Exception as error:
            result.update(attempt='stopped', error=str(error))
            print('此目标停止，保留记录，继续下一个：', '/'.join(pair), error, flush=True)
        report['resume_results'].append(result)
        rounds.save_results(path, report)
    actual = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
    for pair in targets:
        row = next(row for row in report['rows'] if (row['account'], row['target']) == pair)
        print('/'.join(pair), row['filename'], actual.get(row['key'], {}).get('status', 'missing'), flush=True)
    print('已更新原本轮汇总：', path.with_suffix('.csv'))
    print('重复运行不会再次使用本次旧的“未发布”核对结果；新结果未知需重新检查 Facebook。')
    return 0 if all(actual.get(row['key'], {}).get('status') == 'published'
                    for row in report['rows'] if (row['account'], row['target']) in targets) else 3


def main():
    parser = argparse.ArgumentParser(description='按确切本轮任务补发用户本次已核实不存在的视频')
    parser.add_argument('--targets', required=True)
    parser.add_argument('--verified-absent', action='store_true')
    parser.add_argument('--round-start', required=True, help='已核验发布报告的原始开始时间（精确到秒），避免旧命令用于新一轮素材')
    parser.add_argument('--confirmation-id', default='first-user-verification',
                        help='固定的本次人工核验编号；仅重新核对 Facebook 后才能更换，不要自动生成')
    args = parser.parse_args()
    targets = [tuple(value.strip().split('/')) for value in args.targets.split(',')]
    if any(len(pair) != 2 or any(not re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in pair) for pair in targets):
        raise ValueError('目标格式例如 fb03/personal,fb06/page01。')
    return run(targets, args.verified_absent, args.confirmation_id, args.round_start)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('已中断，保留事务记录；先核对实际结果。')
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
