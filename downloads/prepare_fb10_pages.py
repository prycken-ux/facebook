"""Inventory and preview fb10's ten managed Pages; never clicks Post."""
import argparse
import copy
import csv
import hashlib
import sys
import time
from collections import Counter
from datetime import datetime

import apply_common_caption as captions
import fb_upload as upload
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window
from publish_available_today import fresh_video,validate_exact
from retry_failed_with_switch import repair_identity

PAGES=tuple(f'page{n:02d}' for n in range(1,11))


def stamp():
    return datetime.now().astimezone().isoformat()


def inventory(config,state):
    if (not isinstance(config,dict) or not isinstance(config.get('targets'),list)
            or any(not isinstance(row,dict) for row in config['targets']) or not isinstance(state,dict)):
        raise ValueError('原配置或发布记录格式异常')
    if not (upload.ROOT/'profiles/fb10').is_dir():
        raise ValueError('缺少 fb10 原浏览器资料，未创建空白资料代替')
    owners=[entry for entry in config['targets'] if
            (entry.get('account'),entry.get('target'),entry.get('type'))==('fb10','personal','personal')]
    if len(owners)!=1:
        raise ValueError('fb10 缺少唯一的原个人主页配置')
    upload.validate_entry(owners[0])
    identities=Counter()
    for entry in config['targets']:
        try:
            identities[upload.target_key(entry.get('url',''))]+=1
        except ValueError:
            pass
    rows=[]
    for target in PAGES:
        folder=upload.ROOT/'videos/fb10'/target/'inbox'
        row=dict(account='fb10',target=target,name='未登记公共主页',url='',inbox=str(folder),filename='',key=None,
                 status='not_registered',reason='尚未登记，补充主页链接后才能核验',eligible=False,recorded_inbox=[])
        found=[entry for entry in config['targets'] if
               (entry.get('account'),entry.get('target'))==('fb10',target)]
        try:
            if not found:
                rows.append(row)
                continue
            if len(found)!=1:
                raise ValueError('公共主页编号重复，未猜选')
            entry=found[0]
            upload.validate_entry(entry)
            identity=upload.target_key(entry['url'])
            if entry.get('type')!='page' or not identity.startswith('id:'):
                raise ValueError('需要数字 ID 公共主页配置')
            if identities[identity]!=1:
                raise ValueError('此主页链接在配置中重复，未选择')
            row.update(name=entry['name'],url=entry['url'],entry=copy.deepcopy(entry),registered=True)
            selected=fresh_video(entry,state,row['recorded_inbox'])
            if selected is None:
                counts=dict(Counter(record['status'] for record in row['recorded_inbox']))
                row.update(status='no_new_video',reason='没有未记录的新视频；已有记录保留：'+str(counts))
            else:
                key,video=selected
                row.update(key=key,filename=video.name,status='ready_for_preview',eligible=True,
                    reason='可准备此确切新视频，尚未发布')
                pending=[key for key,record in state.items() if isinstance(record,dict) and
                    (record.get('account'),record.get('target'))==('fb10',target) and
                    record.get('status') in {'needs_review','posting','preparing'}]
                if pending:
                    row.update(status='blocked_by_older_review',eligible=False,blocking_keys=pending,
                        reason='该主页有旧待核实任务，先核实原视频；不清除旧记录')
        except Exception as error:
            row.update(status='needs_check',eligible=False,reason=str(error).splitlines()[0][:500])
        rows.append(row)
    return rows


def public_rows(rows):
    return [{key:value for key,value in row.items() if key!='entry'} for row in rows]


