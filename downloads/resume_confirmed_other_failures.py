"""Source/key-bound reconciliation and one explicit retry, with failure history."""
import argparse
import copy
import csv
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import fb_upload as upload
import confirm_selected_round as confirmations
import publish_fb10_pages_direct as direct
from add_fb_accounts import locked
from retry_current_verified_absent import retry_one

SOURCE=None
PAIRS=(('fb01','page01'),('fb06','page01'),('fb09','personal'),('fb23','personal'))
BOUND={}
CLAIM='user-resume-20261029-v1-2-35'
SLOW_UPLOAD_CLAIM='fb01-upload-wait-fresh-check-20261029-v1'


def now():
    return datetime.now().astimezone().isoformat()


def explanation(record,error):
    status=record.get('status','missing')
    text=error.lower()
    if status=='published':
        return '已确认发布成功；旧错误仅作为历史保留','已有成功记录，不重复发布'
    if 'chrome' in text and ('资料仍被占用' in error or 'profile is in use' in text):
        return '该账号 Chrome 资料被占用，本次未启动发布','先正常关闭这个账号的全部 Chrome 窗口；不强制终止其他浏览器，不删除资料或防重发记录'
    if 'advanced protection' in text or 'create passkey' in text:
        reason='账号安全提示阻断自动操作'
        action='由账号本人完成安全提示；程序检测到提示即停止，不代改安全设置'
    elif 'subtree intercepts pointer events' in text or 'intercepts pointer events' in text:
        reason='页面其他元素挡住按钮，鼠标点击没有完成'
        action='个人号优先使用已核验发帖区的 Reel；菜单内限定唯一按钮，必要时键盘激活；未知弹窗停止'
    elif '身份' in error or 'identity' in text:
        reason='未能核验当前发布身份'
        action='精确切换配置目标后重新核验；无法确认就停止，不用其他身份代发'
    elif 'post audience' in text or 'public' in text or '公开' in error:
        reason='公开受众设置未能完成核验'
        action='只在实际界面确认 Public 后继续；缺少 Public 时手动检查账号受众限制'
    elif '回执' in error or 'receipt' in text or record.get('review_reason')=='publication_receipt_timeout':
        reason='提交后未识别到成功回执，结果待核实'
        action='保留防重发记录；只有用户核实原视频不存在才允许一次补发'
    elif 'next' in text or 'settings' in text or 'edit' in text:
        reason='视频编辑步骤没有按预期进入设置页面'
        action='等待并验证 Edit 到 Settings 的实际切换；仅在确认仍为 Edit 时补点一次 Next'
    elif 'timeout' in text or 'timed out' in text:
        reason='页面操作超时；具体原因需结合完整日志和截图'
        action='记录实际阶段和完整错误；不把超时当作成功，也不无限重试'
    else:
        reason='操作未完成；完整原因已保留，需结合当前诊断核实' if error else '没有新的失败证据'
        action='保留原始证据，避免按旧错误猜测本次原因'
    if status in {'needs_review','posting','preparing'}:
        action='当前结果不明，禁止自动再次发布。'+action
    return reason,action


def latest_error(path,report,row,record):
    key=row['key']
    # Prefer errors from the actual current attempt, never silently reuse the
    # first direct driver's error after a later retry replaced this job.
    created=record.get('created','')
    try:
        created_at=datetime.fromisoformat(created).timestamp()
    except (ValueError,TypeError):
        created_at=0
    core=upload.ROOT/'logs'/('review-'+key[:12]+'-error.txt')
    repairs=[r for r in report.get('repair_results',[]) if r.get('key')==key and r.get('error')]
    candidates=[]
    if core.is_file() and core.stat().st_mtime>=created_at-2:
        candidates.append((core.stat().st_mtime,core.read_text(encoding='utf-8-sig'),core.name))
    if repairs:
        try:
            attempted=datetime.fromisoformat(repairs[-1]['attempted_at']).timestamp()
        except (ValueError,TypeError,KeyError):
            attempted=created_at
        candidates.append((attempted,repairs[-1]['error'],'repair_results/latest'))
    if candidates:
        _,error,source=max(candidates,key=lambda item:item[0])
        return error,source
    original=path.with_name(path.stem+'-'+row['account']+'-'+row['target']+'-error.txt')
    if original.is_file() and not any(r.get('key')==key for r in report.get('repair_results',[])):
        return original.read_text(encoding='utf-8-sig'),original.name
    return record.get('error',''),'publish_state/error'


