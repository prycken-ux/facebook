"""Nov-2 authorization: only the eleven before-Post failures and two untouched Oct-31 jobs."""
import argparse,copy,json,os,shutil,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import safe_video_comments as comments
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

DATE='2026-11-02'
SOURCE='frozen-material-2026-10-31-154db1cebacb7ab5.json'
GRANT='retry-oct31-failed-thirteen-20261102'
SPEC={('fb02', 'page01'): {'key': '10200a5074aaa9b1290f8051184fcc2c28de5d0717d8562cdf9df1e44f5e0728',
                      'filename': '10.30打印2.0.mp4',
                      'original_status': 'not_started'},
 ('fb04', 'personal'): {'key': 'd7d3b9a4727948a261df9d70f92cabab6b44147184c7b1b19e2124dbe24404bc',
                        'filename': '1031权利1店打印1.0.mp4',
                        'original_status': 'not_started'},
 ('fb05', 'page01'): {'key': '61b316dd92b5fe1dba5c6eeeb7122fb397e7fa1cf24490f9b911529c942e86b6',
                      'filename': '1031权利打印1店2.0.mp4',
                      'original_status': 'failed_before_post'},
 ('fb06', 'page01'): {'key': 'b6f4cfa6f362e0289697a20a80e22b2d6c7416a961ae80d24c1de2a56e949a5b',
                      'filename': '1031权利打印1店3.0.mp4',
                      'original_status': 'failed_before_post'},
 ('fb08', 'personal'): {'key': 'e848b766e40b51eeb4e749c27ef5af786d6bae8470796d051904f9e8f4f06e2a',
                        'filename': '剧情1.mp4',
                        'original_status': 'failed_before_post'},
 ('fb09', 'personal'): {'key': '50ccbe4f03a6f94df8fea3b581d3804b2214c6402b0fefb020bfe40b2be4a477',
                        'filename': '口播1.mp4',
                        'original_status': 'failed_before_post'},
 ('fb10', 'personal'): {'key': '2b633c3e3d9bf61ad0491f0588bde7a4a7634be7db19ca23776ec78d82648e8e',
                        'filename': '1030-5.mp4',
                        'original_status': 'failed_before_post'},
 ('fb11', 'personal'): {'key': '745d861f8efd4a8e3d268d7e3437fccf62854668b513aeac2c00389bec94ecd6',
                        'filename': '剧情1.mp4',
                        'original_status': 'failed_before_post'},
 ('fb12', 'page01'): {'key': '9fd4b262a2bfa5cdf3b53f947e66127de49824b967cecd0a60280c587d82f996',
                      'filename': '剧情2.mp4',
                      'original_status': 'failed_before_post'},
 ('fb13', 'page01'): {'key': '1b89e21e9da4656b973168b65be0bb35b9319e33e8bb278ed2d85716b3b2f252',
                      'filename': '权剧情3.mp4',
                      'original_status': 'failed_before_post'},
 ('fb17', 'personal'): {'key': '8aacc4dd28a14c33db78ad597e8748131162eeba02bf09ea36d72613b40dae65',
                        'filename': '1.mp4',
                        'original_status': 'failed_before_post'},
 ('fb19', 'personal'): {'key': '3b8ab6e3b9758a8e0412c4fc2c06e73cf236edf1d71c545627623c59271f6d5c',
                        'filename': '2.mp4',
                        'original_status': 'failed_before_post'},
 ('fb20', 'personal'): {'key': 'a55dfcefcedc1a39e59d7e529d0eb7155e934fa9724a7323a81c325fab464045',
                        'filename': '3.mp4',
                        'original_status': 'failed_before_post'}}



def source_jobs():
    value=upload.read_json(upload.ROOT/'logs'/SOURCE,{})
    payload=value.get('payload',{});checksum=batch.digest(payload)
    if (payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-10-31' or payload.get('ai_label') is not False
            or payload.get('include_fb10_pages') is not True or set(payload.get('excluded_accounts',[]))!={'fb16','fb18','fb21'}
            or payload.get('comment_text')!=daily.COMMENT or value.get('sha256')!=checksum
            or not Path(SOURCE).stem.endswith(checksum[:16]) or len(payload.get('jobs',[]))!=30):
        raise ValueError('10月31日原清单缺失或校验不一致，未改选今天的新素材')
    jobs=[]
    for pair,spec in SPEC.items():
        matches=[j for j in payload['jobs'] if (j.get('account'),j.get('target'))==pair and j.get('key')==spec['key'] and j.get('filename')==spec['filename']]
        if len(matches)!=1:raise ValueError('没有唯一的指定原视频：'+'/'.join(pair))
        jobs.append(copy.deepcopy(matches[0]))
    return jobs


