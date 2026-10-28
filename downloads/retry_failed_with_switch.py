"""Retry exact before-Post failures from one bound round after manual actor repair."""
import argparse
import re
import sys
from datetime import datetime

import fb_upload as upload
import publish_fourteen_current as driver
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window,parse_target_pairs
from publish_current_inbox import publish_current


def load_bound_round(round_start):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',round_start):
        raise ValueError('批次时间格式应为 YYYY-MM-DDTHH:MM:SS')
    matches=[]
    for path in (upload.ROOT/'logs').glob('current-audit-*.json'):
        report=upload.read_json(path,{})
        if (report.get('schema')=='fourteen-current-publication-v1' and report.get('phase')!='plan_only'
                and report.get('created','')[:19]==round_start):
            matches.append((path,report))
    if len(matches)!=1:
        raise ValueError('没有唯一匹配的指定发布批次，未用其他批次代替')
    path,report=matches[0]
    rows=report.get('rows',[])
    if len(rows)!=14 or {(r.get('account'),r.get('target')) for r in rows}!=set(driver.TARGETS):
        raise ValueError('指定批次的原 14 个目标不完整')
    if report.get('ai_label') not in {'off','on'} or not report.get('caption_text','').strip():
        raise ValueError('指定批次缺少明确的 AI 标签或原文案')
    return path,report


def validate_job(config,state,row,caption):
    key=row.get('key')
    if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{64}',key):
        raise ValueError('该目标没有本轮确切素材指纹')
    record=state.get(key)
    if not isinstance(record,dict) or record.get('status')!='failed_before_post':
        return None
    pair=(row['account'],row['target'])
    found=[e for e in config.get('targets',[]) if (e.get('account'),e.get('target'))==pair]
    if len(found)!=1:
        raise ValueError('目标配置缺失或重复')
    entry=found[0]
    upload.validate_entry(entry)
    if ((record.get('account'),record.get('target'))!=pair
            or upload.target_key(record.get('url',''))!=upload.target_key(entry['url'])):
        raise ValueError('任务与当前主页身份不一致')
    if any(record.get(field) for field in ('permalink','success_message','confirmation_method')):
        raise ValueError('失败记录包含成功证据，未安排重试')
    if not entry.get('prepared_at') or not entry.get('enabled'):
        raise ValueError('该目标尚未准备或启用')
    name=str(record.get('video','')).replace('\\','/').rsplit('/',1)[-1]
    if name!=row.get('filename'):
        raise ValueError('本轮报告与任务文件名不一致')
    validation=dict(state)
    validation.pop(key)
    selected=upload.named_job(entry,validation,name)
    if not selected or selected[0]!=key or selected[3]!=caption:
        raise ValueError('本轮原视频已变化、缺失或文案与原批次不同')
    return entry


