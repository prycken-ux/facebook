"""Publish unique new material across configured old and newly added targets."""
import argparse
import copy
import csv
import sys
import time
from collections import Counter
from datetime import datetime

import apply_common_caption as captions
import fb_upload as upload
from add_fb_accounts import locked

ACCOUNTS = tuple(f'fb{n:02d}' for n in range(1,24))
PAUSED = {'fb16','fb18','fb21'}


def stamp():
    return datetime.now().astimezone().isoformat()


def fresh_video(entry,state,recorded=None):
    folder=upload.inbox_for(entry)
    if not folder.is_dir():
        return None
    selected=[]
    for video in sorted(folder.iterdir(),key=upload.queue_order):
        if not video.is_file() or video.suffix.lower()!='.mp4':
            continue
        upload.validate_video_filename(video.name)
        video.resolve().relative_to(upload.ROOT.resolve())
        if video.name.lower() in {name.lower() for name in entry.get('excluded_files',[])}:
            continue
        before=video.stat()
        if not before.st_size:
            raise ValueError('存在空视频，请检查：'+video.name)
        key=upload.job_key(entry,video)
        after=video.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise ValueError('视频正在变化，请等待复制完成：'+video.name)
        if key in state:
            record=state[key]
            if ((record.get('account'),record.get('target'))!=(entry['account'],entry['target'])
                    or upload.target_key(record.get('url',''))!=upload.target_key(entry['url'])):
                raise ValueError('视频指纹的已有记录与当前目标不一致')
            if recorded is not None:
                recorded.append(dict(key=key,filename=video.name,status=record.get('status','invalid')))
            continue
        if time.time()-after.st_mtime<60:
            raise ValueError('视频刚更新，请复制完成一分钟后处理：'+video.name)
        selected.append((key,video))
    if len(selected)>1:
        raise ValueError('当前目标有多条未记录新视频，未自动猜选')
    return selected[0] if selected else None


def plan(config,state,prepare_new):
    if (not isinstance(config,dict) or not isinstance(config.get('targets'),list)
            or any(not isinstance(row,dict) for row in config['targets']) or not isinstance(state,dict)):
        raise ValueError('上传配置或发布记录格式异常')
    entries=[entry for entry in config['targets'] if entry.get('account') in ACCOUNTS]
    pairs=Counter((entry.get('account'),entry.get('target')) for entry in entries)
    identities=Counter()
    for entry in entries:
        try:
            identities[upload.target_key(entry.get('url',''))]+=1
        except ValueError:
            pass
    rows=[]
    for entry in sorted(entries,key=lambda e:(e.get('target')!='personal',e.get('account',''),str(e.get('target','')))):
        account,target=entry.get('account'),entry.get('target')
        row=dict(account=account,target=target,name=entry.get('name',''),url=entry.get('url',''),
                 filename='',key=None,status='invalid',eligible=False,reason='',entry=entry,recorded_inbox=[])
        try:
            if account in PAUSED:
                row.update(status='paused',reason='账号仍在登录验证循环，保留暂停接入')
            else:
                upload.validate_entry(entry)
                if pairs[(account,target)]!=1 or identities[upload.target_key(entry['url'])]!=1:
                    raise ValueError('目标编号或主页链接重复，未猜选')
                if not (upload.ROOT/'profiles'/account).is_dir():
                    raise ValueError('缺少原浏览器资料，未创建空白资料代替')
                selected=fresh_video(entry,state,row['recorded_inbox'])
                if selected is None:
                    counts=Counter(item['status'] for item in row['recorded_inbox'])
                    detail='；inbox 已有记录：'+', '.join(f'{s}={n}' for s,n in sorted(counts.items())) if counts else '；inbox 没有可选 MP4'
                    row.update(status='no_new_video',reason='没有未记录的新视频'+detail+'。不代表已发布成功')
                else:
                    key,video=selected
                    needs_prepare=not (entry.get('prepared_at') and entry.get('enabled'))
                    row.update(key=key,filename=video.name,needs_prepare=needs_prepare,
                        status='needs_prepare' if needs_prepare else 'ready',eligible=not needs_prepare or prepare_new,
                        reason='首次准备后启用并发布' if needs_prepare else '可处理当前确切新素材')
        except Exception as error:
            row.update(status='invalid',eligible=False,reason=str(error).splitlines()[0][:300])
        rows.append(row)
    return rows


