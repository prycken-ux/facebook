"""Nov-3 authorization: comments only on the 26 confirmed Nov-2 published jobs."""
import copy,hashlib,re,shutil,sys,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import safe_video_comments as comments
from add_fb_accounts import locked

DATE='2026-11-03'
PREFIX='f6cc163c'
EXCLUDED={('fb02','page01'),('fb04','personal'),('fb10','page07'),('fb10','page08')}
USER_CONFIRMED={
 ('fb07','personal'):'97f5f98b98e8',
 ('fb03','personal'):'aec6e81aeb5e',('fb05','page01'):'27a09f06a816',('fb10','page01'):'66d690b685fd',
 ('fb08','personal'):'a4b07c959620',('fb10','personal'):'039dcaacb422',('fb11','personal'):'03b90f9f7c29',
 ('fb14','personal'):'f35b8f43507b',('fb15','personal'):'61bad5a4816b',('fb17','personal'):'def02221852e',
 ('fb19','personal'):'8538aaccdead',('fb20','personal'):'dae0a9829354',('fb22','personal'):'219df014e5a9',
}
PROTECTED={'sent','already_present','sending','verifying','needs_review'}
STEM='11月2日成功视频补评论-20261103'


def load_source():
    paths=[p for p in (upload.ROOT/'logs').glob('frozen-material-2026-11-02-'+PREFIX+'*.json')
           if re.fullmatch(r'frozen-material-2026-11-02-[a-f0-9]{16}\.json',p.name)]
    if len(paths)!=1:raise ValueError('没有唯一的11月2日f6cc163c原清单，未选择31号或今天新视频')
    source=paths[0];value=upload.read_json(source,{});payload=value.get('payload',{});checksum=batch.digest(payload)
    pairs={(j.get('account'),j.get('target')) for j in payload.get('jobs',[])}
    if (value.get('sha256')!=checksum or not checksum.startswith(PREFIX) or not source.stem.endswith(checksum[:16])
            or payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-11-02'
            or payload.get('comment_text')!=daily.COMMENT or value.get('report_format')!='text'
            or set(payload.get('excluded_accounts',[]))!={'fb16','fb18','fb21'}
            or len(payload.get('jobs',[]))!=30 or pairs!=daily.EXPECTED_PAIRS
            or len({j.get('key') for j in payload['jobs']})!=30
            or any(not re.fullmatch(r'[a-f0-9]{64}',str(j.get('key',''))) for j in payload['jobs'])):
        raise ValueError('11月2日原30条清单或授权评论内容不一致')
    report=upload.read_json(source.with_name(source.stem+'-results.json'),{})
    if report.get('manifest')!=source.name or not isinstance(report.get('attempts'),list):
        raise ValueError('原批次结果或历史尝试记录不匹配，未覆盖其他报告')
    jobs=[copy.deepcopy(j) for j in payload['jobs'] if (j['account'],j['target']) not in EXCLUDED]
    if len(jobs)!=26 or len({j['key'] for j in jobs})!=26:raise ValueError('指定26条原视频不唯一')
    for pair,prefix in USER_CONFIRMED.items():
        found=[j for j in jobs if (j['account'],j['target'])==pair and j['key'].startswith(prefix)]
        if len(found)!=1:raise ValueError('用户确认的原视频匹配不唯一：'+'/'.join(pair))
    return source,value,jobs


def bound_record(job,state):
    row=state.get(job['key'])
    if (not isinstance(row,dict) or (row.get('account'),row.get('target'))!=(job['account'],job['target'])
            or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
            or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):
        raise ValueError('当前任务与原视频不一致，未改选其他视频')
    return row


def comment_key(job):return hashlib.sha256((job['key']+'\0'+comments.text_hash(daily.COMMENT)).encode()).hexdigest()


def restore_verified_link(job,row,item):
    """Reuse a prior exact-job proof, never an unbound or unknown-send ledger row."""
    if row.get('comment_status') in PROTECTED or item.get('status') in PROTECTED:return False
    if row.get('comment_link_job_key')==job['key'] and comments.direct_link(row.get('permalink','')):return False
    if row.get('comment_link_job_key') not in {None,'',job['key']}:return False
    method=item.get('link_method','')
    known=method in {'verified_owner_caption_time','verified_owner_caption_time_reels_tabs','previously_verified_exact_job_link','user_supplied_exact_job_link','published_video_owner_caption_creation_match'}
    known|=isinstance(method,str) and method.startswith('fresh_')
    link=comments.direct_link(item.get('permalink',''))
    if (not link or not known or item.get('status')!='manual_required' or item.get('video_job')!=job['key']
            or (item.get('account'),item.get('target'))!=(job['account'],job['target'])
            or item.get('text_sha256')!=comments.text_hash(daily.COMMENT)):return False
    row.update(permalink=link,comment_link_job_key=job['key'],comment_link_method='restored_exact_job_comment_ledger')
    return True


