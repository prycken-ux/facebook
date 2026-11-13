"""Mark four user-confirmed successes; preserve five logged successes and all comments."""
import copy
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
from add_fb_accounts import locked

METHOD = 'user_confirmed_nov12_four_personals_20261113'
PERSONALS = {
    ('fb16', 'personal'): ('2026-05-20_7641888881230482702.mp4', 'PJ Elliott'),
    ('fb17', 'personal'): ('2026-05-20_7641915762092952845.mp4', 'Kevin Cuneo'),
    ('fb18', 'personal'): ('2026-05-21_7642264438749416717.mp4', 'Cara Doxtator'),
    ('fb21', 'personal'): ('2026-05-25_7643761018920865037.mp4', 'Ken Harp'),
}
PAGES = {
    ('fb10', 'page01'): ('02_分享多却没成交.mp4', 'Thockspiwem Thimbrojospo'),
    ('fb10', 'page02'): ('02_创作者卖家还是直播.mp4', 'Drascreflo Chajundfro'),
    ('fb10', 'page09'): ('02_发完视频看哪个指标.mp4', 'Hacrasnite Hacaldcirtsle'),
    ('fb10', 'page10'): ('01_LIVE开场.mp4', 'Swackgespa Roltceblu'),
    ('fb12', 'page01'): ('2026-05-14_7639697997999262990.mp4', 'Prycken June'),
}
PAGE_GRANT = 'nov12-fifteen-user-confirmed-absent-video-only-20261113-v1'
SOURCES = (
    ('nov12-five-personals-on-nov13.json', '3177b03c', PERSONALS, 'continuation_scope', 'nov13-explicit-five-nov12-personal-videos-v1'),
    (PAGE_GRANT+'.json', '024ae954', PAGES, 'named_absent_grant', PAGE_GRANT),
)


def sources():
    result = []
    for pointer_name, prefix, spec, scope_field, scope in SOURCES:
        pointer = upload.read_json(upload.ROOT/'logs'/pointer_name, {})
        name = pointer.get('manifest', '')
        if not re.fullmatch('frozen-material-2026-11-13-'+prefix+r'[a-f0-9]{8}\.json', name):
            raise ValueError('未找到已确认的原批次，未选择其他素材：'+prefix)
        path = upload.ROOT/'logs'/name
        value = upload.read_json(path, {})
        payload = value.get('payload', {})
        checksum = batch.digest(payload)
        if (value.get('sha256') != checksum or pointer.get('sha256') != checksum
                or not checksum.startswith(prefix) or payload.get('schema') != batch.SCHEMA
                or payload.get('date') != '2026-11-13' or payload.get(scope_field) != scope):
            raise ValueError('原成功任务清单校验失败，未修改记录。')
        for pair, (filename, label) in spec.items():
            jobs = [j for j in payload.get('jobs', []) if (j.get('account'), j.get('target')) == pair]
            if (len(jobs) != 1 or jobs[0].get('filename') != filename
                    or not re.fullmatch(r'[a-f0-9]{64}', str(jobs[0].get('key', '')))):
                raise ValueError('已确认账号没有唯一对应的原视频：'+str(pair))
            job = jobs[0]
            if pair in PAGES and payload.get('selected_names', {}).get(job['key']) != label:
                raise ValueError('主页名称与原成功清单不一致。')
            result.append((path, job, label, pair in PERSONALS))
    if len({job['key'] for _, job, _, _ in result}) != 9:
        raise ValueError('九个成功目标的任务指纹重复。')
    return result


def execute():
    state_path = upload.ROOT/'logs/publish_state.json'
    with locked():
        selected = sources()
        original = upload.read_json(state_path, {})
        changes = []
        for source, job, label, user_confirmed in selected:
            row = original.get(job['key'])
            if (not isinstance(row, dict) or (row.get('account'), row.get('target')) != (job['account'], job['target'])
                    or upload.target_key(row.get('url', '')) != upload.target_key(job['url'])
                    or str(row.get('video', '')).replace('\\', '/').split('/')[-1] != job['filename']):
                raise ValueError('原视频任务记录缺失或身份不一致：'+label)
            if row.get('status') == 'published':
                continue
            if (not user_confirmed or row.get('status') != 'needs_review'
                    or row.get('review_reason') != 'publication_receipt_timeout' or not row.get('post_intent_at')):
                raise ValueError('最新状态与已确认结果不一致，未覆盖：'+label+' '+str(row.get('status')))
            changes.append(dict(key=job['key'], source_manifest=source.name, name=label, previous_record=copy.deepcopy(row)))
        now = datetime.now(timezone.utc).isoformat()
        backup = None
        if changes:
            backup = upload.ROOT/'backups'/(METHOD+'-'+uuid.uuid4().hex[:12])
            backup.mkdir(parents=True)
            shutil.copy2(state_path, backup/state_path.name)
            upload.save_json(backup/'confirmation-audit.json', dict(method=METHOD, confirmed_at=now, changes=changes))
            state = copy.deepcopy(original)
            for item in changes:
                row = state[item['key']]
                row.update(status='published', status_before_user_confirmation=row['status'],
                           confirmation_method=METHOD, confirmed_at=now, confirmed_source_manifest=item['source_manifest'],
                           error_before_user_confirmation=row.get('error', ''), review_reason_before_user_confirmation=row.get('review_reason', ''),
                           error='', review_reason='')
            if upload.read_json(state_path, {}) != original:
                raise ValueError('标记前发布记录发生变化，未覆盖。')
            upload.save_json(state_path, state)
        print('这批视频已标记/保留发布成功，共9个发布目标：', flush=True)
        for _, job, label, _ in selected:
            print(job['account']+'/'+job['target'], label, '发布成功', flush=True)
        print('本次补记：', len(changes), '条；原有成功：', 9-len(changes), '条。', flush=True)
        if backup:
            print('标记前记录及逐条核实依据已备份：', backup, flush=True)
        print('仅更新这些原视频的发布状态；没有上传视频、打开浏览器或发送评论，评论记录未改动。', flush=True)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    try:
        if upload.ROOT.resolve() != Path(sys.argv[1]).resolve():
            raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except Exception as error:
        print('STOP：', str(error) or type(error).__name__, flush=True)
        raise SystemExit(1)
