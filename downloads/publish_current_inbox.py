"""Publish one unrecorded current inbox video without resetting older reviews."""
import argparse
import shutil
import sys
from datetime import datetime

import fb_upload as upload
from add_fb_accounts import locked


def publish_current(account, target='personal', ai_label='off'):
    if ai_label not in ('off', 'on'):
        raise ValueError('AI 标签必须为 on 或 off。')
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
                print('当前素材已有记录，未重发：', video.name, state[key].get('status'), flush=True)
                continue
            candidates.append(video)
        if not candidates:
            print('当前 inbox 没有尚未记录的新视频，未发布：', account, target)
            return False
        if len(candidates) != 1:
            raise ValueError('当前 inbox 有多条新视频，未自动猜选，请先明确本轮素材。')
        video = candidates[0]
        selected = upload.named_job(entry, state, video.name)
        caption_path = upload.ROOT / 'common_caption_today.txt'
        common = caption_path.read_text(encoding='utf-8-sig').strip()
        if not common or selected is None or selected[3] != common:
            raise ValueError('当前同名 TXT 与已保存统一文案不一致，请先套用本轮文案。')
        print('本轮当前素材：', account, target, video.name, '；AI 标签：', ai_label, flush=True)
        backup = upload.ROOT / 'backups' / ('publish-current-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True, exist_ok=False)
        if state_path.exists():
            shutil.copy2(state_path, backup / state_path.name)
        return upload.run_entry(entry, state, state_path, True, filename=video.name,
                                ai_label_override=ai_label == 'on', new_video_with_old_review=True)


def main():
    parser = argparse.ArgumentParser(description='发布 inbox 中唯一未记录的新素材，保留旧待核对任务')
    parser.add_argument('--account', required=True)
    parser.add_argument('--target', default='personal')
    parser.add_argument('--ai-label', choices=['off', 'on'], default='off')
    args = parser.parse_args()
    try:
        publish_current(args.account, args.target, args.ai_label)
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
