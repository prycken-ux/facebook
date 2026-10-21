"""Retry one exact user-verified absent pending video, preserving all other jobs."""
import argparse
import copy
import shutil
import sys
from datetime import datetime

import fb_upload as upload
from add_fb_accounts import locked


def retry_absent(account, target='personal', verified_absent=False, ai_label='off'):
    if not verified_absent:
        raise ValueError('只有用户已确认该视频未发布时才能使用 --verified-absent。')
    if ai_label not in ('on', 'off'):
        raise ValueError('AI 标签必须为 on 或 off。')
    with locked():
        config = upload.read_json(upload.CONFIG, {'targets': []})
        entries = [entry for entry in config['targets']
                   if (entry.get('account'), entry.get('target')) == (account, target)]
        if len(entries) != 1:
            raise ValueError('没有唯一的账号/目标配置，未修改记录。')
        entry = entries[0]
        upload.validate_entry(entry)
        if not entry.get('prepared_at') or not entry.get('enabled'):
            raise ValueError('该目标尚未完成准备或启用，未修改记录。')
        state_path = upload.ROOT / 'logs/publish_state.json'
        original = upload.read_json(state_path, {})
        pending = [(key, row) for key, row in original.items()
                   if (row.get('account'), row.get('target')) == (account, target)
                   and row.get('status') in {'preparing', 'posting', 'needs_review'}]
        if not pending:
            print('没有待核对任务，未补发：', account, target)
            return False
        if len(pending) != 1 or pending[0][1].get('status') != 'needs_review':
            raise ValueError('没有唯一的待核对任务，或存在进行中的任务，未修改记录。')
        key, old = pending[0]
        if old.get('permalink') or old.get('success_message'):
            raise ValueError('该记录已有成功回执或链接，未解除限制。')
        if upload.target_key(old.get('url', '')) != upload.target_key(entry['url']):
            raise ValueError('当前目标与原任务主页不同，未修改记录。')
        state = copy.deepcopy(original)
        del state[key]
        filename = str(old.get('video', '')).replace('\\', '/').rsplit('/', 1)[-1]
        selected = upload.named_job(entry, state, filename)
        if selected is None or selected[0] != key:
            raise ValueError('视频内容指纹与原任务不一致，未修改记录。')
        print('本次补发：', account, target, filename, key[:12], flush=True)
        # Check the live login before clearing anything; a locked profile or an
        # expired login must leave the uncertain record intact.
        upload.check_identity(entry)
        # Revalidate the complete pair after the browser check.
        selected = upload.named_job(entry, state, filename)
        if selected is None or selected[0] != key:
            raise ValueError('核对期间视频发生变化，未修改记录。')
        backup = upload.ROOT / 'backups' / ('verified-absent-retry-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True, exist_ok=False)
        shutil.copy2(state_path, backup / state_path.name)
        upload.save_json(backup / 'assertion.json', {
            'assertion': 'user_verified_absent', 'account': account, 'target': target,
            'job': key, 'filename': filename, 'original_record': old,
        })
        try:
            upload.save_json(state_path, state)
        except Exception:
            shutil.copy2(backup / state_path.name, state_path)
            raise
        print('原任务已备份，按原文件名补发一次：', backup, flush=True)
        try:
            return upload.run_entry(entry, state, state_path, True, filename=filename,
                                    ai_label_override=ai_label == 'on')
        finally:
            # A browser launch or early validation failure can occur before a
            # replacement task exists. Restore the old guard in that case.
            current = upload.read_json(state_path, {})
            if key not in current:
                current[key] = old
                upload.save_json(state_path, current)
                print('未建立新发布任务，原待核对记录已恢复。', flush=True)


def main():
    parser = argparse.ArgumentParser(description='只补发用户已确认未发布的唯一待核对视频')
    parser.add_argument('--account', required=True)
    parser.add_argument('--target', default='personal')
    parser.add_argument('--verified-absent', action='store_true')
    parser.add_argument('--ai-label', choices=['on', 'off'], default='off')
    args = parser.parse_args()
    try:
        retry_absent(args.account, args.target, args.verified_absent, args.ai_label)
        return 0
    except upload.ReceiptNeedsReview as error:
        print('REVIEW：', error)
        print('本次补发仍需核对，请检查 Facebook 和 review 截图，勿直接重复运行。')
        return 3
    except Exception as error:
        print('STOP：', error)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
