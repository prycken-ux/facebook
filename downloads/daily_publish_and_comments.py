"""Reconcile the confirmed Oct-29 batch, comment without reupload, then new Oct-30 media."""
import argparse
import copy
import contextlib
import csv
import json
import re
import shutil
import sys
import time
import zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path

import fb_upload as upload
import scheduled_material_batch as batch
import safe_video_comments as comments
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window
from published_video_lookup import find_published

OLD_DATE='2026-10-29'
TODAY='2026-10-30'
COMMENT='Get your own copy:\nhttps://www.amazon.com/s?maas=maas_adg_B87EF70D0CB3092D4D7277407B28F038_afap_abs&ref_=aa_maas&tag=maas&me=AEFRCMPTGXRXD&marketplaceID=ATVPDKIKX0DER'
EXCLUDED={'fb16','fb18','fb21'}
EXPECTED_PAIRS={(f'fb{n:02}','page01') for n in (1,2,5,6,12,13)} | {
    (f'fb{n:02}','personal') for n in (3,4,7,8,9,10,11,14,15,17,19,20,22,23)} | {
    ('fb10',f'page{n:02}') for n in range(1,11)}


def load_unique(date,required=True,expected_prefix=None):
    values=[]
    for path in (upload.ROOT/'logs').glob('frozen-material-'+date+'-*.json'):
        if not re.fullmatch(r'frozen-material-'+date+r'-[a-f0-9]{16}\.json',path.name):continue
        if expected_prefix and not path.stem.split('-')[-1].startswith(expected_prefix):continue
        value=upload.read_json(path,{})
        payload=value.get('payload',{})
        checksum=batch.digest(payload)
        if value.get('sha256')!=checksum or not path.stem.endswith(checksum[:16]):
            raise ValueError('冻结清单指纹不匹配，未按最新文件猜选')
        if (payload.get('schema')!=batch.SCHEMA or payload.get('date')!=date
                or payload.get('include_fb10_pages') is not True or payload.get('ai_label') is not False
                or set(payload.get('excluded_accounts',[]))!=EXCLUDED):
            raise ValueError('冻结清单的账号范围或 AI 设置不匹配')
        values.append((path,value))
    if len(values)>1 or required and not values:raise ValueError('原日期没有唯一冻结清单，需手动核实')
    return values[0] if values else (None,None)


def configured(job):
    rows=[e for e in upload.read_json(upload.CONFIG,{}).get('targets',[])
          if (e.get('account'),e.get('target'))==(job['account'],job['target'])]
    if len(rows)!=1 or upload.target_key(rows[0]['url'])!=upload.target_key(job['url']):
        raise ValueError('当前目标与原冻结任务不一致')
    upload.validate_entry(rows[0]);return rows[0]


