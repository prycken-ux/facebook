"""Explicitly run one fresh batch: all uploads, then verified comments. No history scan."""
import argparse
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
from add_fb_accounts import locked


def execute(date,real_footage,output_dir=None):
    if not real_footage:raise ValueError('须确认本批全部实拍，再使用 --real-footage')
    if upload.VERSION not in {'2.43','2.44'}:raise ValueError('需安装上传核心 2.43 或 2.44')
    now=datetime.now(timezone.utc)
    if now.astimezone(batch.BJ).date().isoformat()!=date:raise ValueError('仅运行明确指定的北京时间当天，不补跑旧批次')
    with locked():
        path,value=batch.freeze(date,now.astimezone(batch.BJ).strftime('%H:%M'),True,daily.COMMENT,now)
        value['workflow']='future-video-comments-v1'
        if output_dir:value['output_dir']=str(output_dir)
        upload.save_json(path,value)
    print('本批新视频：',len(value['payload']['jobs']),'；排除 fb16/fb18/fb21；同名文案优先。',flush=True)
    print('先发布所有视频，再评论本批成功的视频；不处理以前的视频或评论。',flush=True)
    with daily.keep_awake():
        while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
        batch.run(path,output_dir,defer_comments=True,retry_before_post=False)
        daily.backfill(value,output_dir,future_only=True)
        report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
        rows=batch.results(path,value,report.get('attempts',[]),output_dir,final=True)
    return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='只发布本次新视频，批量完成后发送并刷新核验评论')
    parser.add_argument('--date',required=True,help='本次授权的北京时间日期 YYYY-MM-DD')
    parser.add_argument('--real-footage',action='store_true',help='确认本批全部实拍，不含 AI')
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    raise SystemExit(execute(args.date,args.real_footage,args.output_dir))
