"""A durable, single retry of recoverable before-Post failures from one new batch."""
import copy,re
from datetime import datetime,timezone
from pathlib import Path
import fb_upload as upload
import scheduled_material_batch as batch
from add_fb_accounts import locked

AUTO_RETRY_VERSION='1.1-immediate-aware'
SAFE_BEFORE_POST_RETRY_VERSION='1.2-network-and-prepost-timeouts'
POLICY='recoverable-before-post-once-v1'
CLAIMS_SCHEMA='automatic-before-post-retry-claims-v1'
DENY=re.compile(r'captcha|checkpoint|two[_ -]?(?:step|factor)|advanced protection|account.{0,32}(?:disabled|restricted|suspended)|restricted account|log[ -]?in|sign[ -]?in|session expired|2fa|安全验证|验证码|登录|账号限制|操作频繁|身份不一致|不匹配|不唯一|多个|文案.*(?:变化|缺少|为空)|原视频.*(?:变化|缺失)|配置.*(?:变化|重复)|冻结.*校验',re.I)
RECOVER=re.compile(r'net::ERR_(?:TIMED_OUT|CONNECTION_RESET|CONNECTION_CLOSED|CONNECTION_REFUSED|PROXY_CONNECTION_FAILED|NETWORK_CHANGED|INTERNET_DISCONNECTED)|发布前上传仍未完成或按钮不可用|Chrome 资料仍被占用|Target page, context or browser has been closed|菜单.*(?:未加载|未.*可用)|未找到新版 Describe your reel 描述框|视频尚未进入 Reel 编辑器|公共主页列表切换超时',re.I)
POINTER_STAGES={'open_reel_menu','select_exact_video','classic_next_1','classic_next_2','fill_caption','commit_classic_caption','modern_caption_audience_ai','ready_to_post'}
TIMEOUT_STAGES=POINTER_STAGES|{'open_target_profile','verify_identity','recover_loading_menu_before_file','wait_reel_editor','verify_selected_media','verify_public_audience','verify_ai_label'}
PROOF_FIELDS=('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at','review_reason','today_first_retry_used','previous_before_post_attempt')


def load_source(path):
    path=Path(path);path.resolve().relative_to((upload.ROOT/'logs').resolve())
    value=upload.read_json(path,{});payload=value.get('payload',{});checksum=batch.digest(payload)
    if (value.get('workflow')!='future-video-comments-v1' or value.get('auto_retry_policy')!=POLICY
            or payload.get('schema')!=batch.SCHEMA or value.get('sha256')!=checksum
            or not re.fullmatch(r'frozen-material-\d{4}-\d{2}-\d{2}-'+checksum[:16]+r'\.json',path.name)
            or payload.get('date')!=datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()
            or payload.get('ai_label') is not False or payload.get('include_fb10_pages') is not True
            or set(payload.get('excluded_accounts',[]))!={'fb16','fb18','fb21'}):
        raise ValueError('自动补发只接受本次当天明确启用的全新批次原清单')
    jobs=payload.get('jobs',[])
    if not jobs or len({j['key'] for j in jobs})!=len(jobs) or any(not batch.eligible(j,True) for j in jobs):raise ValueError('自动补发原清单的账号或素材范围异常')
    return path,value


def claims_document():
    path=upload.ROOT/'logs/automatic_before_post_retry_claims.json'
    value=upload.read_json(path,{'schema':CLAIMS_SCHEMA,'jobs':{}})
    if not isinstance(value,dict) or value.get('schema')!=CLAIMS_SCHEMA or not isinstance(value.get('jobs'),dict):raise ValueError('自动补发账本格式异常，保留原记录，未重新发放机会')
    return path,value


