"""Publish one exact fresh video on each of fb10's ten Pages, without prompts."""
import argparse
import copy
import sys
import time
from datetime import datetime

import apply_common_caption as captions
import fb_upload as upload
import publish_available_today as today
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window
from prepare_fb10_pages import inventory


def stamp():
    return datetime.now().astimezone().isoformat()


def validate_current(row,text,require_caption=True):
    config=upload.read_json(upload.CONFIG,{})
    found=[entry for entry in config.get('targets',[]) if
           (entry.get('account'),entry.get('target'))==('fb10',row['target'])]
    if len(found)!=1 or found[0]!=row['entry']:
        raise ValueError('目标配置在本轮期间变化，未选择其他主页')
    if (upload.ROOT/'common_caption_today.txt').read_text(encoding='utf-8-sig').strip()!=text:
        raise ValueError('统一文案在本轮期间变化，未使用其他文案')
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    selected=today.fresh_video(row['entry'],state)
    if not selected or (selected[0],selected[1].name)!=(row['key'],row['filename']):
        raise ValueError('本轮素材已变化、已有记录或不再唯一，未用其他文件代替')
    if require_caption:
        today.validate_exact(row['entry'],state,row,text)
    return state


def save(path,report,rows,results):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    final=today.save_report(path,report,rows,results,state)
    report['manual_checks']=[row for row in final if row['status'] in {
        'needs_review','posting','preparing','needs_check','failed_before_post',
        'invalid','blocked_by_older_review','not_registered'} or any(
        item['status'] in {'needs_review','posting','preparing','failed_before_post'}
        for item in row.get('recorded_inbox',[]))]
    upload.save_json(path,report)
    return final


def run(publish=False,ai_label=None,close_windows=False):
    if publish and ai_label not in {'on','off'}:
        raise ValueError('直接发布需要明确 --ai-label off 或 on')
    if publish and upload.VERSION not in {'2.31','2.32'}:
        raise ValueError('请安装本包配套的上传核心 2.31，再直接发布')
    with locked():
        config=upload.read_json(upload.CONFIG,{})
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        rows=inventory(config,state)
        text=(upload.ROOT/'common_caption_today.txt').read_text(encoding='utf-8-sig').strip()
        if not text:
            raise ValueError('已保存的统一文案为空，未发布')
        for row in rows:
            if row['eligible']:
                row.update(status='ready_to_publish',reason='本轮确切新视频，可自动核验后发布')
        path=upload.ROOT/'logs'/('fb10-pages-publish-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
        report=dict(schema='fb10-pages-direct-publication-v1',created=stamp(),
            caption_text=text,ai_label=ai_label,rows=today.public_rows(rows),
            phase='publishing' if publish else 'plan_only',
            authorization='one exact fresh video per fb10 managed Page in this invocation; no permanent enable')
        results=[]
        save(path,report,rows,results)
        for row in rows:
            print(row['target'],row['name'],row['filename'] or '-',row['status'],row['reason'],flush=True)
        if not publish:
            print('只检查计划，未生成文案、启用或发布。',path.with_suffix('.csv'),flush=True)
            return 0

        backup=upload.ROOT/'backups'/('fb10-pages-direct-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True)
        for original in (upload.CONFIG,upload.ROOT/'logs/publish_state.json',upload.ROOT/'common_caption_today.txt'):
            if original.is_file():
                (backup/original.name).write_bytes(original.read_bytes())
        report['backup']=str(backup)
        print('直接发布：仅 fb10/page01～page10；无需 READY、POST 或预览回车。',flush=True)
        changed=False
        for row in rows:
            if not row['eligible']:
                continue
            try:
                validate_current(row,text,False)
                caption=upload.inbox_for(row['entry'])/row['filename']
                caption=caption.with_suffix('.txt')
                caption.resolve().relative_to(upload.ROOT.resolve())
                if not caption.is_file() or caption.read_text(encoding='utf-8-sig').strip()!=text:
                    if caption.exists():
                        saved=backup/caption.relative_to(upload.ROOT)
                        saved.parent.mkdir(parents=True,exist_ok=True)
                        saved.write_bytes(caption.read_bytes())
                    captions.atomic_caption(caption,text)
                    changed=True
            except Exception as error:
                row.update(status='needs_check',eligible=False,reason=str(error))
        report['rows']=today.public_rows(rows)
        save(path,report,rows,results)
        try:
            if changed:
                print('文案已写入，自动等待 61 秒让文件稳定。',flush=True)
                for seconds in (30,31):
                    time.sleep(seconds)
                    print('文案稳定等待中。' if seconds==30 else '开始逐页发布。',flush=True)
            if close_windows and any(row['eligible'] for row in rows):
                close_selected_window('fb10')
            for row in rows:
                if not row['eligible']:
                    continue
                result=dict(account='fb10',target=row['target'],key=row['key'],filename=row['filename'],
                            status='needs_check',started_at=stamp())
                print('\n自动发布：',row['target'],row['name'],row['filename'],flush=True)
                try:
                    state=validate_current(row,text)
                    # Authorization is for these current exact files only.
                    # Do not enable targets in the persisted scheduler config.
                    entry=dict(copy.deepcopy(row['entry']),enabled=True)
                    upload.run_entry(entry,state,upload.ROOT/'logs/publish_state.json',True,
                        filename=row['filename'],ai_label_override=ai_label=='on',expected_job_key=row['key'])
                    record=upload.read_json(upload.ROOT/'logs/publish_state.json',{}).get(row['key'],{})
                    if record.get('status')!='published':
                        raise RuntimeError('没有确切成功记录，不能视为发布成功')
                    result.update(status='published',reason='本轮确切视频收到成功回执并已记录')
                except KeyboardInterrupt:
                    result['reason']='用户中断，请按当前确切任务记录核实'
                    raise
                except Exception as error:
                    result['error']=str(error)
                    detail=path.with_name(path.stem+'-'+row['target']+'-error.txt')
                    detail.write_text(str(error),encoding='utf-8')
                    result['detail_log']=str(detail)
                    print('此目标保留记录，继续下一个：',str(error).splitlines()[0],flush=True)
                finally:
                    results.append(result)
                    save(path,report,rows,results)
            report['phase']='attempts_finished'
        except KeyboardInterrupt:
            report['phase']='interrupted'
            raise
        except Exception as error:
            report.update(phase='stopped',error=str(error))
            raise
        finally:
            final=save(path,report,rows,results)
            print('\n本轮确切视频发布结果：',flush=True)
            for row in final:
                print(row['target'],row['name'],row['filename'] or '-',row['status'],row['reason'],flush=True)
                for old in row.get('recorded_inbox',[]):
                    print('  已有素材记录：',old['filename'],old['status'],'；不重发',flush=True)
            print('本轮记录成功：',sum(row['status']=='published' for row in final),
                  '；需核实目标：',len(report['manual_checks']),flush=True)
            print('汇总：',path.with_suffix('.csv'),flush=True)
        return 3 if report['manual_checks'] else 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='fb10 十个公共主页的确切新视频自动直接发布')
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--ai-label',choices=['off','on'])
    parser.add_argument('--close-windows',action='store_true')
    args=parser.parse_args()
    try:
        raise SystemExit(run(args.run,args.ai_label,args.close_windows))
    except KeyboardInterrupt:
        print('批次已中断；保留任务记录，不自动重发未知结果。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',error,flush=True)
        raise SystemExit(1)
