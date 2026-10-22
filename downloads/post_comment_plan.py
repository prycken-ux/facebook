"""Freeze per-video product comments for future posts; no browser or comment sender."""
import argparse
import hashlib
import sys
import time
from datetime import datetime

import fb_upload as upload
from add_fb_accounts import locked

SCHEMA = 'per-video-post-comment-v1'


def configure(enabled=True):
    with locked():
        config = upload.read_json(upload.CONFIG, {})
        entries = config.get('targets', [])
        if not entries:
            raise ValueError('没有发布目标，未启用。')
        identities = set()
        targets = []
        for entry in entries:
            upload.validate_entry(entry)
            pair = (entry['account'], entry['target'])
            if pair in identities:
                raise ValueError('发布目标重复，未启用。')
            identities.add(pair)
            targets.append(dict(account=pair[0], target=pair[1], url=entry['url']))
        path = upload.ROOT / 'post_comment_config.json'
        previous = upload.read_json(path, None)
        if previous:
            backup = upload.ROOT / 'backups' / ('post-comment-config-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            upload.save_json(backup / path.name, previous)
        settings = dict(schema=SCHEMA, enabled=enabled, future_only=True,
                        activated_at=datetime.now().astimezone().isoformat(), targets=targets,
                        comment_filename='{video_stem}.comment.txt',
                        stage='awaiting_top_level_comment_ui_adaptation', automatic_send_enabled=False)
        upload.save_json(path, settings)
        print('后续视频评论文案绑定：', '已启用' if enabled else '已停用')
        print('发布目标：', len(targets), '；现有已发布视频不补评论。')
        print('自动发送尚未启用；需先完成公共主页和个人主页评论区适配。')
        return settings


def build_plan(entry, video, key):
    """Called only when selecting a new publication; never backfills existing rows."""
    settings = upload.read_json(upload.ROOT / 'post_comment_config.json', None)
    if not settings or not settings.get('enabled'):
        return None
    if settings.get('schema') != SCHEMA or settings.get('future_only') is not True:
        raise ValueError('视频评论配置版本不匹配，请重新配置。')
    matches = [row for row in settings.get('targets', [])
               if (row.get('account'), row.get('target')) == (entry['account'], entry['target'])]
    if not matches:
        return None
    if len(matches) != 1 or upload.target_key(matches[0]['url']) != upload.target_key(entry['url']):
        raise ValueError('视频评论配置目标已变化，请核对后重新配置。')
    path = video.with_suffix('.comment.txt')
    if not path.exists():
        return None
    before = path.stat()
    if before.st_size > 65536:
        raise ValueError('评论 TXT 超过 64KB，请检查文件。')
    text = path.read_text(encoding='utf-8-sig').strip()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('评论文案正在保存，请稍后再试。')
    if not text:
        return None
    if time.time() - after.st_mtime < 60:
        raise ValueError('评论文案刚保存，请等待一分钟后再发布。')
    if len(text) > 5000 or any(ord(c) < 32 and c not in '\r\n\t' for c in text):
        raise ValueError('评论文案过长或含控制字符，请检查。')
    return dict(schema=SCHEMA, video_job=key, account=entry['account'], target=entry['target'],
                target_url=entry['url'], text=text, text_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                source=str(path), planned_at=datetime.now().astimezone().isoformat(),
                status='waiting_for_video_publication', automatic_send_enabled=False)


def status():
    with locked():
        state = upload.read_json(upload.ROOT / 'logs/publish_state.json', {})
        rows = []
        for key, record in state.items():
            plan = record.get('post_comment_plan')
            if not plan:
                continue
            if (plan.get('schema') != SCHEMA or plan.get('video_job') != key
                    or (plan.get('account'), plan.get('target')) != (record.get('account'), record.get('target'))
                    or upload.target_key(plan.get('target_url', '')) != upload.target_key(record.get('url', ''))
                    or hashlib.sha256(plan['text'].encode('utf-8')).hexdigest() != plan.get('text_sha256')):
                raise ValueError('评论计划与原发布任务不一致，未生成队列。')
            video_status = record.get('status')
            phase = ('waiting_for_comment_ui_and_verified_video_link' if video_status == 'published' else
                     'waiting_for_video_confirmation' if video_status in {'needs_review', 'posting', 'preparing'} else
                     'video_not_published')
            rows.append(dict(job=key, account=record['account'], target=record['target'],
                             video=record['video'], video_status=video_status, status=phase,
                             text=plan['text'], text_sha256=plan['text_sha256']))
        path = upload.ROOT / 'logs/post-comment-queue.json'
        upload.save_json(path, dict(created=datetime.now().astimezone().isoformat(),
                                   automatic_send_enabled=False, rows=rows))
        for row in rows:
            print(row['account'] + '/' + row['target'], row['status'], row['job'][:12])
        print('后续视频的评论计划：', len(rows), '条；历史视频未加入。')
        print('评论待办：', path)
        print('本阶段只绑定文案；自动发送仍需完成评论区和视频链接适配。')
        return rows


def main():
    parser = argparse.ArgumentParser(description='为以后发布的视频绑定产品评论文案；本工具不发送评论')
    parser.add_argument('action', choices=['enable-future', 'disable', 'status'])
    args = parser.parse_args()
    if args.action == 'status':
        status()
    else:
        configure(args.action == 'enable-future')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：', error)
        raise SystemExit(1)