def confirm_yesterday(path,manifest):
    """Caller holds the uploader lock; all 30 were explicitly confirmed by the user."""
    jobs=manifest['payload']['jobs']
    if len(jobs)!=30 or len({j['key'] for j in jobs})!=30 or {(j['account'],j['target']) for j in jobs}!=EXPECTED_PAIRS:
        raise ValueError('原批次不是唯一的 30 个目标')
    state_path=upload.ROOT/'logs/publish_state.json';original=upload.read_json(state_path,{})
    plan=[]
    for job in jobs:
        entry=configured(job);row=original.get(job['key'])
        if (not isinstance(row,dict) or (row.get('account'),row.get('target'))!=(job['account'],job['target'])
                or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
                or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):
            raise ValueError('原任务缺失或与确切视频不一致，未批量猜记成功：'+job['account']+'/'+job['target'])
        plan.append((job,entry))
    backup=upload.ROOT/'backups'/('confirmed-oct29-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    shutil.copy2(state_path,backup/state_path.name);shutil.copy2(path,backup/path.name)
    state=copy.deepcopy(original);now=datetime.now(timezone.utc).isoformat()
    for job,entry in plan:
        row=state[job['key']]
        if row.get('status')!='published':
            row.setdefault('historical_attempts',[]).append(dict(status=row.get('status'),error=row.get('error',''),failure_stage=row.get('failure_stage','')))
            row.update(status='published',confirmation_method='user_confirmed_all_oct29_existing_posts',confirmed_at=now,error='')
        row.setdefault('published_caption_text',job['caption_text'])
        row['confirmed_frozen_manifest']=path.name
        row.setdefault('confirmed_batch_lookup_cutoff',now)
    upload.save_json(state_path,state)  # Persist the no-reupload guard before moving any file.
    archive_rows=[]
    for job,entry in plan:
        video=upload.inbox_for(entry)/job['filename'];caption=video.with_suffix('.txt')
        result='原文件已归档或不在 inbox；没有移动其他文件'
        if video.is_file() and upload.job_key(entry,video)==job['key']:
            if caption.is_file() and batch.file_hash(caption)==job['caption_sha256']:
                try:result='已归档：'+str(upload.archive(video,caption))
                except Exception as error:result='已补记成功，归档需核实：'+str(error)
            else:result='原文件文案缺失或变化，保留不移动'
        archive_rows.append(dict(account=job['account'],target=job['target'],key=job['key'],archive_result=result))
    upload.save_json(backup/'confirmation-audit.json',dict(manifest=path.name,confirmed_at=now,rows=archive_rows))
    print('昨天 30 个原视频已按你的确认补记成功；不重新上传。备份：',backup,flush=True)


def manual_links(path,jobs):
    if path is None:return {}
    allowed={j['key']:(j['account'],j['target']) for j in jobs};found={}
    with Path(path).open(encoding='utf-8-sig',newline='') as handle:
        for row in csv.DictReader(handle):
            link=row.get('permalink','').strip()
            if not link:continue
            key=row.get('key','')
            if key not in allowed or (row.get('account'),row.get('target'))!=allowed[key] or not comments.direct_link(link):
                raise ValueError('手动视频链接未对应原任务完整指纹')
            if key in found:raise ValueError('同一任务有多个手动链接')
            found[key]=comments.direct_link(link)
    return found


def write_backfill_report(manifest,rows,output_dir):
    stem='昨日补评论-'+OLD_DATE+'-'+manifest['sha256'][:8]
    path=upload.ROOT/'logs'/(stem+'.json')
    upload.save_json(path,dict(schema='confirmed-published-comments-v1',rows=rows))
    csv_path=path.with_suffix('.csv')
    with csv_path.open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['account','target','filename','key','status','permalink','error'])
        writer.writeheader();writer.writerows(rows)
    out=Path(output_dir) if output_dir else upload.ROOT/'logs'
    if not out.is_dir():out=upload.ROOT/'logs'
    with zipfile.ZipFile(out/(stem+'.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(path,'results.json');archive.write(csv_path,'results.csv')
        for row in rows:
            for suffix in ['-error.txt','.png','.aria.txt']:
                file=upload.ROOT/'logs'/('comment-'+row['key'][:12]+suffix)
                if file.is_file():archive.write(file,file.name)
    print('昨日补评论结果：',out/(stem+'.zip'),flush=True)


def backfill(manifest,output_dir,links_path=None,only_keys=None,rows=None,already_locked=False):
    from playwright.sync_api import sync_playwright
    jobs=manifest['payload']['jobs'];links=manual_links(links_path,jobs)
    state_path=upload.ROOT/'logs/publish_state.json';rows=[] if rows is None else rows
    start=datetime.fromisoformat(OLD_DATE+'T00:00:00+08:00').timestamp()
    # Each job keeps the first confirmation cutoff, before any video from today's new batch.
    with (contextlib.nullcontext() if already_locked else locked()):
        for job in jobs:
            if only_keys is not None and job['key'] not in only_keys:continue
            result=dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],status='manual_required',permalink='',error='')
            try:
                state=upload.read_json(state_path,{});record=state[job['key']]
                end=datetime.fromisoformat(record['confirmed_batch_lookup_cutoff']).timestamp()
                comment_key=comments.hashlib.sha256((job['key']+'\0'+comments.text_hash(COMMENT)).encode()).hexdigest()
                existing=upload.read_json(upload.ROOT/'logs/video_comments.json',{}).get(comment_key,{})
                if existing.get('status') in {'sent','already_present','sending','needs_review'}:
                    result.update(status=existing['status'],permalink=existing.get('permalink',''),error=existing.get('error',''))
                    continue
                if any(r.get('account')==job['account'] and r.get('status') in {'preparing','posting'} for r in state.values()):
                    raise RuntimeError('该账号另有提交中的任务，未关闭其浏览器或补评论')
                entry=dict(configured(job),auto_switch_personal=True)
                close_selected_window(entry['account'])
                print('补昨天原视频的评论：',job['account'],job['target'],job['filename'],flush=True)
                with sync_playwright() as playwright:
                    context=upload.launch_context(playwright,entry)
                    try:
                        page=context.pages[0] if context.pages else context.new_page();page.set_default_timeout(15000)
                        page.goto(upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000)
                        proof=upload.ensure_identity(page,entry)
                        link=links.get(job['key'])
                        if link:verified=(link,'user_supplied_exact_job_link')
                        elif record.get('comment_link_job_key')==job['key'] and comments.direct_link(record.get('permalink','')):
                            verified=(comments.direct_link(record['permalink']),'previously_verified_exact_job_link')
                        else:verified=find_published(page,context,entry,job['caption_text'],start,end)
                        value=comments.after_publication(page,context,entry,proof,job['key'],record,COMMENT,None,verified_link=verified)
                        record.update(comment_status=value['status'],comment_error=value.get('error',''))
                        upload.save_json(state_path,state)
                        result.update(status=value['status'],permalink=value.get('permalink',''),error=value.get('error',''))
                    except Exception as error:
                        comments.capture_failure(page,job['key'],error);raise
                    finally:context.close()
            except KeyboardInterrupt:raise
            except Exception as error:
                result['error']=str(error)[:2000]
                current=upload.read_json(state_path,{})
                if current.get(job['key'],{}).get('status')=='published':
                    current[job['key']].update(comment_status='manual_required',comment_error=result['error'])
                    upload.save_json(state_path,current)
            finally:
                rows.append(result);write_backfill_report(manifest,rows,output_dir)
                print('昨日评论：',job['account'],job['target'],result['status'],result['error'].splitlines()[0] if result['error'] else '',flush=True)
    return rows


