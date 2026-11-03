"""One fresh batch: publish each video and immediately verify its own comment."""
import argparse
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
from add_fb_accounts import locked
import automatic_batch_retry as automatic_retry

PUBLISH_WORKFLOW_VERSION="2.3-immediate-comments"


def execute(date,real_footage,output_dir=None):
    if not real_footage:raise ValueError('须确认本批全部实拍，再使用 --real-footage')
    if upload.VERSION!='2.47':raise ValueError('自动补发流程需安装上传核心 2.47')
    if (getattr(upload,'IMMEDIATE_COMMENT_VERSION','')!='1.0-receipt-first-reload'
            or automatic_retry.AUTO_RETRY_VERSION!='1.1-immediate-aware'):
        raise ValueError('须安装完整即时评论及补发配套更新')
    now=datetime.now(timezone.utc)
    if now.astimezone(batch.BJ).date().isoformat()!=date:raise ValueError('仅运行明确指定的北京时间当天，不补跑旧批次')
    with locked():
        path,value=batch.freeze(date,now.astimezone(batch.BJ).strftime('%H:%M'),True,daily.COMMENT,now,report_format='text',exclude_previous_plans=True)
        value['workflow']='future-video-comments-v1'
        value['auto_retry_policy']=automatic_retry.POLICY
        value['comment_timing']=upload.IMMEDIATE_COMMENT_TIMING
        value['report_format']='text'
        if output_dir:value['output_dir']=str(output_dir)
        upload.save_json(path,value)
    print('本批新视频：',len(value['payload']['jobs']),'；排除 fb16/fb18/fb21；同名文案优先。',flush=True)
    print('每条视频成功后立即评论并刷新确认，再处理下一条；首轮结束补发一次可恢复的发布前失败。不处理以前的视频或评论。',flush=True)
    with daily.keep_awake():
        while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
        batch.run(path,output_dir,defer_comments=False,retry_before_post=False)
        automatic_retry.run(path,output_dir)
        report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
        rows=batch.results(path,value,report.get('attempts',[]),output_dir,final=True)
    return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='本批每条视频发布成功立即评论并刷新核验；首轮结束安全补发一次')
    parser.add_argument('--date',required=True,help='本次授权的北京时间日期 YYYY-MM-DD')
    parser.add_argument('--real-footage',action='store_true',help='确认本批全部实拍，不含 AI')
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    raise SystemExit(execute(args.date,args.real_footage,args.output_dir))
