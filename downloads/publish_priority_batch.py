"""One new batch: all uploads, one safe retry, then verified comments."""
import argparse,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import automatic_batch_retry as retry
import actual_reels_comment_lookup as actual
import safe_video_comments as comments
from add_fb_accounts import locked

PRIORITY_WORKFLOW_VERSION='1.0-publish-retry-comments'
TIMING='after-video-pass-and-retry-v1'


def validate(path,value,date):
    payload=value.get('payload',{});checksum=batch.digest(payload);jobs=payload.get('jobs',[])
    if (value.get('sha256')!=checksum or payload.get('schema')!=batch.SCHEMA or payload.get('date')!=date
            or not re.fullmatch('frozen-material-'+re.escape(date)+'-'+checksum[:16]+r'\.json',path.name)
            or value.get('workflow')!='future-video-comments-v1' or value.get('auto_retry_policy')!=retry.POLICY
            or value.get('comment_timing')!=TIMING or value.get('priority_workflow')!=PRIORITY_WORKFLOW_VERSION
            or value.get('report_format')!='text' or payload.get('ai_label') is not False
            or payload.get('include_fb10_pages') is not True or payload.get('comment_text')!=daily.COMMENT
            or set(payload.get('excluded_accounts',[]))!=batch.excluded_accounts(date)
            or not jobs or len({j.get('key') for j in jobs})!=len(jobs)
            or any(not batch.eligible(j,True,date=date) or not re.fullmatch(r'[a-f0-9]{64}',str(j.get('key',''))) for j in jobs)):
        raise ValueError('今天优先发布批次的清单、范围或策略校验失败')
    policy=batch.preferences.load(date)
    if policy and (payload.get('publication_preferences_sha256')!=policy['sha256'] or any(j.get('caption_text')!=policy['payload']['caption'] for j in jobs)):
        raise ValueError('本批统一正文或后续发布规则已变化，未使用旧文案')


def prepare(date):
    now=datetime.now(timezone.utc);pointer=upload.ROOT/'logs'/('priority-batch-'+date+'.json')
    with locked():
        saved=upload.read_json(pointer,None)
        if saved is not None:
            if not isinstance(saved,dict) or saved.get('date')!=date or not re.fullmatch('frozen-material-'+re.escape(date)+r'-[a-f0-9]{16}\.json',str(saved.get('manifest',''))):
                raise ValueError('今天续跑指针异常，未另建批次')
            path=upload.ROOT/'logs'/saved['manifest'];value=upload.read_json(path,{})
            if saved.get('sha256')!=value.get('sha256'):raise ValueError('今天续跑清单指纹不一致')
            validate(path,value,date)
            print('续跑今天原批次，已尝试的视频不进入首轮重发。',flush=True)
            return path,value
        path,value=batch.freeze(date,now.astimezone(batch.BJ).strftime('%H:%M'),True,daily.COMMENT,now,
                                report_format='text',exclude_previous_plans=True)
        value.update(workflow='future-video-comments-v1',auto_retry_policy=retry.POLICY,
                     comment_timing=TIMING,priority_workflow=PRIORITY_WORKFLOW_VERSION,report_format='text')
        validate(path,value,date);upload.save_json(path,value)
        upload.save_json(pointer,dict(date=date,manifest=path.name,sha256=value['sha256']))
        return path,value


def comment_report(path,value,rows):
    state_path=upload.ROOT/'logs/publish_state.json';state=upload.read_json(state_path,{});changed=False
    ledger=upload.read_json(upload.ROOT/'logs/video_comments.json',{})
    for result in rows:
        row=state.get(result['key'],{});key=comments.hashlib.sha256((result['key']+'\0'+comments.text_hash(daily.COMMENT)).encode()).hexdigest()
        if (result.get('status')=='manual_required' and result.get('error','').startswith('自动定位暂未完成：') and row.get('status')=='published'
                and ledger.get(key,{}).get('status') not in {'sent','already_present','sending','verifying','needs_review'}):
            result['status']='lookup_pending';row['comment_status']='lookup_pending';changed=True
    if changed:upload.save_json(state_path,state)
    prior=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if prior.get('manifest')!=path.name or not isinstance(prior.get('attempts'),list):raise ValueError('原发布结果变化，未覆盖')
    batch.results(path,value,prior['attempts'],None,final=False)


def execute(date,real_footage):
    if not real_footage:raise ValueError('需要本批全部实拍确认')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=date:raise ValueError('只运行明确授权的北京时间当天新批次')
    if (upload.VERSION!='2.47' or getattr(upload,'IMMEDIATE_COMMENT_VERSION','')!='1.0-receipt-first-reload'
            or getattr(batch,'RESUME_WORKFLOW_VERSION','')!='1.0-preserve-attempted-jobs'
            or getattr(retry,'SAFE_BEFORE_POST_RETRY_VERSION','')!='1.2-network-and-prepost-timeouts'
            or retry.AUTO_RETRY_VERSION!='1.1-immediate-aware'):
        raise ValueError('优先发布、补发和评论的配套程序校验失败')
    path,value=prepare(date)
    print('今天新视频：',len(value['payload']['jobs']),'条；全部实拍，AI标签关闭；跳过：',','.join(value['payload']['excluded_accounts']),flush=True)
    print('先发布全部视频，再对可恢复的发布前失败补发一次，最后评论。',
          '正文统一使用已保存的授权原文。' if batch.preferences.load(date) else '已有同名TXT优先，缺少文案使用已保存文案。',flush=True)
    print('原清单开始时间：',value['payload']['start'],'；请保持此窗口打开。',flush=True)
    with daily.keep_awake():
        while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
        print('阶段1：发布今天原批次，保存成功视频直链，暂不发送评论。',flush=True)
        batch.run(path,defer_comments=True,resume=True)
        print('阶段2：只自动补发一次可恢复的发布前失败；已提交或结果不明的保留待核实。',flush=True)
        retry.run(path)
        print('阶段3：仅给今天原批次的成功视频评论，优先使用发布时保存的确切直链。',flush=True)
        original=daily.find_published;daily.find_published=actual.make_finder(value['payload']['jobs'],True)
        rows=[]
        try:
            daily.backfill(value,None,only_keys={j['key'] for j in value['payload']['jobs']},rows=rows,
                           future_only=True,reporter=lambda *_:comment_report(path,value,rows))
        finally:
            daily.find_published=original
            prior=upload.read_json(path.with_name(path.stem+'-results.json'),{})
            batch.results(path,value,prior.get('attempts',[]),None,final=True)
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    successes=sum(state.get(j['key'],{}).get('status')=='published' for j in value['payload']['jobs'])
    print('视频发布成功：',successes,'/',len(value['payload']['jobs']),'；评论失败不改变视频成功状态。',flush=True)
    return 0 if all(state.get(j['key'],{}).get('status')=='published' and state[j['key']].get('comment_status') in {'sent','already_present'} for j in value['payload']['jobs']) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='今天新批次：先上传全部，再安全补发一次，最后评论')
    parser.add_argument('--date',required=True);parser.add_argument('--real-footage',action='store_true')
    args=parser.parse_args()
    try:raise SystemExit(execute(args.date,args.real_footage))
    except KeyboardInterrupt:print('已停止；发布、补发和评论记录保留，重跑会继续原批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