def repair_identity(entry,read=input,auto_first=False,automatic_only=False):
    if automatic_only and not auto_first:
        raise ValueError('automatic_only requires auto_first')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        context=upload.launch_context(playwright,entry)
        try:
            page=context.pages[0] if context.pages else context.new_page()
            upload.navigate_profile(page,entry['url'])
            if auto_first:
                print('先自动切换并核对公共主页身份：',entry['name'],flush=True)
                try:
                    proof=upload.ensure_identity(page,entry)
                except Exception as error:
                    print('自动身份核验未通过：',str(error).splitlines()[0],flush=True)
                    # Local UI evidence lets us adapt an unknown avatar label
                    # without collecting raw DOM, cookies, or form values.
                    try:
                        from capture_profile_switch_ui import capture
                        import zipfile
                        folder=upload.ROOT/'logs'/('auto-switch-'+entry['account']+'-'+entry['target']+'-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
                        capture(page,folder,'automatic-failure')
                        output=folder.with_suffix('.zip')
                        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
                            for item in folder.iterdir():
                                if item.is_file():
                                    archive.write(item,item.name)
                        print('自动切换诊断：',output,flush=True)
                    except Exception:
                        print('未能保存切换界面诊断，原任务记录保留。',flush=True)
                    if automatic_only:
                        raise RuntimeError('自动身份核验未通过，本页已跳过，不等待人工输入：'+str(error).splitlines()[0]) from error
                    print('本页改为手动处理；SKIP 可跳过后继续其他主页。',flush=True)
                else:
                    proof['checked_at']=datetime.now().astimezone().isoformat()
                    upload.save_json(upload.ROOT/'logs'/('identity-'+entry['account']+'-'+entry['target']+'.json'),proof)
                    print('自动切换及身份核验通过，无需输入 READY。',flush=True)
                    return True
            while True:
                print('请在此浏览器右上角头像菜单切到：',entry['name'],entry['url'],flush=True)
                print('切好后回到此窗口输入 READY；跳过当前目标输入 SKIP；结束批次输入 CANCEL。',flush=True)
                try:
                    answer=read('READY / SKIP / CANCEL: ').strip().upper()
                except EOFError:
                    raise KeyboardInterrupt from None
                if answer=='CANCEL':
                    raise KeyboardInterrupt
                if answer=='SKIP':
                    return False
                if answer!='READY':
                    continue
                try:
                    # Manual actor repair can land at another route; reopen the
                    # configured URL and retain the ordinary identity proof rules.
                    upload.navigate_profile(page,entry['url'])
                    proof=upload.ensure_identity(page,entry)
                    proof['checked_at']=datetime.now().astimezone().isoformat()
                    upload.save_json(upload.ROOT/'logs'/('identity-'+entry['account']+'-'+entry['target']+'.json'),proof)
                    return True
                except Exception as error:
                    print('身份尚未核验通过：',str(error).splitlines()[0],flush=True)
                    print('请继续手动切换或处理页面加载后再输入 READY；也可 SKIP。',flush=True)
        finally:
            context.close()


def save_results(path,report):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    results=report.get('results',[])+report.get('resume_results',[])
    report['final_rows']=driver.final_rows(report['rows'],state,results)
    errors={r.get('key'):r.get('error') for r in results if r.get('error')}
    for row in report['final_rows']:
        if row.get('status')=='failed_before_post' and errors.get(row.get('key')):
            row['reason']=errors[row['key']]
    upload.save_json(path,report)
    driver.save_csv(path.with_suffix('.csv'),report['final_rows'])
    return state


def retry(round_start,targets,publish=False,close_windows=False,assist_targets=()):
    with locked():
        path,report=load_bound_round(round_start)
        config=upload.read_json(upload.CONFIG,{})
        driver.validate_scope(config)
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        caption=report['caption_text'].strip()
        common=(upload.ROOT/'common_caption_today.txt').read_text(encoding='utf-8-sig').strip()
        if common!=caption:
            raise ValueError('当前统一文案与指定批次不同，未更换原任务文案')
        jobs=[]
        for pair in targets:
            found=[r for r in report['rows'] if (r['account'],r['target'])==pair]
            if len(found)!=1:
                raise ValueError('选定目标不在本轮报告中')
            if validate_job(config,state,found[0],caption) is not None:
                jobs.append(dict(found[0]))
            else:
                print('保留当前状态，不重发：','/'.join(pair),flush=True)
        if publish:
            backup=upload.ROOT/'backups'/('manual-switch-retry-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            for original in (path,upload.CONFIG,upload.ROOT/'logs/publish_state.json'):
                upload.save_json(backup/original.name,upload.read_json(original,{}))
    print('续发来源：',path,'；可处理：',len(jobs),'个；沿用 AI 标签：',report['ai_label'],flush=True)
    for row in jobs:
        print(row['account']+'/'+row['target'],row['filename'],row['key'][:12],flush=True)
    if not publish:
        print('仅检查计划，未打开浏览器或改变记录。',flush=True)
        return 0
    report.setdefault('resume_results',[])
    try:
        for row in jobs:
            result=dict(account=row['account'],target=row['target'],key=row['key'],filename=row['filename'],
                        attempted_at=datetime.now().astimezone().isoformat(),method='manual_actor_repair_before_safe_retry')
            try:
                with locked():
                    config=upload.read_json(upload.CONFIG,{})
                    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
                    entry=validate_job(config,state,row,caption)
                    if entry is None:
                        continue
                    if close_windows:
                        close_selected_window(row['account'])
                    if not repair_identity(entry):
                        result.update(attempt='skipped',error='用户跳过当前身份切换，原失败记录保留')
                    else:
                        result['identity_repaired']=True
                if result.get('identity_repaired'):
                    options={'pause_before_reel':True} if (row['account'],row['target']) in assist_targets else {}
                    publish_current(row['account'],row['target'],report['ai_label'],retry_before_post=True,
                                    expected_key=row['key'],**options)
                    result['attempt']='finished'
            except Exception as error:
                result.update(attempt='stopped',error=str(error).splitlines()[0][:500])
                print('此目标保留记录并继续：',result['error'],flush=True)
            report['resume_results'].append(result)
            with locked():
                save_results(path,report)
    finally:
        with locked():
            actual=save_results(path,report)
        print('\n指定目标的本轮实际结果：',flush=True)
        selected=set(targets)
        for row in report['final_rows']:
            if (row['account'],row['target']) in selected:
                print(row['account']+'/'+row['target'],row['filename'],row['status'],row['reason'],flush=True)
        print('本轮汇总：',path.with_suffix('.csv'),flush=True)
    return 0 if all(actual.get(row.get('key'),{}).get('status')=='published' for row in report['rows']
                    if (row['account'],row['target']) in selected) else 3


def main():
    parser=argparse.ArgumentParser(description='切换身份后仅重试指定批次的明确发布前失败视频')
    parser.add_argument('--round-start',required=True)
    parser.add_argument('--targets',required=True)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--close-windows',action='store_true')
    parser.add_argument('--assist-targets',help='这些目标使用已有菜单协助暂停，例如 fb09/personal')
    args=parser.parse_args()
    targets=parse_target_pairs(args.targets)
    assist=parse_target_pairs(args.assist_targets) if args.assist_targets else []
    if not set(assist)<=set(targets):
        raise ValueError('菜单协助目标必须包含在本次续发目标中')
    return retry(args.round_start,targets,args.run,args.close_windows,assist)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('续发已结束，保留已有任务记录，请核对本轮报告。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',str(error).splitlines()[0],flush=True)
        raise SystemExit(1)