def execute(output_dir=None,links_path=None,comments_only=False):
    if upload.VERSION!='2.40':raise ValueError('需安装配套上传核心 2.40')
    now=datetime.now(timezone.utc)
    if now.astimezone(batch.BJ).date().isoformat()!=TODAY:raise ValueError('不是本次授权的北京时间日期，不自动改日发布')
    with locked():
        old_path,old=load_unique(OLD_DATE,expected_prefix='64658f5a')
        confirm_yesterday(old_path,old)
        path,value=(None,None) if comments_only else load_unique(TODAY,required=False)
        if not comments_only and path is None:
            try:
                current=datetime.now(timezone.utc)
                path,value=batch.freeze(TODAY,current.astimezone(batch.BJ).strftime('%H:%M'),True,COMMENT,current)
                if output_dir:value['output_dir']=str(output_dir);upload.save_json(path,value)
            except ValueError as error:
                if '没有可冻结的全新视频' not in str(error):raise
                print('没有新视频可发布；仍执行昨天漏评论。',flush=True)
        if value and value['payload'].get('comment_text')!=COMMENT:raise ValueError('今天已有清单的评论文案不一致，未覆盖')
    visited=set();old_rows=[]
    def before_new(job):
        selected={j['key'] for j in old['payload']['jobs']
                  if (j['account'],j['target'])==(job['account'],job['target'])}-visited
        if selected:
            backfill(old,output_dir,links_path,only_keys=selected,rows=old_rows,already_locked=True)
            visited.update(selected)
    result=0
    if path:
        print('逐目标补昨天评论、发布今天的新视频。排除 fb16/fb18/fb21；成功记录及归档自动保存。',flush=True)
        if datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):
            print('等待刚写入的文案文件稳定（最多约 75 秒），之后自动开始，请保持窗口打开。',flush=True)
        while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
        result=batch.run(path,output_dir,before_job=before_new)
    remaining={j['key'] for j in old['payload']['jobs']}-visited
    if remaining:backfill(old,output_dir,links_path,only_keys=remaining,rows=old_rows)
    if any(r['status'] not in {'sent','already_present'} for r in old_rows):result=3
    return result


@contextlib.contextmanager
def keep_awake():
    kernel=None;previous=0
    if sys.platform=='win32':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.SetThreadExecutionState.argtypes=[ctypes.c_uint]
        kernel.SetThreadExecutionState.restype=ctypes.c_uint
        previous=kernel.SetThreadExecutionState(0x80000001)
    try:yield
    finally:
        if kernel:kernel.SetThreadExecutionState(previous or 0x80000000)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='补昨日评论并立即发布今天新视频；不重发旧视频')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--links-csv',type=Path,help='仅补无法自动确定的原视频链接，CSV 完整指纹不得改动')
    parser.add_argument('--comments-only',action='store_true')
    args=parser.parse_args()
    try:
        with keep_awake():raise SystemExit(execute(args.output_dir,args.links_csv,args.comments_only))
    except KeyboardInterrupt:print('已中断；保留记录，不自动重发。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',error,flush=True);raise SystemExit(1)
