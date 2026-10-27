"""Locally record a user's explicit confirmation for selected exact round jobs."""
import argparse
import copy
import re
import shutil
import sys
from datetime import datetime

import fb_upload as upload
import publish_fourteen_current as driver
from add_fb_accounts import locked
from diagnose_personal_identity import parse_target_pairs
from retry_failed_with_switch import load_bound_round


def basename(value):
    return str(value).replace('\\','/').rsplit('/',1)[-1]


def load_expanded_report(filename):
    if not re.fullmatch(r'available-today-\d{8}-\d{6}-\d{6}\.json',filename):
        raise ValueError('需提供 logs 中确切的 available-today 报告文件名')
    path=upload.ROOT/'logs'/filename
    report=upload.read_json(path,{})
    if (not isinstance(report,dict) or report.get('schema')!='available-current-publication-v1'
            or report.get('phase')=='plan_only' or not isinstance(report.get('rows'),list)
            or any(not isinstance(row,dict) for row in report['rows'])
            or report.get('ai_label') not in {'off','on'} or not report.get('caption_text','').strip()):
        raise ValueError('没有有效的原新账号实际发布报告')
    created=datetime.fromisoformat(report.get('created',''))
    if created.tzinfo is None or created.strftime('%Y%m%d')!=filename[16:24]:
        raise ValueError('原报告日期或时区与文件名不一致')
    return path,report


def missing_record_source(entry,filename,key):
    folder=upload.inbox_for(entry)
    candidates=[folder/filename]
    if (folder.parent/'completed').is_dir():
        candidates.extend((folder.parent/'completed').rglob(filename))
    for video in candidates:
        if not video.is_file():
            continue
        video.resolve().relative_to(folder.parent.resolve())
        before=video.stat()
        actual=upload.job_key(entry,video)
        after=video.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise ValueError('补记期间视频正在变化，未创建成功记录')
        if before.st_size and actual==key:
            return video
    raise ValueError('缺少本地记录，且没有与原报告指纹一致的原视频；未猜选其他素材')


def confirmation_plan(config,state,report,targets,allow_unrecorded=False):
    if not targets or len(set(targets))!=len(targets):
        raise ValueError('需提供明确且不重复的已确认目标')
    plan=[]
    for pair in targets:
        rows=[r for r in report['rows'] if (r.get('account'),r.get('target'))==pair]
        entries=[e for e in config.get('targets',[]) if (e.get('account'),e.get('target'))==pair]
        if len(rows)!=1 or len(entries)!=1:
            raise ValueError('原批次素材或当前目标不唯一：'+'/'.join(pair))
        source,entry=rows[0],entries[0]
        upload.validate_entry(entry)
        key=source.get('key')
        if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{64}',key):
            raise ValueError('原批次没有确切素材指纹，未用旧视频代替：'+'/'.join(pair))
        upload.validate_video_filename(source.get('filename'))
        record=state.get(key)
        manual_source=None
        if record is None:
            if not allow_unrecorded:
                raise ValueError('原批次缺少确切任务记录，未自动创建成功记录')
            if report.get('ai_label') not in {'off','on'} or not report.get('caption_text','').strip():
                raise ValueError('缺少原批次明确素材设置，未创建成功记录')
            manual_source=missing_record_source(entry,source['filename'],key)
        elif (not isinstance(record,dict) or (record.get('account'),record.get('target'))!=pair
                or upload.target_key(record.get('url',''))!=upload.target_key(entry['url'])
                or basename(record.get('video',''))!=source['filename']):
            raise ValueError('原批次、任务记录或当前目标不一致：'+'/'.join(pair))
        if source.get('url') and upload.target_key(source['url'])!=upload.target_key(entry['url']):
            raise ValueError('原批次目标网址已变化')
        if record is not None and record.get('status') not in {'published','failed_before_post','needs_review'}:
            raise ValueError('任务状态需先检查：'+'/'.join(pair))
        plan.append(dict(account=pair[0],target=pair[1],key=key,filename=source['filename'],
                         previous_status=record['status'] if record is not None else 'unrecorded',entry=entry,
                         manual_source=str(manual_source) if manual_source is not None else None))
    if len({row['key'] for row in plan})!=len(plan):
        raise ValueError('选定素材指纹重复，未确认')
    return plan


