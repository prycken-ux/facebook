"""Retry one source-bound fb10 Page video freshly verified absent by its owner."""
import argparse
import re
import sys
from datetime import datetime

import fb_upload as upload
import publish_fb10_pages_direct as direct
from add_fb_accounts import locked
from retry_current_verified_absent import retry_one


def load_source(filename,target):
    if not re.fullmatch(r'fb10-pages-publish-\d{8}-\d{6}-\d{6}\.json',filename):
        raise ValueError('请指定确切原发布报告文件名，未使用最新批次代替')
    if not re.fullmatch(r'page(?:0[1-9]|10)',target):
        raise ValueError('补发范围只限 fb10 的指定公共主页')
    path=upload.ROOT/'logs'/filename
    report=upload.read_json(path,{})
    rows=report.get('rows')
    if (report.get('schema')!='fb10-pages-direct-publication-v1'
            or report.get('phase')=='plan_only' or report.get('ai_label') not in {'off','on'}
            or not isinstance(rows,list) or len(rows)!=10
            or any(not isinstance(row,dict) for row in rows)
            or {(row.get('account'),row.get('target')) for row in rows}
                !={('fb10',f'page{n:02d}') for n in range(1,11)}
            or not report.get('caption_text','').strip()):
        raise ValueError('来源不是有效的 fb10 十页实际发布批次')
    row=next(row for row in rows if row['target']==target)
    if not re.fullmatch(r'[a-f0-9]{64}',row.get('key') or ''):
        raise ValueError('指定主页在原批次没有确切视频指纹')
    upload.validate_video_filename(row.get('filename'))
    if not upload.target_key(row.get('url','')).startswith('id:'):
        raise ValueError('原批次缺少数字公共主页链接')
    return path,report,row


def run(source_report,target,verified=False,confirmation_id='',close_windows=False):
    if not verified:
        raise ValueError('需要本次手动确认对应原视频确实没有发布，才能补发')
    with locked():
        path,report,row=load_source(source_report,target)
    result=dict(account='fb10',target=target,key=row['key'],filename=row['filename'],
        attempted_at=datetime.now().astimezone().isoformat(),user_verified_absent=True,
        confirmation_id=confirmation_id)
    try:
        done=retry_one(('fb10',target),path,report,True,confirmation_id=confirmation_id,
                       direct_publication=True,close_windows=close_windows)
        result['attempt']='finished' if done is not False else 'skipped'
    except KeyboardInterrupt:
        result.update(attempt='interrupted',error='用户中断，保留当前任务记录')
        raise
    except Exception as error:
        result.update(attempt='stopped',error=str(error))
        print('补发已停止或需核实：',error,flush=True)
    finally:
        with locked():
            current=upload.read_json(path,{})
            if (current.get('schema')!=report['schema'] or current.get('rows')!=report['rows']
                    or current.get('caption_text')!=report['caption_text'] or current.get('ai_label')!=report['ai_label']):
                raise ValueError('来源报告在补发期间发生变化，未覆盖报告')
            current.setdefault('resume_results',[]).append(result)
            final=direct.save(path,current,current['rows'],current.get('results',[]))
            selected=next(item for item in final if item['target']==target)
            print('\n本次补发结果：fb10/'+target,selected['filename'],selected['status'],selected['reason'],flush=True)
            print('本轮累计成功：',sum(item['status']=='published' for item in final),'；其他目标未重新发布。',flush=True)
            print('原批次汇总已更新：',path.with_suffix('.csv'),flush=True)
    return 0 if selected['status']=='published' else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='只补发本次已核实不存在的 fb10 指定公共主页原视频')
    parser.add_argument('--source-report',required=True)
    parser.add_argument('--target',required=True)
    parser.add_argument('--verified-absent',action='store_true')
    parser.add_argument('--confirmation-id',required=True)
    parser.add_argument('--close-windows',action='store_true')
    args=parser.parse_args()
    try:
        raise SystemExit(run(args.source_report,args.target,args.verified_absent,args.confirmation_id,args.close_windows))
    except KeyboardInterrupt:
        print('补发已中断，保留任务记录；核实新结果前不要重复补发。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',error,flush=True)
        raise SystemExit(1)