def prepare(jobs,source,state,ledger,audit):
    ordered=[];skipped=[]
    for job in jobs:
        try:
            row=bound_record(job,state);pair=job['account'],job['target'];daily.configured(job)
            if row.get('status')=='needs_review' and pair in USER_CONFIRMED:
                posted=datetime.fromisoformat(row['post_intent_at']);created=datetime.fromisoformat(row['created'])
                if posted.tzinfo is None or created.tzinfo is None or created>posted:raise ValueError('原创建/提交时间不可信')
                before=copy.deepcopy(row)
                row.update(status='published',confirmation_method='user_confirmed_nov02_published_20261103',confirmed_at=datetime.now(timezone.utc).isoformat(),
                    confirmed_source_manifest=source.name,confirmed_batch_lookup_cutoff=(posted+timedelta(minutes=30)).isoformat(),error='')
                row.pop('review_reason',None);audit.append(dict(key=job['key'],action='user_confirmed_publication',prior_record=before))
            if row.get('status')!='published':raise ValueError('视频当前未确认成功，未发送评论')
            before=copy.deepcopy(row)
            if restore_verified_link(job,row,ledger.get(comment_key(job),{})):
                audit.append(dict(key=job['key'],action='restore_verified_comment_link',prior_record=before))
            ordered.append(job)
        except Exception as error:
            skipped.append(dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],status='video_not_confirmed',error=str(error)))
    ordered.sort(key=lambda j:(not bool(state[j['key']].get('comment_link_job_key')==j['key'] and comments.direct_link(state[j['key']].get('permalink',''))),j['account'],j['target']))
    return ordered,skipped


def write_results(source,value,jobs,rows,final=False):
    by_key={r['key']:r for r in rows};state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    ledger=upload.read_json(upload.ROOT/'logs/video_comments.json',{})
    labels={'sent':'评论已刷新确认成功','already_present':'已有规定评论，保留','manual_required':'未发送或未完成','needs_review':'发送结果待核实，不重复发','sending':'已有发送意图，跳过','verifying':'已有发送意图，跳过','video_not_confirmed':'未处理：原视频状态需核对','not_started':'本次尚未处理'}
    lines=['11月2日已确认成功视频补评论（26条，11月3日授权）','本次没有上传或补发视频。',''];output=[]
    for job in jobs:
        row=dict(by_key.get(job['key'],dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],status='not_started',error='')))
        receipt=ledger.get(comment_key(job),{})
        if receipt.get('status') in {'sending','verifying','needs_review'}:
            row.update(status=receipt['status'],error=receipt.get('error',''))
        output.append(row)
        text=job['account']+'/'+job['target']+' '+job['filename']+'：'+labels.get(row['status'],row['status'])
        if row.get('error'):text+='；'+str(row['error']).split('\n',1)[0]
        lines.append(text)
    sent=sum(r['status'] in {'sent','already_present'} for r in output)
    lines+=['','本次评论确认成功或已存在：'+str(sent)+'条；其余未完成、待核实或尚未处理：'+str(len(jobs)-sent)+'条。',
            'fb02、fb04、fb10/page07、page08及31号旧视频均未补评。']
    folder=upload.ROOT/'logs';upload.save_json(folder/(STEM+'.json'),dict(source_manifest=source.name,video_upload_started=False,rows=output))
    (folder/(STEM+'.txt')).write_text('\n'.join(lines),encoding='utf-8-sig')
    if final:
        prior=upload.read_json(source.with_name(source.stem+'-results.json'),{})
        if prior.get('manifest')!=source.name:raise ValueError('原结果报告变化，未覆盖')
        batch.results(source,value,prior['attempts'],None,final=False)
        print('\n'.join(lines),flush=True)
    return output


def execute():
    if (upload.VERSION!='2.47' or getattr(upload,'IMMEDIATE_COMMENT_VERSION','')!='1.0-receipt-first-reload'
            or not callable(getattr(comments,'immediate_verified_comment',None))):raise ValueError('需先完成配套评论模块校验')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('此补评仅限北京时间11月3日，未启动其他日期任务')
    rows=[];audit=[];state_path=upload.ROOT/'logs/publish_state.json'
    with locked(),daily.keep_awake():
        source,value,jobs=load_source();state=upload.read_json(state_path,{});ledger=upload.read_json(upload.ROOT/'logs/video_comments.json',{})
        backup=upload.ROOT/'backups'/('nov02-comment-backfill-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8]);backup.mkdir(parents=True)
        for prior in (state_path,upload.ROOT/'logs/video_comments.json',source,source.with_name(source.stem+'-results.json'),source.with_name(source.stem+'-results.txt')):
            if prior.is_file():shutil.copy2(prior,backup/prior.name)
        ordered,skipped=prepare(jobs,source,state,ledger,audit);rows.extend(skipped)
        if audit:
            upload.save_json(backup/'preparation-audit.json',dict(source_manifest=source.name,changes=audit))
            upload.save_json(state_path,state)
        print('只给11月2日已确认成功的视频补评论：',len(ordered),'条。已有或待核实的发送记录保留，不重复发。',flush=True)
        work_payload=dict(date='2026-11-02',jobs=ordered)
        work=dict(payload=work_payload,sha256=batch.digest(work_payload))
        reporter=lambda *_:write_results(source,value,jobs,rows)
        if ordered:
            daily.backfill(work,None,only_keys={j['key'] for j in ordered},rows=rows,already_locked=True,future_only=True,reporter=reporter)
        result=write_results(source,value,jobs,rows,final=True)
    return 0 if all(r['status'] in {'sent','already_present'} for r in result) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if sys.platform!='win32' or upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原Windows上传电脑运行')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('补评已停止，保留已有发送意图，不要清空记录后重复发送。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
