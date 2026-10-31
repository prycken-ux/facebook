"""Oct-31 authorization: retry only the eight exact Oct-30 failed-before-Post jobs."""
import argparse
import copy
import csv
import shutil
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
from add_fb_accounts import locked

DATE='2026-10-31'
SOURCE='frozen-material-2026-10-30-95909206c11ab92a.json'
KEYS={
 ('fb01','page01'):'ea7f9bd1ebb00d5985d111ccb57aa3637030328b9b8136f5fa119d3114b187d6',
 ('fb09','personal'):'6a30dc8af05f7c8125073ce59929bf7a3475770dd2ceacde664d7432b8d69cbb',
 ('fb10','page01'):'eed4a2e58f5dc3e920bd462d781ae5163b18479c3a5ad65df1b0a8583f862ac7',
 ('fb10','page02'):'c1f132ff62b6978078a799c7e8ae84e7f64ad4b0d1d7bb9d69ae4a626a670bb1',
 ('fb10','page06'):'8be4a2614d7cdd1790b8785f84f7becb4a8f3b5855e9e7a8a71c01216a71eb12',
 ('fb10','page09'):'a4e63c6c43ab3606fbcf9f98dbb3450b7662a3f1633a3e4e68d26907893666af',
 ('fb10','page10'):'6dc19d92d57a5ad17799c689ee56119d59266efd84906cf0ece60e66917a8731',
 ('fb23','personal'):'3fbe2882fc7cc59b5087f18f538b76ec135bfff81827726458b6c5652840c92b'
}


def source_jobs():
    path=upload.ROOT/'logs'/SOURCE
    value=upload.read_json(path,{})
    payload=value.get('payload',{})
    checksum=batch.digest(payload)
    if (value.get('sha256')!=checksum or not path.stem.endswith(checksum[:16])
            or payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-10-30'
            or payload.get('ai_label') is not False or payload.get('comment_text')!=daily.COMMENT):
        raise ValueError('10月30日原清单缺失或校验不一致，未选其他日期/最新文件代替')
    jobs=[]
    for pair,key in KEYS.items():
        matches=[j for j in payload.get('jobs',[]) if (j.get('account'),j.get('target'))==pair and j.get('key')==key]
        if len(matches)!=1:raise ValueError('原批次没有唯一匹配的指定素材：'+'/'.join(pair))
        jobs.append(copy.deepcopy(matches[0]))
    return path,value,jobs


def make_retry(output_dir=None):
    now=datetime.now(timezone.utc)
    if now.astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('本次重发授权日期是北京时间10月31日，不自动改日重发')
    source,original,jobs=source_jobs()
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    selected=[];issues=[]
    for job in jobs:
        key=job['key'];record=state.get(key)
        try:
            daily.configured(job)
            if (not isinstance(record,dict) or (record.get('account'),record.get('target'))!=(job['account'],job['target'])
                    or upload.target_key(record.get('url',''))!=upload.target_key(job['url'])
                    or str(record.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):
                raise ValueError('现有记录缺失或与原视频不一致，未创建新任务或解除限制')
            selected.append(job)
        except Exception as error:issues.append(dict(account=job['account'],target=job['target'],filename=job['filename'],key=key,reason=str(error)))
    payload=dict(schema=batch.SCHEMA,date=DATE,start=now.isoformat(),requested_start=now.isoformat(),
        ai_label=False,include_fb10_pages=True,excluded_accounts=['fb16','fb18','fb21'],
        comment_text=daily.COMMENT,jobs=selected,run_kind='retry-oct30-eight',source_manifest=SOURCE,
        source_sha256=original['sha256'],authorized_keys=sorted(KEYS.values()))
    path=upload.ROOT/'logs'/'retry-oct30-eight-authorized-20261031.json'
    if path.exists():
        previous=upload.read_json(path,{})
        old=previous.get('payload',{})
        if (previous.get('sha256')!=batch.digest(old) or old.get('run_kind')!='retry-oct30-eight'
                or old.get('date')!=DATE or old.get('source_sha256')!=original['sha256']
                or old.get('authorized_keys')!=sorted(KEYS.values())
                or any(j.get('key') not in KEYS.values() for j in old.get('jobs',[]))):
            raise ValueError('本次重发清单校验失败，未覆盖或换用其他任务')
        return path,previous
    value=dict(payload=payload,sha256=batch.digest(payload),created_at=now.isoformat(),issues=issues,output_dir=str(output_dir) if output_dir else None)
    upload.save_json(path,value)
    backup=upload.ROOT/'backups'/('retry-oct30-eight-'+now.strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    shutil.copy2(upload.ROOT/'logs/publish_state.json',backup/'publish_state.json')
    shutil.copy2(source,backup/source.name)
    print('仅重发原报告的八个失败目标；原状态及清单已备份：',backup,flush=True)
    for row in issues:print('此项保留待核实，继续其他目标：',row['account'],row['target'],row['reason'],flush=True)
    return path,value



def reserve_exact_retry(job):
    """Caller holds the global uploader lock. A consumed grant is never reset."""
    row=upload.read_json(upload.ROOT/'logs/publish_state.json',{}).get(job['key'])
    if (not isinstance(row,dict) or (row.get('account'),row.get('target'))!=(job['account'],job['target'])
            or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
            or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):
        raise ValueError('原任务记录缺失或变化，未把旧素材作为新视频重发')
    path=upload.ROOT/'logs'/'retry-oct30-eight-authorized-20261031-claims.json'
    claims=upload.read_json(path,{})
    if job['key'] in claims:raise ValueError('该原视频本次重试许可已使用；保留记录，需核实后再处理')
    claims[job['key']]=dict(account=job['account'],target=job['target'],filename=job['filename'],
        reserved_at=datetime.now(timezone.utc).isoformat(),source=SOURCE,original_record=copy.deepcopy(row))
    upload.save_json(path,claims)

def execute(output_dir=None,comments_only=False):
    if upload.VERSION!='2.42':raise ValueError('需安装配套上传核心 2.42')
    with locked():path,value=make_retry(output_dir)
    if not comments_only:
        print('第一阶段：重发这八个目标的原视频。成功/待核实/提交中记录不重发，发生问题继续下一个。',flush=True)
        batch.run(path,output_dir,before_job=reserve_exact_retry,defer_comments=True,retry_before_post=True)
    print('第二阶段：仅处理本次八个目标中已经成功的视频评论。',flush=True)
    daily.backfill(value,output_dir)
    report_path=path.with_name(path.stem+'-results.json')
    attempts=upload.read_json(report_path,{}).get('attempts',[])
    rows=batch.results(path,value,attempts,output_dir,final=True)
    return 0 if not value.get('issues') and all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='10月31日仅重发10月30日报告中八条发布前失败原视频')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--comments-only',action='store_true')
    args=parser.parse_args()
    try:
        with daily.keep_awake():raise SystemExit(execute(args.output_dir,args.comments_only))
    except KeyboardInterrupt:print('已停止，保留发布/评论记录，勿直接重复提交。',flush=True);raise SystemExit(130)
    except Exception as error:
        import traceback
        try:(upload.ROOT/'logs/retry-eight-run-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        except OSError:pass
        print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