def decide(job,value,state,attempt,claims):
    if job['key'] in claims['jobs']:return False,'此视频已使用自动补发机会'
    if not isinstance(attempt,dict) or attempt.get('key')!=job['key'] or attempt.get('action')!='manual_required':return False,'本批首轮没有可恢复的失败尝试'
    since=datetime.fromisoformat(value['created_at']).timestamp()-5
    try:
        if datetime.fromisoformat(attempt['started_at']).timestamp()<since:return False,'失败尝试不属于本批次'
    except (KeyError,TypeError,ValueError):return False,'失败尝试缺少批次时间证据'
    record=state.get(job['key'])
    if record is not None:
        if (not isinstance(record,dict) or record.get('status')!='failed_before_post'
                or any(record.get(k) for k in PROOF_FIELDS)):return False,'已成功、已提交、待核实或已经重试，保留不重发'
        if ((record.get('account'),record.get('target'))!=(job['account'],job['target'])
                or upload.target_key(record.get('url',''))!=upload.target_key(job['url'])
                or str(record.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']
                or record.get('uploader_version') not in {'2.46','2.47'} or record.get('ai_label_requested') is not False):return False,'原任务身份或发布日志版本不满足自动补发要求'
        try:
            if datetime.fromisoformat(record['created']).timestamp()<since:return False,'任务早于本批次'
        except (KeyError,TypeError,ValueError):return False,'任务缺少本批次时间证据'
    if any(r.get('account')==job['account'] and r.get('status') in {'preparing','posting'} for r in state.values()):return False,'该账号仍有准备或提交中的任务，未关闭浏览器'
    reason=str(record.get('error','') if record else '') or str(attempt.get('error',''))
    stage=record.get('failure_stage','') if record else ''
    if DENY.search(reason):return False,'需要人工处理身份、安全验证或文件配置，未自动重试'
    recoverable=bool(RECOVER.search(reason))
    recoverable|=(bool(re.search(r'Timeout\s+\d+\s*ms\s+exceeded',reason,re.I)) and stage in TIMEOUT_STAGES)
    recoverable|=('intercepts pointer events' in reason and stage in POINTER_STAGES)
    recoverable|=('net::ERR_ABORTED' in reason and stage in {'open_target_profile','verify_identity'})
    if not recoverable:return False,'错误不在可恢复范围，保留给人工核实'
    return True,'首轮发布前的可恢复错误：'+reason.split('\n',1)[0][:260]


def checked_job(job):
    entry=batch.validate_job(job)
    selection=upload.named_job(entry,{},job['filename'])
    if not selection or selection[0]!=job['key'] or selection[3]!=job['caption_text']:raise ValueError('自动补发时原视频指纹或文案发生变化')
    return entry


def reserve(job,path,value,attempt):
    """batch.run holds both upload locks before this callback and before closing Chrome."""
    current_path,current=load_source(path)
    if current['sha256']!=value['sha256']:raise ValueError('原批次清单发生变化，未补发')
    _,claims=claims_document();state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    allowed,reason=decide(job,current,state,attempt,claims)
    if not allowed:raise ValueError('取消自动补发：'+reason)
    checked_job(job)
    ledger_path,claims=claims_document()
    if job['key'] in claims['jobs']:raise ValueError('自动补发机会已经使用')
    claims['jobs'][job['key']]=dict(account=job['account'],target=job['target'],filename=job['filename'],
        source_manifest=current_path.name,source_sha256=current['sha256'],reason=reason,
        reserved_at=datetime.now(timezone.utc).isoformat(),original_record=copy.deepcopy(state.get(job['key'])))
    upload.save_json(ledger_path,claims)  # Consume before browser/file selection, including on crash.


def run(path,output_dir=None):
    with locked():
        path,value=load_source(path)
        report_path=path.with_name(path.stem+'-results.json');first=upload.read_json(report_path,{})
        if first.get('manifest')!=path.name:raise ValueError('缺少本批首轮执行结果，未根据旧错误猜选补发目标')
        attempts=first.get('attempts',[]);latest={a['key']:a for a in attempts}
        if any(j['key'] not in latest for j in value['payload']['jobs']):raise ValueError('首轮尚未处理完本批清单，自动补发队列未启动')
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{});_,claims=claims_document()
        selected=[];decisions=[];first_attempts={}
        for job in value['payload']['jobs']:
            try:
                allow,reason=decide(job,value,state,latest.get(job['key']),claims)
                if allow:
                    checked_job(job);selected.append(copy.deepcopy(job));first_attempts[job['key']]=copy.deepcopy(latest[job['key']])
            except Exception as error:allow=False;reason=str(error) or type(error).__name__
            decisions.append(dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],eligible=allow,reason=reason))
        audit=upload.ROOT/'logs'/('automatic-retry-audit-'+value['sha256'][:16]+'.json')
        upload.save_json(audit,dict(source_manifest=path.name,policy=POLICY,decisions=decisions))
        if not selected:
            print('自动补发队列为空；成功、已提交和待核实任务保留不重发。',flush=True)
            return []
        payload=copy.deepcopy(value['payload']);payload.update(jobs=selected,run_kind='automatic-safe-retry-v1',source_manifest=path.name,source_sha256=value['sha256'])
        checksum=batch.digest(payload);queue_path=upload.ROOT/'logs'/('automatic-retry-'+payload['date']+'-'+checksum[:16]+'.json')
        queue=dict(payload=payload,sha256=checksum,created_at=datetime.now(timezone.utc).isoformat(),report_format='text',issues=[],comment_timing=value.get('comment_timing'))
        upload.save_json(queue_path,queue)
    print('首轮视频全部处理完；现在仅自动补发可恢复的发布前失败：',len(selected),'条，每条最多一次。',flush=True)
    try:
        immediate=value.get('comment_timing')=='immediate-after-publication-v1'
        batch.run(queue_path,output_dir,before_job=lambda job:reserve(job,path,value,first_attempts[job['key']]),defer_comments=not immediate,retry_before_post=True)
    finally:
        second=upload.read_json(queue_path.with_name(queue_path.stem+'-results.json'),{}).get('attempts',[])
        _,latest_claims=claims_document()
        for attempt in second:
            claim=latest_claims['jobs'].get(attempt['key'],{})
            if claim.get('source_sha256')==value['sha256']:
                attempt.update(attempt_phase='automatic_retry',automatic_retry_number=1)
        # Keep one original batch report; new retry attempts appear after their first attempt.
        batch.results(path,value,attempts+second,output_dir,final=False)
    return selected