def public_rows(rows):
    return [{k:v for k,v in row.items() if k!='entry'} for row in rows]


def save_report(path,report,rows,results,state):
    outcomes={(r['account'],r['target']):r for r in results}
    final=[]
    for source in public_rows(rows):
        row=dict(source)
        record=state.get(row['key']) if row.get('key') else None
        result=outcomes.get((row['account'],row['target']),{})
        if record:
            row.update(status=record.get('status','invalid'),created=record.get('created',''),
                reason='当前确切素材已记录成功' if record.get('status')=='published' else
                '结果待核对，保留记录' if record.get('status') in {'needs_review','posting','preparing'} else
                str(record.get('error','')).splitlines()[0][:300] if record.get('error') else '')
        elif result:
            row.update(status=result.get('status',row['status']),reason=result.get('error',result.get('reason',row['reason'])))
        final.append(row)
    report.update(results=results,final_rows=final)
    report['manual_checks']=[dict(row) for row in final if row['status'] in
                            {'needs_review','posting','preparing','needs_check','failed_before_post','invalid'}]
    upload.save_json(path,report)
    with path.with_suffix('.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        fields=['account','target','name','filename','status','reason','key']
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        for row in final:
            writer.writerow({field:row.get(field,'') for field in fields})
    return final


def validate_exact(entry,state,row,text):
    if row['key'] in state:
        raise ValueError('此确切素材已有任务记录，本次不重发')
    selected=upload.named_job(entry,state,row['filename'])
    if not selected or selected[0]!=row['key'] or selected[3]!=text:
        raise ValueError('当前视频指纹或同名文案与本轮核对结果不同')


def run(publish=False,ai_label=None,prepare_new=False,close_windows=False,targets=None):
    if publish and ai_label not in {'off','on'}:
        raise ValueError('实际发布需要明确 --ai-label off 或 on')
    with locked():
        config=upload.read_json(upload.CONFIG,{})
        if targets is not None:
            if not targets or len(set(targets))!=len(targets):
                raise ValueError('需指定不重复的账号/目标')
            if any(account not in ACCOUNTS for account,target in targets):
                raise ValueError('指定目标超出已授权账号范围')
            selected=[e for e in config.get('targets',[]) if (e.get('account'),e.get('target')) in targets]
            if Counter((e.get('account'),e.get('target')) for e in selected)!=Counter(targets):
                raise ValueError('指定目标未登记或重复，未扩大到其他账号')
        state_path=upload.ROOT/'logs/publish_state.json'
        state=upload.read_json(state_path,{})
        text=(upload.ROOT/'common_caption_today.txt').read_text(encoding='utf-8-sig').strip()
        if not text:
            raise ValueError('已保存的统一文案为空')
        rows=plan(config,state,prepare_new)
        if targets is not None:
            rows=[row for row in rows if (row['account'],row['target']) in targets]
        path=upload.ROOT/'logs'/('available-today-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
        report=dict(schema='available-current-publication-v1',created=stamp(),ai_label=ai_label,
            scope_accounts=list(ACCOUNTS),paused_accounts=sorted(PAUSED),caption_text=text,
            rows=public_rows(rows),phase='publishing' if publish else 'plan_only')
        if targets is not None:
            report['selected_targets']=[dict(account=a,target=t) for a,t in targets]
        results=[]
        save_report(path,report,rows,results,state)
        for row in rows:
            print(row['account']+'/'+str(row['target']),row['name'],row['filename'] or '-',row['status'],row['reason'],flush=True)
        if not publish:
            print('只检查计划；没有生成文案、准备、启用或发布。报告：',path,flush=True)
            return 0
        backup=upload.ROOT/'backups'/('available-today-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True)
        for original in (upload.CONFIG,state_path,upload.ROOT/'common_caption_today.txt'):
            if original.is_file():
                (backup/original.name).write_bytes(original.read_bytes())
        for row in rows:
            if not row['eligible']:
                continue
            try:
                captions.apply([row['account']],text,target_filter={(row['account'],row['target'])})
            except Exception as error:
                row.update(eligible=False,status='invalid',reason=str(error).splitlines()[0][:300])
        report['rows']=public_rows(rows)
        save_report(path,report,rows,results,state)
        if any(row['eligible'] for row in rows):
            print('等待 61 秒，让本轮文案和素材稳定。',flush=True)
            for seconds in (30,31):
                time.sleep(seconds)
                print('文件稳定等待中。' if seconds==30 else '开始依次处理。',flush=True)
        try:
            for row in rows:
                if not row['eligible']:
                    continue
                result=dict(account=row['account'],target=row['target'],key=row['key'],filename=row['filename'],started_at=stamp())
                entry=row['entry']
                print('正在处理：',row['account'],row['target'],row['name'],row['filename'],flush=True)
                try:
                    state=upload.read_json(state_path,{})
                    validate_exact(entry,state,row,text)
                    if close_windows:
                        from diagnose_personal_identity import close_selected_window
                        close_selected_window(row['account'])
                    if not (entry.get('prepared_at') and entry.get('enabled')):
                        print('此目标首次使用：请检查预览画面、文案、Public 和 AI 设置；检查后按回车继续。',flush=True)
                        prepared=upload.run_entry(entry,state,state_path,False,filename=row['filename'],
                            ai_label_override=ai_label=='on',expected_job_key=row['key'])
                        if not prepared:
                            raise RuntimeError('没有完成首次准备，未启用或发布')
                        state=upload.read_json(state_path,{})
                        validate_exact(entry,state,row,text)
                        previous=copy.deepcopy(entry)
                        entry.update(prepared_at=stamp(),enabled=True)
                        try:
                            # A scoped run still preserves every unselected configuration row.
                            current=upload.read_json(upload.CONFIG,{})
                            matches=[e for e in current.get('targets',[]) if
                                     (e.get('account'),e.get('target'))==(entry['account'],entry['target'])]
                            if len(matches)!=1 or matches[0]!=previous:
                                raise ValueError('首次准备期间目标配置变化，未启用或发布')
                            matches[0].update(entry)
                            upload.save_json(upload.CONFIG,current)
                        except Exception:
                            entry.clear()
                            entry.update(previous)
                            raise
                        result['prepared_enabled_at']=stamp()
                    state=upload.read_json(state_path,{})
                    validate_exact(entry,state,row,text)
                    upload.run_entry(entry,state,state_path,True,filename=row['filename'],
                        ai_label_override=ai_label=='on',new_video_with_old_review=True,expected_job_key=row['key'])
                    result['status']='attempt_finished'
                except Exception as error:
                    result.update(status='needs_check',error=str(error).splitlines()[0][:500])
                    print('此目标保留记录并跳过，继续下一个：',result['error'],flush=True)
                results.append(result)
                state=upload.read_json(state_path,{})
                save_report(path,report,rows,results,state)
            report['phase']='attempts_finished'
        finally:
            state=upload.read_json(state_path,{})
            final=save_report(path,report,rows,results,state)
            print('\n本轮已配置目标的新素材结果：',flush=True)
            for row in final:
                print(row['account']+'/'+str(row['target']),row['filename'] or '-',row['status'],row['reason'],flush=True)
            print('本轮记录成功：',sum(row['status']=='published' for row in final),'；安排素材：',sum(bool(row['eligible']) for row in rows),flush=True)
            print('本轮报告：',path,flush=True)
            print('结果汇总：',path.with_suffix('.csv'),flush=True)
        eligible=[row for row in rows if row['eligible']]
        return 0 if eligible and not any(row['status']=='invalid' for row in rows) and all(
            state.get(row['key'],{}).get('status')=='published' for row in eligible) else 3


def main():
    parser=argparse.ArgumentParser(description='发布已有和新增账号中可处理的当前新素材，每目标最多一条')
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--ai-label',choices=['off','on'])
    parser.add_argument('--prepare-new',action='store_true',help='新增目标首次预览检查完成后自动启用并发布')
    parser.add_argument('--close-windows',action='store_true',help='正常请求关闭当前有新素材的账号窗口，不强制结束进程')
    parser.add_argument('--targets',help='仅处理指定目标，例如 fb17/personal,fb22/personal,fb23/personal')
    args=parser.parse_args()
    if args.targets:
        from diagnose_personal_identity import parse_target_pairs
        targets=parse_target_pairs(args.targets)
    else:
        targets=None
    return run(args.run,args.ai_label,args.prepare_new,args.close_windows,targets)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('批次已中断，保留已建立的任务记录，请先核对本轮报告。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',str(error).splitlines()[0],flush=True)
        raise SystemExit(1)