def archive_confirmed(item):
    """Move only matching inbox bytes; a replaced same-name file stays untouched."""
    video=upload.inbox_for(item['entry'])/item['filename']
    if not video.exists():
        return '原文件不在 inbox，成功补记保留；没有移动其他文件'
    if not video.is_file() or upload.job_key(item['entry'],video)!=item['key']:
        return 'inbox 同名文件已是其他内容，未移动；只确认原批次视频'
    caption=video.with_suffix('.txt')
    if not caption.is_file():
        return '缺少同名文案，原文件保留；成功记录已补记'
    # Recheck immediately before moving, after the success guard is persisted.
    if upload.job_key(item['entry'],video)!=item['key']:
        raise ValueError('视频在归档前发生变化，未移动')
    folder=upload.archive(video,caption)
    return '原视频已归档：'+str(folder/item['filename'])


def confirm(round_start,targets,verified=False,source_report=None,allow_unrecorded=False):
    if not verified:
        raise ValueError('需 --verified-published，表示用户已在 Facebook 确认选定原视频实际发布')
    with locked():
        path,report=(load_expanded_report(source_report) if source_report else load_bound_round(round_start))
        state_path=upload.ROOT/'logs/publish_state.json'
        original=upload.read_json(state_path,{})
        config=upload.read_json(upload.CONFIG,{})
        plan=confirmation_plan(config,original,report,targets,allow_unrecorded)
        now=datetime.now().astimezone().isoformat()
        backup=upload.ROOT/'backups'/('confirmed-selected-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True)
        for source in (state_path,upload.CONFIG,path,path.with_suffix('.csv')):
            if source.is_file():
                shutil.copy2(source,backup/source.name)
        audit=dict(source_report=path.name,round_start=round_start,confirmed_at=now,
            method='user_confirmed_selected_existing_posts_no_links',
            rows=[{k:v for k,v in item.items() if k!='entry'} for item in plan])
        upload.save_json(backup/'confirmation.json',audit)
        state=copy.deepcopy(original)
        for item in plan:
            if item['key'] not in state:
                video=upload.ROOT/item['manual_source']
                if upload.job_key(item['entry'],video)!=item['key']:
                    raise ValueError('原视频在补记前变化，未写成功记录')
                state[item['key']]=dict(account=item['account'],target=item['target'],
                    url=item['entry']['url'],video=str(video),caption=str(video.with_suffix('.txt')),
                    created=report['created'],status='unrecorded',ai_label_requested=report['ai_label']=='on')
            record=state[item['key']]
            if record['status']!='published':
                record.update(status='published',status_before_user_confirmation=record['status'],
                    confirmation_method='user_confirmed_existing_post_no_link',confirmed_at=now,
                    confirmed_source_report=path.name)
        if state!=original:
            upload.save_json(state_path,state)
        selected={item['key'] for item in plan}
        # Retain immutable source rows and all earlier attempts/errors. Only
        # the current result view changes, and only for the selected full keys.
        finals=copy.deepcopy(report.get('final_rows') or report['rows'])
        for row in finals:
            if row.get('key') in selected:
                row.update(status='published',reason='用户已确认该原批次视频发布成功；不重发')
        report['final_rows']=finals
        confirmations=report.setdefault('selected_user_confirmations',[])
        if not any(set(item.get('keys',[]))==selected for item in confirmations):
            confirmations.append(dict(confirmed_at=now,keys=sorted(selected),backup=str(backup)))
        upload.save_json(path,report)
        driver.save_csv(path.with_suffix('.csv'),finals)
        for item,result in zip(plan,audit['rows']):
            try:
                result['archive_result']=archive_confirmed(item)
            except Exception as error:
                result['archive_result']='归档需检查，已保留成功状态：'+str(error).splitlines()[0]
            print(item['account']+'/'+item['target'],item['filename'],'已确认成功；不重发。',result['archive_result'],flush=True)
        upload.save_json(backup/'confirmation.json',audit)
        print('选定原视频成功补记：',len(plan),'；本工具没有上传或发布。备份：',backup,flush=True)
    return 0


def main():
    parser=argparse.ArgumentParser(description='仅补记用户明确确认的原批次指定视频，不发布')
    scope=parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--round-start')
    scope.add_argument('--source-report')
    parser.add_argument('--targets',required=True)
    parser.add_argument('--verified-published',action='store_true')
    parser.add_argument('--allow-unrecorded',action='store_true',help='用户已核实手动发布，允许按原报告和本地原视频补建确切成功记录')
    args=parser.parse_args()
    return confirm(args.round_start,parse_target_pairs(args.targets),args.verified_published,args.source_report,args.allow_unrecorded)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：',str(error).splitlines()[0],flush=True)
        raise SystemExit(1)
