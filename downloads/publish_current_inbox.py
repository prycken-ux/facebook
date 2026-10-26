"""Publish one unrecorded current inbox video without resetting older reviews."""
import argparse
import re
import shutil
import sys
from datetime import datetime

import fb_upload as upload
from add_fb_accounts import locked


def publish_current(account, target='personal', ai_label='off', retry_before_post=False, expected_key=None,
                    pause_before_reel=False):
    if ai_label not in ('off', 'on'):
        raise ValueError('AI 标签必须为 on 或 off。')
    if expected_key is not None and not re.fullmatch(r'[a-f0-9]{64}', expected_key):
        raise ValueError('指定素材任务指纹格式无效。')
    with locked():
        config = upload.read_json(upload.CONFIG, {'targets': []})
        matches = [row for row in config['targets']
                   if (row.get('account'), row.get('target')) == (account, target)]
        if len(matches) != 1:
            raise ValueError('没有唯一的账号/目标配置。')
        entry = matches[0]
        upload.validate_entry(entry)
        if not entry.get('prepared_at') or not entry.get('enabled'):
            raise ValueError('该目标尚未准备或启用。')
        state_path = upload.ROOT / 'logs/publish_state.json'
        state = upload.read_json(state_path, {})
        folder = upload.inbox_for(entry)
        candidates = []
        for video in sorted(folder.iterdir(), key=upload.queue_order):
            if not video.is_file() or video.suffix.lower() != '.mp4':
                continue
            video.resolve().relative_to(folder.resolve())
            if not video.stat().st_size:
                continue
            if video.name.lower() in {name.lower() for name in entry.get('excluded_files', [])}:
                continue
            key = upload.job_key(entry, video)
            if key in state:
                row = state[key]
                if retry_before_post and row.get('status') == 'failed_before_post':
                    if ((row.get('account'), row.get('target')) != (account, target)
                            or upload.target_key(row.get('url', '')) != upload.target_key(entry['url'])
                            or any(row.get(field) for field in ('permalink', 'success_message', 'confirmation_method'))):
                        raise ValueError('发布前失败记录与当前素材冲突或含成功证据，未重试。')
                    candidates.append((video, key, row))
                else:
                    print('当前素材已有记录，未重发：', video.name, row.get('status'), flush=True)
                continue
            candidates.append((video, key, None))
        if not candidates:
            print('当前 inbox 没有尚未记录的新视频，未发布：', account, target)
            return False
        if expected_key is not None:
            matched=[candidate for candidate in candidates if candidate[1]==expected_key]
            if not matched:
                raise ValueError('当前素材与刚才核对的内容不同，未选择其他视频代替。')
            candidates=matched
        if len(candidates) != 1:
            raise ValueError('当前 inbox 有多条新视频，未自动猜选，请先明确本轮素材。')
        video, key, failed_row = candidates[0]
        if expected_key is not None and key != expected_key:
            raise ValueError('当前素材与刚才核对的内容不同，未选择其他视频代替。')
        validation_state = dict(state)
        if failed_row is not None:
            del validation_state[key]
        selected = upload.named_job(entry, validation_state, video.name)
        if selected is not None and selected[0] != key:
            raise ValueError('核对期间当前视频内容变化，未发布。')
        caption_path = upload.ROOT / 'common_caption_today.txt'
        common = caption_path.read_text(encoding='utf-8-sig').strip()
        if not common or selected is None or selected[3] != common:
            raise ValueError('当前同名 TXT 与已保存统一文案不一致，请先套用本轮文案。')
        print('本轮当前素材：', account, target, video.name, '；AI 标签：', ai_label, flush=True)
        backup = upload.ROOT / 'backups' / ('publish-current-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True, exist_ok=False)
        if state_path.exists():
            shutil.copy2(state_path, backup / state_path.name)
        if failed_row is not None:
            upload.save_json(backup / 'before-post-retry.json', {
                'reason': 'recorded_failure_before_post_click', 'job': key, 'original_record': failed_row})
            del state[key]
            try:
                upload.save_json(state_path, state)
            except Exception:
                shutil.copy2(backup / state_path.name, state_path)
                raise
            print('原记录明确为发布前失败，已备份，重新处理当前同一素材：', video.name, flush=True)
        try:
            assistance={'pause_before_reel':True} if pause_before_reel else {}
            return upload.run_entry(entry, state, state_path, True, filename=video.name,
                                    ai_label_override=ai_label == 'on', new_video_with_old_review=True,
                                    expected_job_key=key,**assistance)
        finally:
            if failed_row is not None:
                actual = upload.read_json(state_path, {})
                if key not in actual:
                    actual[key] = failed_row
                    upload.save_json(state_path, actual)
                    print('未建立新任务，原发布前失败记录已恢复。')


def main():
    parser = argparse.ArgumentParser(description='发布 inbox 中唯一未记录的新素材，保留旧待核对任务')
    parser.add_argument('--account', required=True)
    parser.add_argument('--target', default='personal')
    parser.add_argument('--ai-label', choices=['off', 'on'], default='off')
    parser.add_argument('--retry-before-post', action='store_true', help='只重试明确在点击发布前失败的当前素材')
    parser.add_argument('--expected-job', help='必须与核对时的完整素材内容指纹一致')
    args = parser.parse_args()
    try:
        publish_current(args.account, args.target, args.ai_label,
                        retry_before_post=args.retry_before_post, expected_key=args.expected_job)
        return 0
    except upload.ReceiptNeedsReview as error:
        print('REVIEW：', error)
        print('新素材本次结果仍需核对，保留新旧记录，未再次尝试。')
        return 3
    except Exception as error:
        print('STOP：', error)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