def validate_retry(job,state):
    pair=job['account'],job['target'];spec=SPEC.get(pair)
    if not spec or job['key']!=spec['key'] or job['filename']!=spec['filename']:raise ValueError('任务不在本次指定13条之中')
    entry=daily.configured(job);old=state.get(job['key'])
    if old is not None:
        if ((old.get('account'),old.get('target'))!=pair or upload.target_key(old.get('url',''))!=upload.target_key(job['url'])
                or str(old.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):raise ValueError('当前记录与原视频不一致')
        if old.get('status')=='published':return entry,old,'already_published'
        if old.get('status')!='failed_before_post':raise ValueError('当前任务已提交、待核实或仍在处理，不自动重置')
        if old.get('ai_label_requested') is not False or any(old.get(k) for k in ('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at')):
            raise ValueError('存在提交/成功线索或原 AI 设置不一致，不重复发布')
    elif spec['original_status']!='not_started':raise ValueError('失败原任务记录缺失，未把旧素材当成全新视频')
    selected=upload.named_job(entry,{k:v for k,v in state.items() if k!=job['key']},job['filename'])
    if not selected or selected[0]!=job['key'] or selected[3]!=job['caption_text'] or batch.file_hash(selected[2])!=job['caption_sha256']:
        raise ValueError('原视频或文案已变化/缺失，未改选其他文件')
    return entry,old,'ready'


def abandoned_preparations(account,selected_key,state):
    """Only known journal versions prove an exclusive-lock preparation predates Post."""
    result=[]
    for key,row in state.items():
        if key==selected_key or row.get('account')!=account or row.get('status') not in {'preparing','posting'}:continue
        if (row.get('status')!='preparing' or row.get('uploader_version') not in {'2.41','2.42','2.43','2.44','2.45','2.46'}
                or any(row.get(k) for k in ('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at'))):
            raise ValueError('该账号另有未核实的提交/旧任务，保留其浏览器与记录，先跳过')
        result.append(key)
    return result


def reserve(job,state,state_path):
    entry,old,action=validate_retry(job,state)
    if action=='already_published':return entry,False
    claims_path=upload.ROOT/'logs'/(GRANT+'-claims.json');claims=upload.read_json(claims_path,{})
    if job['key'] in claims:raise ValueError('此原视频本次补发机会已使用，未循环重复提交')
    stale=abandoned_preparations(entry['account'],job['key'],state)
    close_selected_window(entry['account'])  # Normal close only; fails safely if the profile stays busy.
    if upload.read_json(state_path,{})!=state:raise ValueError('关闭窗口期间任务记录变化，未重置任务')
    backup=upload.ROOT/'backups'/(GRANT+'-'+job['key'][:12]+'-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True);upload.save_json(backup/'publish_state.json',state)
    claim=dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],grant=GRANT,
        assertion='user_authorized_reported_failure_before_post_or_not_started',reserved_at=datetime.now(timezone.utc).isoformat(),
        original_record=copy.deepcopy(old),abandoned_preparation_keys=stale)
    upload.save_json(backup/'authorization.json',claim)
    claims[job['key']]=claim;upload.save_json(claims_path,claims)
    for key in stale:
        prior=copy.deepcopy(state[key]);state[key].update(status='failed_before_post',abandoned_preparation_prior_record=prior,
            error='原上传进程已退出，独占锁下核验无 Post 意图；仅结束旧准备状态，不发布该旧素材')
    if old is not None:
        state[job['key']]=dict(account=old['account'],target=old['target'],url=old['url'],video=old['video'],caption=old['caption'],
            created=old['created'],status='failed_before_post',ai_label_requested=False,retry_authorization=GRANT,authorized_prior_attempt=copy.deepcopy(old))
    upload.save_json(state_path,state)
    return entry,True