def snapshot(path,report,row,phase,extra_error=None):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    record=state.get(row['key'],{})
    if (record.get('account'),record.get('target'))!=(row['account'],row['target']):
        raise ValueError('任务记录与原目标不一致，未记录或重试其他任务')
    error,source=latest_error(path,report,row,record)
    if extra_error is not None:
        error,source=extra_error,'current_repair_attempt'
    reason,prevention=explanation(record,error)
    stage=record.get('failure_stage','unknown')
    if record.get('status')=='published':
        stage='completed'
    elif 'chrome' in error.lower() and ('资料仍被占用' in error or 'profile is in use' in error.lower()):
        stage='preflight_profile_in_use'
    event=dict(at=now(),phase=phase,account=row['account'],target=row['target'],key=row['key'],
        filename=row['filename'],status=record.get('status'),failure_stage=stage,
        uploader_version=record.get('uploader_version'),error_source=source,error=error,
        reason=reason,prevention=prevention)
    ledger=upload.ROOT/'logs/publication_failure_history.json'
    history=upload.read_json(ledger,dict(schema='publication-failure-history-v1',events=[]))
    if history.get('schema')!='publication-failure-history-v1' or not isinstance(history.get('events'),list):
        raise ValueError('失败历史格式异常，未覆盖')
    fingerprint=hashlib.sha256(json.dumps({k:v for k,v in event.items() if k!='at'},sort_keys=True).encode()).hexdigest()
    if not any(e.get('fingerprint')==fingerprint for e in history['events']):
        history['events'].append(dict(event,fingerprint=fingerprint))
        upload.save_json(ledger,history)
    return event


