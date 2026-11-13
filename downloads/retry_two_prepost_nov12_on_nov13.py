"""One new video-only grant for the two explicit pre-Post failures in the last report."""
import copy
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

if __name__ == '__main__':
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import retry_named_nov12_on_nov13 as base

DAY = '2026-11-13'
PARENT_GRANT = 'nov12-fifteen-user-confirmed-absent-video-only-20261113-v1'
PARENT_PREFIX = '024ae954'
GRANT = 'nov12-donna-cyrus-prepost-video-only-extra-once-20261113-v1'
SPEC = {
    ('fb02', 'page01'): ('1111(1)-2.mp4', 'Donna Merrill', ''),
    ('fb23', 'personal'): ('1111-3.mp4', 'Cyrus Marlene', 'c39afc3832d8'),
}
POST_FIELDS = base.SUCCESS_FIELDS + ('post_intent_at',)
SOURCE = base.source
CHECKED = base.checked
RUN = base.execute


def require_day():
    if datetime.now(timezone.utc).astimezone(base.batch.BJ).date().isoformat() != DAY:
        raise ValueError('本指令仅限11月13日补发Donna Merrill和Cyrus Marlene两条发布前失败原视频。')


def has_submission(row):
    if isinstance(row, list):
        return any(has_submission(value) for value in row)
    if not isinstance(row, dict):
        return False
    return row.get('status') in {'published', 'posting'} or any(row.get(k) for k in POST_FIELDS) or any(
        has_submission(value) for value in row.values() if isinstance(value, (dict, list)))


def source():
    pointer = base.upload.read_json(base.upload.ROOT/'logs'/(PARENT_GRANT+'.json'), {})
    name = pointer.get('manifest', '')
    if not re.fullmatch('frozen-material-'+DAY+'-'+PARENT_PREFIX+r'[a-f0-9]{8}\.json', name):
        raise ValueError('没有找到刚才024ae954这批原失败清单，未改选其他批次。')
    path = base.upload.ROOT/'logs'/name
    parent = base.upload.read_json(path, {})
    base.workflow.validate(path, parent)
    payload = parent['payload']
    if (pointer.get('sha256') != parent['sha256'] or payload.get('named_absent_grant') != PARENT_GRANT
            or payload.get('comment_policy') != 'do_not_send'):
        raise ValueError('原失败批次的指纹或仅视频规则不一致。')
    jobs, labels, issues, origin, template = SOURCE()
    if issues or len(jobs) != 2 or {(j['account'], j['target']) for j in jobs} != set(SPEC):
        raise ValueError('两个指定失败账号未能唯一匹配原视频：'+str(issues))
    for job in jobs:
        pair = job['account'], job['target']
        filename, expected_name, prefix = SPEC[pair]
        originals = [j for j in payload['jobs'] if (j.get('account'), j.get('target')) == pair]
        if (len(originals) != 1 or originals[0] != job or job['filename'] != filename
                or labels.get(job['key']) != expected_name or not job['key'].startswith(prefix)
                or payload.get('selected_names', {}).get(job['key']) != expected_name):
            raise ValueError('账号、原文件、任务指纹或名称与刚才的失败记录不一致。')
    origin = copy.deepcopy(origin)
    origin['explicit_prepost_failure_parent'] = dict(manifest=name, sha256=parent['sha256'], grant=PARENT_GRANT)
    return jobs, labels, issues, origin, template


def checked(job, state, claims):
    entry, status = CHECKED(job, state, claims)
    if status != 'ready':
        return entry, status
    row = state.get(job['key'])
    if (not isinstance(row, dict) or row.get('status') != 'failed_before_post'
            or has_submission(row) or row.get('uploader_version') != '2.47'
            or row.get('ai_label_requested') is not False):
        raise ValueError('仅允许明确发布前失败；已有提交线索、待核实或没有原任务的素材不重发。')
    return entry, status


def execute():
    require_day()
    with patch.object(base, 'GRANT', GRANT), patch.object(base, 'NAMES', tuple(v[1] for v in SPEC.values())), \
            patch.object(base, 'source', side_effect=source), patch.object(base, 'checked', side_effect=checked), \
            patch.object(base, 'require_day', side_effect=require_day):
        print('本次只再尝试Donna Merrill（fb02/page01）和Cyrus Marlene（fb23/personal）的两条发布前失败原视频，各一次；不发送评论。', flush=True)
        return RUN()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    try:
        if base.upload.ROOT.resolve() != Path(sys.argv[1]).resolve():
            raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:
        print('已暂停；保留两条视频的已有进度，重跑同一命令继续。', flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', str(error) or type(error).__name__, flush=True)
        raise SystemExit(1)