def write_report(jobs,attempts,output_dir,final=False):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{});rows=[]
    for job in jobs:
        record=state.get(job['key'],{});attempt=attempts.get(job['key'],{})
        rows.append(dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],
            video_status=record.get('status','not_started'),comment_status=record.get('comment_status','not_started'),
            action=attempt.get('action','not_started'),error='' if record.get('status')=='published' else attempt.get('error') or record.get('error',''),
            comment_error=record.get('comment_error','')))
    labels={'published':'发布成功','failed_before_post':'发布前失败','needs_review':'待核实','posting':'已提交待核实','preparing':'准备中待核实','not_started':'尚未开始'}
    lines=['10月31日原视频补发结果（本次授权：11月2日，共13条）','']
    for status in ['published','failed_before_post','needs_review','posting','preparing','not_started']:
        group=[r for r in rows if r['video_status']==status]
        if not group:continue
        lines.append(labels[status]+'：'+str(len(group))+'条')
        for r in group:
            message=r['account']+'/'+r['target']+' '+r['filename']
            if r['action']=='already_published':message+='（原记录已成功，本次未重发）'
            if r['error']:message+='；'+str(r['error']).split('\n',1)[0]
            lines.append(message)
        lines.append('')
    lines.append('评论结果：')
    for r in rows:
        if r['video_status']=='published':lines.append(r['account']+'/'+r['target']+' '+r['comment_status']+('；'+r['comment_error'] if r['comment_error'] else ''))
    stem='10月31日失败及未开始13条补发-20261102';report=upload.ROOT/'logs'/(stem+'.json');summary=upload.ROOT/'logs'/(stem+'.txt')
    upload.save_json(report,dict(grant=GRANT,source_manifest=SOURCE,rows=rows));summary.write_text('\n'.join(lines),encoding='utf-8-sig')
    out=Path(output_dir) if output_dir and Path(output_dir).is_dir() else upload.ROOT/'logs'
    if out!=summary.parent:shutil.copy2(summary,out/summary.name)
    with zipfile.ZipFile(out/(stem+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        z.write(report,'results.json');z.write(summary,'summary.txt')
        for row in rows:
            for prefix in ['review-','comment-']:
                if prefix=='review-' and row['video_status']=='published':continue
                if prefix=='comment-' and row['comment_status'] not in {'manual_required','needs_review'}:continue
                for suffix in ['.png','.aria.txt','-error.txt']:
                    file=upload.ROOT/'logs'/(prefix+row['key'][:12]+suffix)
                    if file.is_file():z.write(file,file.name)
    if final:
        print('\n'.join(lines),flush=True);print('本次文本汇总：',out/summary.name,flush=True)
    return rows


def execute(output_dir=None):
    if upload.VERSION not in {'2.45','2.46'} or comments.COMMENT_WORKFLOW_VERSION!='1.3-facebook-attribution':raise ValueError('需先安装上传核心 2.45 或 2.46 及评论模块 1.3')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('此补发授权仅限北京时间2026年11月2日')
    state_path=upload.ROOT/'logs/publish_state.json';attempts={};success=[]
    with locked(),daily.keep_awake():
        jobs=source_jobs()
        for job in jobs:
            attempt=attempts[job['key']]={'action':'not_started'}
            try:
                state=upload.read_json(state_path,{})
                if state.get(job['key'],{}).get('status')=='published':attempt['action']='already_published';continue
                entry,ready=reserve(job,state,state_path)
                if not ready:attempt['action']='already_published';continue
                runtime=dict(entry,enabled=True,auto_switch_personal=True,_authorized_comment_text=daily.COMMENT)
                print('补发指定原视频：',entry['account'],entry['target'],job['filename'],flush=True)
                attempt['action']='attempted'
                upload.run_entry(runtime,state,state_path,True,filename=job['filename'],ai_label_override=False,
                    expected_job_key=job['key'],preserve_old_review_for_exact_job=True,defer_comments=True,retry_before_post=state.get(job['key']) is not None)
            except KeyboardInterrupt:raise
            except Exception as error:
                attempt.update(action='skipped_or_failed',error=(str(error) or type(error).__name__)[:2000]);print('此项记录后继续下一个：',attempt['error'].split('\n',1)[0],flush=True)
            finally:
                current=upload.read_json(state_path,{}).get(job['key'],{})
                if current.get('status')=='published' and attempt['action']=='attempted':success.append(job)
                write_report(jobs,attempts,output_dir)
        if success:
            payload=dict(date=DATE,jobs=success);manifest=dict(payload=payload,sha256=batch.digest(payload))
            daily.backfill(manifest,output_dir,future_only=True,already_locked=True,reporter=lambda *_:write_report(jobs,attempts,output_dir))
        rows=write_report(jobs,attempts,output_dir,final=True)
    return 0 if all(r['video_status']=='published' for r in rows) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser(description='仅重发10月31日报告的11条发布前失败及2条未开始；成功及待核实任务不重发')
    parser.add_argument('--output-dir',type=Path);args=parser.parse_args()
    try:raise SystemExit(execute(args.output_dir))
    except KeyboardInterrupt:print('已停止，保留状态，请勿循环重复发布。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
