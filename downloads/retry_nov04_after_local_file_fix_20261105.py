"""One repaired retry of the exact Nov-4 failed batch, then verified comments."""
import copy,re,shutil,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import actual_reels_comment_lookup as actual
import normal_chrome_batch as normal
import local_file_input as local
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

PREFIX='d6707ad5'
GRANT='nov04-repaired-local-files-once-20261105'
PROOF=('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at')


def source():
    paths=[p for p in (upload.ROOT/'logs').glob('frozen-material-2026-11-04-'+PREFIX+'*.json')
           if re.fullmatch(r'frozen-material-2026-11-04-[a-f0-9]{16}\.json',p.name)]
    if len(paths)!=1:raise ValueError('没有唯一的11月4日d6707ad5原批次，未选择今天新素材')
    path=paths[0];value=upload.read_json(path,{});payload=value.get('payload',{});jobs=payload.get('jobs',[]);checksum=batch.digest(payload)
    if (value.get('sha256')!=checksum or not checksum.startswith(PREFIX) or not path.stem.endswith(checksum[:16])
            or payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-11-04'
            or payload.get('ai_label') is not False or payload.get('include_fb10_pages') is not True
            or set(payload.get('excluded_accounts',[]))!={'fb16','fb18','fb21'} or payload.get('comment_text')!=daily.COMMENT
            or len(jobs)!=30 or {(j.get('account'),j.get('target')) for j in jobs}!=daily.EXPECTED_PAIRS
            or len({j.get('key') for j in jobs})!=30 or any(not re.fullmatch(r'[a-f0-9]{64}',str(j.get('key',''))) for j in jobs)
            or value.get('report_format')!='text'):raise ValueError('原30条视频清单校验失败')
    report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if report.get('manifest')!=path.name or not isinstance(report.get('attempts'),list):raise ValueError('原批次结果不匹配')
    return path,value,copy.deepcopy(jobs)


def claims(value):
    path=upload.ROOT/'logs'/(GRANT+'-claims.json')
    result=upload.read_json(path,dict(grant=GRANT,source_sha256=value['sha256'],jobs={}))
    if (not isinstance(result,dict) or result.get('grant')!=GRANT or result.get('source_sha256')!=value['sha256']
            or not isinstance(result.get('jobs'),dict)):raise ValueError('修复后补发账本异常，未重置机会')
    return path,result


def has_post_proof(row):
    if isinstance(row,list):return any(has_post_proof(v) for v in row)
    if not isinstance(row,dict):return False
    return any(row.get(k) for k in PROOF) or any(has_post_proof(v) for v in row.values() if isinstance(v,(dict,list)))


def validate(job,state,ledger):
    row=state.get(job['key'])
    if (not isinstance(row,dict) or (row.get('account'),row.get('target'))!=(job['account'],job['target'])
            or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
            or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):raise ValueError('当前任务与原视频不一致')
    if row.get('status')=='published':return None,'published'
    if row.get('status')!='failed_before_post' or has_post_proof(row):raise ValueError('已有提交、成功线索或待核实，保留不重发')
    if row.get('uploader_version')!='2.47' or row.get('ai_label_requested') is not False:raise ValueError('原任务版本或实拍记录不匹配')
    prior=ledger['jobs'].get(job['key'])
    if prior is not None:
        if (not isinstance(prior,dict) or prior.get('phase') not in {'reserved','not_started'}
                or row not in (prior.get('original_record'),prior.get('replacement_record'))):
            raise ValueError('本次修复后补发已建立新任务，不额外重复提交')
    if any(r.get('account')==job['account'] and r.get('status') in {'preparing','posting'} for r in state.values()):raise ValueError('该账号另有进行中任务，未关闭浏览器')
    entry=batch.validate_job(job)
    selected=upload.named_job(entry,{k:v for k,v in state.items() if k!=job['key']},job['filename'])
    if not selected or selected[0]!=job['key'] or selected[3]!=job['caption_text']:raise ValueError('原视频或原文案发生变化')
    return dict(entry,enabled=True,auto_switch_personal=True,_authorized_comment_text=daily.COMMENT),'ready'


def reserve(job,state,path,ledger):
    entry,status=validate(job,state,ledger)
    if status=='published':return entry,None
    old=copy.deepcopy(state[job['key']]);prior=ledger['jobs'].get(job['key'])
    if prior is not None:
        original=copy.deepcopy(prior['original_record']);replacement=copy.deepcopy(prior['replacement_record'])
    else:
        original=old
        replacement={k:copy.deepcopy(old[k]) for k in ('account','target','url','video','caption','created','uploader_version') if k in old}
        replacement.update(status='failed_before_post',ai_label_requested=False,repair_authorization=GRANT,repair_previous_attempt=original)
    item=dict(phase='reserved',account=job['account'],target=job['target'],filename=job['filename'],
              reserved_at=datetime.now(timezone.utc).isoformat(),original_record=original,replacement_record=replacement)
    ledger['jobs'][job['key']]=item;upload.save_json(path,ledger)  # Durable grant before replacing the old guard.
    state[job['key']]=replacement;upload.save_json(upload.ROOT/'logs/publish_state.json',state)
    return entry,replacement