def save(path,report,rows,results):
    outcomes={result['target']:result for result in results}
    final=[]
    for original in public_rows(rows):
        row=dict(original)
        if row['target'] in outcomes:
            result=outcomes[row['target']]
            row.update(status=result['status'],reason=result.get('error') or result.get('reason',''))
        final.append(row)
    report.update(final_rows=final,results=results)
    upload.save_json(path,report)
    with path.with_suffix('.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        fields=['account','target','name','url','inbox','filename','status','reason','key']
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        writer.writerows(final)
    return final


def initialize_folders():
    for target in PAGES:
        for name in ('inbox','completed','failed'):
            (upload.ROOT/'videos/fb10'/target/name).mkdir(parents=True,exist_ok=True)


def preview_matches(entry,row,text,ai_label):
    return bool(entry.get('prepared_at') and entry.get('preparation_video_key')==row['key']
        and entry.get('preparation_video_filename')==row['filename']
        and entry.get('preparation_ai_label') is (ai_label=='on')
        and entry.get('preparation_caption_sha256')==hashlib.sha256(text.encode('utf-8')).hexdigest()
        and entry.get('preparation_target_key')==upload.target_key(entry['url']))


def prepare(rows,ai_label,common_caption,report_path,report,close_windows=False):
    state_path=upload.ROOT/'logs/publish_state.json'
    results=[]
    if common_caption:
        text=(upload.ROOT/'common_caption_today.txt').read_text(encoding='utf-8-sig').strip()
        if not text:
            raise ValueError('原统一文案为空')
    else:
        text=None
    backup=upload.ROOT/'backups'/('fb10-pages-preview-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    for original in (upload.CONFIG,state_path):
        if original.is_file():
            (backup/original.name).write_bytes(original.read_bytes())
    report['backup']=str(backup)
    if common_caption:
        for row in rows:
            if not row['eligible']:
                continue
            try:
                captions.apply(['fb10'],text,target_filter={('fb10',row['target'])})
            except Exception as error:
                row.update(status='needs_check',eligible=False,reason=str(error).splitlines()[0][:500])
        if any(row['eligible'] for row in rows):
            print('等待 61 秒让文案稳定。',flush=True)
            for seconds in (30,31):
                time.sleep(seconds)
                print('等待中。' if seconds==30 else '开始逐个公共主页预览。',flush=True)
    report['rows']=public_rows(rows)
    save(report_path,report,rows,results)
    if close_windows and any(row['eligible'] for row in rows):
        close_selected_window('fb10')
    try:
        for row in rows:
            if not row['eligible']:
                continue
            entry=row['entry']
            result=dict(account='fb10',target=row['target'],key=row['key'],filename=row['filename'],started_at=stamp())
            print('\n准备公共主页：',row['target'],row['name'],row['filename'],flush=True)
            try:
                state=upload.read_json(state_path,{})
                selected=upload.named_job(entry,state,row['filename'])
                if not selected or selected[0]!=row['key']:
                    raise ValueError('原视频指纹变化，未选择其他文件')
                expected_text=text if common_caption else selected[3]
                validate_exact(entry,state,row,expected_text)
                # Shared fb10 profile: manual switching is serial and must pass
                # the ordinary numeric Page actor/header identity checks.
                if preview_matches(entry,row,expected_text,ai_label):
                    result.update(status='preview_ready',reason='此确切视频及相同文案、AI 设置已有准备记录，本次无需重复预览')
                elif not repair_identity(entry):
                    result.update(status='manual_skipped',reason='用户跳过该主页身份切换，未上传或发布')
                else:
                    validate_exact(entry,upload.read_json(state_path,{}),row,expected_text)
                    ready=upload.run_entry(entry,upload.read_json(state_path,{}),state_path,False,
                        filename=row['filename'],ai_label_override=ai_label=='on',expected_job_key=row['key'])
                    if not ready:
                        raise ValueError('没有完成预览，未标记准备成功')
                    validate_exact(entry,upload.read_json(state_path,{}),row,expected_text)
                    config=upload.read_json(upload.CONFIG,{})
                    found=[item for item in config.get('targets',[]) if
                           (item.get('account'),item.get('target'))==('fb10',row['target'])]
                    if len(found)!=1 or found[0]!=entry:
                        raise ValueError('准备期间配置变化，未保存准备状态')
                    checked_at=stamp()
                    found[0].update(prepared_at=checked_at,preparation_video_key=row['key'],
                        preparation_video_filename=row['filename'],preparation_ai_label=ai_label=='on',
                        preparation_caption_sha256=hashlib.sha256(expected_text.encode('utf-8')).hexdigest(),
                        preparation_target_key=upload.target_key(entry['url']))
                    upload.save_json(upload.CONFIG,config)
                    result.update(status='preview_ready',reason='本地预览核对完成；没有点击 Post，尚未发布',prepared_at=checked_at)
            except Exception as error:
                result.update(status='needs_check',error=str(error).splitlines()[0][:500])
                detail=report_path.with_name(report_path.stem+'-'+row['target']+'-error.txt')
                try:
                    detail.write_text(str(error),encoding='utf-8')
                    result['detail_log']=str(detail)
                except OSError:
                    pass
                print('保留此目标并继续：',result['error'],flush=True)
                if result.get('detail_log'):
                    print('详细原因：',result['detail_log'],flush=True)
            results.append(result)
            save(report_path,report,rows,results)
        report['phase']='previews_finished'
    except KeyboardInterrupt:
        report['phase']='interrupted'
        raise
    finally:
        final=save(report_path,report,rows,results)
        print('\n预览准备结果（不是发布结果）：',flush=True)
        for row in final:
            print(row['target'],row['name'],row['filename'] or '-',row['status'],row['reason'],flush=True)
        print('预览完成：',sum(row['status']=='preview_ready' for row in final),'/10；本工具未点击 Post。',flush=True)
        print('准备清单：',report_path.with_suffix('.csv'),flush=True)
    return 0 if len(results)==10 and all(result['status']=='preview_ready' for result in results) else 3


def run(do_prepare=False,init_folders=False,ai_label=None,common_caption=False,close_windows=False):
    if do_prepare and ai_label not in {'on','off'}:
        raise ValueError('本批预览需要明确 --ai-label off 或 on，不能沿用其他批次猜测')
    with locked():
        config=upload.read_json(upload.CONFIG,{})
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        rows=inventory(config,state)
        if init_folders:
            initialize_folders()
        path=upload.ROOT/'logs'/('fb10-pages-prepare-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
        report=dict(schema='fb10-pages-preparation-v1',created=stamp(),ai_label=ai_label,
            caption_source='common_caption_today.txt' if common_caption else 'per-video txt',
            phase='preparing_previews' if do_prepare else 'inventory_only',rows=public_rows(rows))
        save(path,report,rows,[])
        for row in rows:
            print(row['target'],row['name'],row['status'],row['reason'],flush=True)
            print('素材目录：',row['inbox'],flush=True)
        if not do_prepare:
            print('目录和配置核对完成；预留 page10 文件夹不等于已经登记 page10。',flush=True)
            print('清单：',path.with_suffix('.csv'),flush=True)
            print('没有选择视频、启用目标或点击发布。',flush=True)
            return 0
        return prepare(rows,ai_label,common_caption,path,report,close_windows)


def main():
    parser=argparse.ArgumentParser(description='fb10 十个公共主页的目录核对与逐页预览，不发布')
    parser.add_argument('--init-folders',action='store_true')
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--ai-label',choices=['off','on'])
    parser.add_argument('--use-common-caption',action='store_true',help='本批明确沿用原统一文案，生成新视频的同名 TXT')
    parser.add_argument('--close-windows',action='store_true')
    args=parser.parse_args()
    return run(args.prepare,args.init_folders,args.ai_label,args.use_common_caption,args.close_windows)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('已结束预览准备，保留原发布记录；本工具没有点击 Post。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',str(error).splitlines()[0],flush=True)
        raise SystemExit(1)