def export(path,report,rows,output_dir):
    destination=Path(output_dir) if output_dir else upload.ROOT/'logs'
    if not destination.is_dir():
        raise ValueError('输出目录不存在')
    events=[snapshot(path,report,row,'final') for row in rows]
    filename='发布失败原因与本次补发-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    fields=['account','target','filename','status','failure_stage','reason','prevention']
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
    writer.writeheader();writer.writerows(events)
    csv_data=stream.getvalue().encode('utf-8-sig')
    (destination/(filename+'.csv')).write_bytes(csv_data)
    with zipfile.ZipFile(destination/(filename+'.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('current-results.csv',csv_data)
        archive.writestr('current-evidence.json',json.dumps(events,ensure_ascii=False,indent=2).encode('utf-8'))
        for event in events:
            prefix=event['account']+'-'+event['target']
            archive.writestr(prefix+'-latest-error.txt',event['error'].encode('utf-8'))
            shot=upload.ROOT/'logs'/('review-'+event['key'][:12]+'.png')
            if shot.is_file() and event['status']!='published':
                archive.write(shot,prefix+'-current-review.png')
    print('\n本次四个目标最终状态：',flush=True)
    for event in events:
        print(event['account']+'/'+event['target'],event['filename'],event['status'],event['reason'],flush=True)
    print('原因和规避措施：',destination/(filename+'.csv'),flush=True)
    print('若仍失败，请上传这个完整新诊断包：',destination/(filename+'.zip'),flush=True)
    return events


def run(fb06_verified_published=False,fb01_verified_absent=False,output_dir=None,close_windows=False,source_report=None,
        also_verified_published=(),fresh_fb01_verification=False):
    if not fb06_verified_published or not fb01_verified_absent:
        raise ValueError('此工具只能使用用户本次已明确确认的 fb06 成功、fb01 未发布结果')
    if upload.VERSION not in {'2.35','2.36'}:
        raise ValueError('需先安装配套上传核心 2.35')
    if fresh_fb01_verification and upload.VERSION!='2.36':
        raise ValueError('本次最新核验补发需先安装慢上传修复 2.36')
    extra=set(also_verified_published)
    if len(extra)!=len(also_verified_published) or not extra.issubset({('fb09','personal'),('fb23','personal')}):
        raise ValueError('本次追加成功核实只接受明确、不重复的 fb09/personal、fb23/personal')
    confirmed={('fb06','page01')} | extra
    with locked():
        path,report=confirmations.load_expanded_report(source_report or SOURCE)
        if report.get('schema')!='other-accounts-direct-publication-v1':
            raise ValueError('原批次类型不匹配')
        rows=[]
        config=upload.read_json(upload.CONFIG,{})
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        for pair in PAIRS:
            key=BOUND.get(pair)
            found=[r for r in report['rows'] if (r.get('account'),r.get('target'))==pair]
            if len(found)!=1 or (key is not None and found[0].get('key')!=key):
                raise ValueError('原批次素材指纹不匹配：'+'/'.join(pair))
            confirmations.confirmation_plan(config,state,report,[pair])
            rows.append(copy.deepcopy(found[0]))
        for row in rows:
            snapshot(path,report,row,'before_user_reconciliation')
    # Only user-confirmed exact source jobs; success is never inferred from a timeout.
    confirmations.confirm(None,[pair for pair in PAIRS if pair in confirmed],True,source_report=path.name)
    try:
        for row in rows:
            pair=row['account'],row['target']
            if pair in confirmed:
                continue
            result=dict(account=pair[0],target=pair[1],key=row['key'],filename=row['filename'],
                repair_version=upload.VERSION,attempted_at=now(),user_verified_absent=pair==('fb01','page01'))
            if pair==('fb01','page01') and fresh_fb01_verification:
                result['absence_verified_after_latest_attempt']=True
            error=None
            print('\n本次仅补发原视频：','/'.join(pair),row['filename'],flush=True)
            try:
                claim=SLOW_UPLOAD_CLAIM if pair==('fb01','page01') and fresh_fb01_verification else CLAIM
                done=retry_one(pair,path,report,verified=pair==('fb01','page01'),confirmation_id=claim,
                    direct_publication=True,close_windows=close_windows,before_post_only=pair!=('fb01','page01'))
                result['attempt']='finished' if done is not False else 'skipped'
            except KeyboardInterrupt:
                result.update(attempt='interrupted',error='用户中断，保留任务和防重复记录')
                raise
            except Exception as failure:
                error=str(failure)
                result.update(attempt='stopped',error=error)
                print('此目标停止，保留记录后继续：',error.splitlines()[0],flush=True)
            finally:
                with locked():
                    current=upload.read_json(path,{})
                    if (current.get('rows')!=report['rows'] or current.get('schema')!=report['schema']
                        or current.get('caption_text')!=report['caption_text'] or current.get('ai_label')!=report['ai_label']):
                        raise ValueError('原批次报告变化，未覆盖')
                    current.setdefault('repair_results',[]).append(result)
                    direct.save(path,current,current['rows'],current.get('results',[]))
                    snapshot(path,current,row,'after_retry',error)
    finally:
        with locked():
            current=upload.read_json(path,{})
            events=export(path,current,rows,output_dir)
    return 0 if all(e['status']=='published' for e in events) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='按本次用户核实结果补记 fb06，只补发 fb01、fb09、fb23 原视频')
    parser.add_argument('--source-report',required=True)
    parser.add_argument('--fb06-verified-published',action='store_true')
    parser.add_argument('--fb01-verified-absent',action='store_true')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--close-windows',action='store_true')
    parser.add_argument('--also-verified-published',default='',
        help='仅用户已核实成功时追加：fb09/personal,fb23/personal；这些目标只补记，不发布')
    parser.add_argument('--fb01-verified-absent-after-latest-attempt',action='store_true',
        help='仅在检查最新补发之后的 Facebook 页面，确认原视频仍不存在时使用；固定许可只使用一次')
    args=parser.parse_args()
    try:
        extra=tuple(tuple(value.split('/')) for value in args.also_verified_published.split(',')) if args.also_verified_published else ()
        raise SystemExit(run(args.fb06_verified_published,args.fb01_verified_absent,args.output_dir,args.close_windows,args.source_report,extra,args.fb01_verified_absent_after_latest_attempt))
    except KeyboardInterrupt:
        print('已中断；保留状态，核对实际发布结果后再处理。',flush=True)
        raise SystemExit(130)
    except Exception as failure:
        print('STOP：',failure,flush=True)
        raise SystemExit(1)
