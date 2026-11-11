"""One bounded extra comment pass; submitted outcomes are verified without resending."""
import re
from datetime import datetime,timezone
from pathlib import Path

import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import actual_reels_comment_lookup as actual
import safe_video_comments as comments
from add_fb_accounts import locked

VERSION='1.0-scoped-retry-readonly-reconcile'
SCHEMA='automatic-comment-retry-claims-v1'
PENDING={'sending','verifying','needs_review'}
DONE={'sent','already_present'}
DENY=re.compile(r'captcha|checkpoint|two[_ -]?(?:step|factor)|advanced protection|temporarily blocked|comments? (?:are|is) (?:disabled|restricted)|account.{0,32}(?:disabled|restricted|suspended)|安全验证|验证码|账号限制|操作频繁|评论.{0,8}(?:禁止|受限)|log[ -]?in|sign[ -]?in|session expired|2fa',re.I)


def candidates(value,state,ledger,claims):
    selected=[];decisions=[];text=value['payload']['comment_text']
    for job in value['payload']['jobs']:
        row=state.get(job['key'],{})
        key=comments.hashlib.sha256((job['key']+'\0'+comments.text_hash(text)).encode()).hexdigest()
        item=ledger.get(key,{})
        reason='';mode=''
        if row.get('status')!='published':reason='视频尚未确认成功，先核实视频；不补发视频或发送评论'
        elif row.get('comment_status') in DONE or item.get('status') in DONE:reason='评论已成功，保留不重发'
        elif key in claims['jobs']:reason='本条已进入过自动补评阶段，保留原处理结果'
        elif row.get('comment_status') in PENDING or item.get('status') in PENDING:mode='verify_only'
        elif DENY.search(str(row.get('comment_error',''))+' '+str(item.get('error',''))):reason='需要处理登录、安全验证或平台限制，未自动重试'
        else:mode='retry_before_send'
        if mode:selected.append((job,key,mode))
        decisions.append(dict(account=job['account'],target=job['target'],key=job['key'],mode=mode or 'skip',reason=reason))
    return selected,decisions


def run(path,reporter=None):
    path=Path(path);path.resolve().relative_to((upload.ROOT/'logs').resolve())
    value=upload.read_json(path,{})
    from publish_priority_batch import validate
    date=datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat();validate(path,value,date)
    if value['payload'].get('comment_retry_policy')!=VERSION:raise ValueError('旧批次没有启用之后的自动补评规则，不补历史评论')
    if comments.COMMENT_RECOVERY_VERSION!=VERSION or daily.COMMENT_RECOVERY_VERSION!=VERSION:raise ValueError('评论补发配套程序版本不一致')
    rows=[]
    with locked():
        claims_path=upload.ROOT/'logs/automatic_comment_retry_claims.json'
        claims=upload.read_json(claims_path,dict(schema=SCHEMA,jobs={}))
        if not isinstance(claims,dict) or claims.get('schema')!=SCHEMA or not isinstance(claims.get('jobs'),dict):raise ValueError('补评账本异常，未重置重试机会')
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{});ledger=upload.read_json(upload.ROOT/'logs/video_comments.json',{})
        selected,decisions=candidates(value,state,ledger,claims)
        for job,key,mode in selected:
            claims['jobs'][key]=dict(account=job['account'],target=job['target'],video_job=job['key'],text_sha256=comments.text_hash(value['payload']['comment_text']),
                source_manifest=path.name,source_sha256=value['sha256'],mode=mode,reserved_at=datetime.now(timezone.utc).isoformat())
        # Consume the bounded attempt before opening a browser, even if interrupted.
        if selected:upload.save_json(claims_path,claims)
        audit=path.with_name(path.stem+'-comment-retry.json')
        upload.save_json(audit,dict(schema=SCHEMA,source_manifest=path.name,decisions=decisions,rows=[]))
        if not selected:
            print('自动补评队列为空；已成功及尚未核实的视频保留原状态。',flush=True)
            return rows
        print('评论补发阶段：未提交评论重新尝试，已提交待核实的只刷新检查；共',len(selected),'条。',flush=True)
        original=daily.find_published;daily.find_published=actual.make_finder(value['payload']['jobs'],True)
        try:
            daily.backfill(value,None,only_keys={job['key'] for job,_,_ in selected},rows=rows,already_locked=True,
                           future_only=True,reconcile_pending=True,reporter=reporter or (lambda *_:None))
        finally:
            daily.find_published=original
            upload.save_json(audit,dict(schema=SCHEMA,source_manifest=path.name,decisions=decisions,rows=rows))
    return rows
