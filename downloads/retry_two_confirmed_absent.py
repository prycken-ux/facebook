"""One new user authorization for two exact Oct-30 media; fb14/fb17 cancelled."""
import argparse,copy,json,shutil,sys,traceback,zipfile
from datetime import datetime,timezone
from pathlib import Path
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import safe_video_comments as comments
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

DATE='2026-10-31'
SOURCE='frozen-material-2026-10-30-95909206c11ab92a.json'
GRANT='two-confirmed-absent-20261031-after-eight-retry'
SPEC={
 ('fb10','page09'):dict(key='a4e63c6c43ab3606fbcf9f98dbb3450b7662a3f1633a3e4e68d26907893666af',filename='9.mp4',name='Hacrasnite Hacaldcirtsle',url='https://www.facebook.com/profile.php?id=61594856113274',reason='原生选文件事件后编辑器仍为空，Describe your reel 描述框不存在',prevention='确认编辑器已接收原文件；仅在明确为空时重选同一视频一次；不猜文案框'),
 ('fb09','personal'):dict(key='6a30dc8af05f7c8125073ce59929bf7a3475770dd2ceacde664d7432b8d69cbb',filename='剧情2.mp4',name='Jesse Arreola',url='https://www.facebook.com/profile.php?id=100094216112371',reason='上次提交后三分钟仍显示 Uploading 53%，未取得成功回执',prevention='界面仍显示上传未完成时暂不提交；提交后最多三分钟，未知结果不循环重发')
}


def source_jobs():
    value=upload.read_json(upload.ROOT/'logs'/SOURCE,{})
    payload=value.get('payload',{});checksum=batch.digest(payload)
    if (payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-10-30' or payload.get('ai_label') is not False
            or value.get('sha256')!=checksum or not Path(SOURCE).stem.endswith(checksum[:16])):
        raise ValueError('10月30日原素材清单缺失或校验不一致，未换用新视频')
    jobs=[]
    for pair,spec in SPEC.items():
        matches=[j for j in payload.get('jobs',[]) if (j.get('account'),j.get('target'))==pair and j.get('key')==spec['key'] and j.get('filename')==spec['filename']]
        if len(matches)!=1 or upload.target_key(matches[0]['url'])!=upload.target_key(spec['url']):raise ValueError('原清单没有唯一指定素材：'+'/'.join(pair))
        jobs.append(copy.deepcopy(matches[0]))
    return jobs


def validate_retry(job,state):
    pair=job['account'],job['target'];spec=SPEC.get(pair)
    if not spec or job['key']!=spec['key'] or job['filename']!=spec['filename']:raise ValueError('任务超出此次两个目标的原视频范围')
    old=state.get(job['key']);entry=daily.configured(job)
    if entry['name']!=spec['name'] or upload.target_key(entry['url'])!=upload.target_key(spec['url']):raise ValueError('账号身份与本次指定主页不一致')
    if not isinstance(old,dict) or (old.get('account'),old.get('target'))!=pair or upload.target_key(old.get('url',''))!=upload.target_key(spec['url']):raise ValueError('原任务记录缺失或目标不一致')
    if old.get('status')=='published':return entry,None
    if old.get('status') not in {'failed_before_post','needs_review'}:raise ValueError('任务仍在准备/提交中或状态未知，未解除原限制')
    if any(old.get(k) for k in ('permalink','success_message','confirmation_method','confirmed_at','published_at')):raise ValueError('已有成功证据，未自动重新发布')
    if old.get('ai_label_requested') is not False:raise ValueError('原视频实拍/AI 设置缺少明确记录')
    if str(old.get('video','')).replace('\\','/').split('/')[-1]!=spec['filename']:raise ValueError('原任务文件名不一致')
    if any(k!=job['key'] and r.get('account')==pair[0] and r.get('status') in {'preparing','posting'} for k,r in state.items()):raise ValueError('此账号另有准备/提交中的任务，未关闭窗口或清理记录')
    selected=upload.named_job(entry,{k:v for k,v in state.items() if k!=job['key']},job['filename'])
    if not selected or selected[0]!=job['key'] or selected[3]!=job['caption_text'] or batch.file_hash(selected[2])!=job['caption_sha256']:raise ValueError('原文件或同名文案与原批次不一致，未使用其他素材')
    return entry,old