def settle(job,replacement,path,ledger):
    state_path=upload.ROOT/'logs/publish_state.json';current=upload.read_json(state_path,{})
    row=current.get(job['key']);item=ledger['jobs'][job['key']]
    if row is None or row==replacement:
        current[job['key']]=copy.deepcopy(item['original_record']);upload.save_json(state_path,current)
        item['phase']='not_started'
    else:item['phase']='consumed'
    item['result_status']=current[job['key']].get('status','unknown');upload.save_json(path,ledger)


def refresh(path,value,attempt=None,final=False):
    prior=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if prior.get('manifest')!=path.name or not isinstance(prior.get('attempts'),list):raise ValueError('原结果报告变化，未覆盖')
    return batch.results(path,value,prior['attempts']+([attempt] if attempt else []),None,final=final)


def self_check(job):
    from playwright.sync_api import sync_playwright
    entry=dict(daily.configured(job),_local_file_selfcheck=True)
    close_selected_window(entry['account'])
    with sync_playwright() as playwright:
        context=upload.launch_context(playwright,entry)
        try:local.self_check(context,job)
        finally:context.close()


def execute():
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!='2026-11-05':raise ValueError('本指令仅限11月5日补发11月4日原批次')
    if upload.VERSION!='2.47' or getattr(normal,'LOCAL_FILE_INPUT_COMPATIBILITY','')!=local.VERSION:raise ValueError('本机大文件上传修复尚未安装')
    state_path=upload.ROOT/'logs/publish_state.json'
    with locked(),daily.keep_awake():
        path,value,jobs=source();ledger_path,ledger=claims(value);state=upload.read_json(state_path,{})
        eligible=[]
        for index,job in enumerate(jobs,1):
            if index==1 or index%5==0:print('正在核对11月4日原视频：',index,'/',len(jobs),'；核对内容指纹和原文案。',flush=True)
            try:
                if validate(job,state,ledger)[1]=='ready':eligible.append(job)
            except Exception as error:print('暂不重发：',job['account'],job['target'],job['filename'],'；',str(error).split('\n',1)[0],flush=True)
        original=upload.launch_context;upload.launch_context=normal.launcher_for_jobs(jobs)
        original_finder=daily.find_published
        try:
            if eligible:
                large=next((j for j in eligible if j.get('video_size',0)>50*1024*1024),eligible[0])
                print('先做本机原视频选择自检；通过后才启动这批补发。',flush=True);self_check(large)
                backup=upload.ROOT/'backups'/(GRANT+'-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
                for file in (state_path,path,path.with_name(path.stem+'-results.json'),upload.ROOT/'logs/automatic_before_post_retry_claims.json',upload.ROOT/'logs/video_comments.json'):
                    if file.is_file():shutil.copy2(file,backup/file.name)
                print('修复后可补发：',len(eligible),'条；原尝试和自动补发记录保留；本次每条仅再尝试一次。',flush=True)
            for job in jobs:
                state=upload.read_json(state_path,{});attempt=None;replacement=None
                try:
                    entry,status=validate(job,state,ledger)
                    if status=='published':continue
                    close_selected_window(entry['account'])
                    if upload.read_json(state_path,{})!=state:raise ValueError('关闭窗口期间记录变化，未覆盖')
                    entry,replacement=reserve(job,state,ledger_path,ledger)
                    attempt=dict(account=job['account'],target=job['target'],key=job['key'],started_at=datetime.now(timezone.utc).isoformat(),action='manual_required',attempt_phase=GRANT)
                    print('\n修复后补发原视频：',job['account'],job['target'],job['filename'],flush=True)
                    upload.run_entry(entry,state,state_path,True,filename=job['filename'],ai_label_override=False,
                                     expected_job_key=job['key'],preserve_old_review_for_exact_job=True,retry_before_post=True,defer_comments=True)
                    attempt['action']='finished'
                except KeyboardInterrupt:raise
                except Exception as error:
                    message=(str(error) or type(error).__name__)[:2000]
                    if attempt is not None:attempt['error']=message
                    print('此条保留结果，继续其他原视频：',job['account'],job['target'],message.split('\n',1)[0],flush=True)
                finally:
                    if replacement is not None:settle(job,replacement,ledger_path,ledger)
                    refresh(path,value,attempt)
            state=upload.read_json(state_path,{});published=[j for j in jobs if state.get(j['key'],{}).get('status')=='published']
            if published:
                print('原视频补发阶段结束；现在仅评论本批已成功的视频。',flush=True)
                daily.find_published=actual.make_finder(published,True)
                work=dict(payload=dict(date='2026-11-04',jobs=published))
                daily.backfill(work,None,only_keys={j['key'] for j in published},already_locked=True,future_only=True,reporter=lambda *_:refresh(path,value))
            rows=refresh(path,value,final=True)
        finally:upload.launch_context=original;daily.find_published=original_finder
    return 0 if all(r['video_status']=='published' for r in rows) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止；原记录、补发意图和新提交结果保留，重跑不会重复提交。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