def reserve(job,state,state_path):
    claims_path=upload.ROOT/'logs'/(GRANT+'-claims.json');claims=upload.read_json(claims_path,{})
    if job['key'] in claims:raise ValueError('此次单次补发许可已使用，不循环提交；需先核实新结果')
    entry,old=validate_retry(job,state)
    if old is None:return entry,False
    close_selected_window(entry['account'])
    if upload.read_json(state_path,{})!=state:raise ValueError('关闭窗口期间发布记录变化，未重置原任务')
    backup=upload.ROOT/'backups'/(GRANT+'-'+job['key'][:12]+'-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True);shutil.copy2(state_path,backup/'publish_state.json')
    assertion=dict(account=job['account'],target=job['target'],key=job['key'],filename=job['filename'],grant=GRANT,
        asserted_at=datetime.now(timezone.utc).isoformat(),assertion='user_currently_verified_exact_video_absent',original_record=copy.deepcopy(old))
    upload.save_json(backup/'authorization.json',assertion)
    # Consume first, then replace only this guard. A crash cannot reuse the grant.
    claims[job['key']]=assertion;upload.save_json(claims_path,claims)
    state[job['key']]=dict(account=old['account'],target=old['target'],url=old['url'],video=old['video'],caption=old['caption'],created=old['created'],
        status='failed_before_post',ai_label_requested=False,retry_authorization=GRANT,verified_absent_prior_attempt=copy.deepcopy(old))
    upload.save_json(state_path,state)
    return entry,True


def write_report(jobs,attempts,output_dir):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{});rows=[]
    for job in jobs:
        pair=job['account'],job['target'];spec=SPEC[pair];record=state.get(job['key'],{});attempt=attempts.get(job['key'],{})
        rows.append(dict(account=pair[0],target=pair[1],name=spec['name'],filename=job['filename'],key=job['key'],
            video_status=record.get('status','missing'),comment_status=record.get('comment_status','not_started'),
            previous_reason=spec['reason'],prevention=spec['prevention'],attempt=attempt.get('action','not_started'),
            error='' if record.get('status')=='published' else attempt.get('error',record.get('error','')),comment_error=record.get('comment_error','')))
    stem='两个指定目标补发-20261031';report=upload.ROOT/'logs'/(stem+'.json');upload.save_json(report,dict(grant=GRANT,skipped_accounts=['fb14','fb17','fb16','fb18','fb21'],rows=rows))
    out=Path(output_dir) if output_dir and Path(output_dir).is_dir() else upload.ROOT/'logs'
    with zipfile.ZipFile(out/(stem+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        z.write(report,'results.json')
        for job in jobs:
            for prefix in ['review-','comment-']:
                row=state.get(job['key'],{})
                if prefix=='review-' and row.get('status')=='published':continue
                if prefix=='comment-' and row.get('comment_status') not in {'manual_required','needs_review'}:continue
                for suffix in ['.png','.aria.txt','-error.txt']:
                    file=upload.ROOT/'logs'/(prefix+job['key'][:12]+suffix)
                    if file.is_file():z.write(file,file.name)
    for row in rows:print(row['account']+'/'+row['target'],row['filename'],row['video_status'],row['comment_status'],str(row['error']).split('\n')[0],flush=True)
    print('本次结果包：',out/(stem+'.zip'),flush=True)
    return rows


def execute(output_dir=None):
    if upload.VERSION!='2.44' or comments.COMMENT_WORKFLOW_VERSION!='1.3-facebook-attribution':raise ValueError('需安装配套上传核心 2.44 及评论模块 1.3')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('此补发授权仅用于北京时间10月31日，不自动改日重发')
    state_path=upload.ROOT/'logs/publish_state.json';attempts={};success=[]
    with locked(),daily.keep_awake():
        jobs=source_jobs()
        for job in jobs:
            attempt=attempts[job['key']]={'action':'skipped'}
            try:
                state=upload.read_json(state_path,{})
                if state.get(job['key'],{}).get('status')=='published':
                    attempt['action']='already_published';continue
                entry,ready=reserve(job,state,state_path)
                if not ready:continue
                runtime=dict(entry,enabled=True,auto_switch_personal=True,_authorized_comment_text=daily.COMMENT)
                print('仅补发指定原视频：',entry['account'],entry['target'],job['filename'],flush=True)
                attempt['action']='attempted'
                upload.run_entry(runtime,state,state_path,True,filename=job['filename'],ai_label_override=False,
                    expected_job_key=job['key'],preserve_old_review_for_exact_job=True,defer_comments=True,retry_before_post=True)
            except KeyboardInterrupt:raise
            except Exception as error:
                attempt.update(action='needs_review_or_skipped',error=(str(error) or type(error).__name__)[:2000]);print('此目标保留记录，继续下一个：',attempt['error'].split('\n')[0],flush=True)
            finally:
                current=upload.read_json(state_path,{}).get(job['key'],{})
                previous=current.get('previous_before_post_attempt',{})
                if current.get('status')=='published' and previous.get('retry_authorization')==GRANT and attempt['action']=='attempted':success.append(job)
                write_report(jobs,attempts,output_dir)
        if success:
            # Comments only for successful new submissions in this exact authorization.
            payload=dict(date=DATE,jobs=success);manifest=dict(payload=payload,sha256=batch.digest(payload))
            daily.backfill(manifest,output_dir,future_only=True,already_locked=True)
        rows=write_report(jobs,attempts,output_dir)
    return 0 if all(r['video_status']=='published' for r in rows) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser(description='仅补发用户本次确认未发布的 fb10/page09 9.mp4 与 fb09 剧情2.mp4；跳过 fb14/fb17')
    parser.add_argument('--output-dir',type=Path);args=parser.parse_args()
    try:raise SystemExit(execute(args.output_dir))
    except KeyboardInterrupt:print('已停止，保留记录，勿直接重复发布。');raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__);raise SystemExit(1)
