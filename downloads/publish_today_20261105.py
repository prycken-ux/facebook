"""Nov-5 real footage: confirm the old two, publish new batch, retry once, comment."""
import argparse,copy,shutil,sys,uuid
from datetime import datetime,timezone
import fb_upload as upload
import scheduled_material_batch as batch
import publish_priority_batch as priority
import daily_publish_and_comments as daily
import actual_reels_comment_lookup as actual
import safe_video_comments as comments
import normal_chrome_batch as normal
import local_file_input as local
import retry_nov04_two_and_comment_20261105 as previous
from add_fb_accounts import locked

DATE='2026-11-05'
MODE=normal.NORMAL_CHROME_VERSION
WORKFLOW_VERSION='1.0-nov05-real-priority'
PROTECTED={'sent','already_present','sending','verifying','needs_review'}


def confirm_previous():
    """Only the two original Nov-4 keys; never submit or comment on old videos."""
    with locked():
        path,value,jobs=previous.base.source();state_path=upload.ROOT/'logs/publish_state.json';state=upload.read_json(state_path,{})
        selected=previous.select(jobs,state);plan=[]
        for job in selected:
            row=previous.bound(job,state)
            if row.get('status')=='published':continue
            if row.get('status')!='needs_review' or not row.get('post_intent_at'):raise ValueError('昨天两条补发的阶段出现变化，未猜记成功')
            plan.append(job)
        if not plan:
            print('昨天指定两条已有成功记录，保留；今天不重新上传或补评论。',flush=True);return
        backup=upload.ROOT/'backups'/('nov04-two-confirmed-before-nov05-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        for file in (state_path,path,path.with_name(path.stem+'-results.json')):
            if file.is_file():shutil.copy2(file,backup/file.name)
        now=datetime.now(timezone.utc).isoformat()
        audit=dict(source_manifest=path.name,method='user_confirmed_nov04_two_published_before_nov05',
                   rows=[dict(key=j['key'],previous_record=copy.deepcopy(state[j['key']])) for j in plan])
        upload.save_json(backup/'confirmation-audit.json',audit)
        for job in plan:
            row=state[job['key']]
            row.update(status='published',status_before_user_confirmation=row['status'],confirmation_method=audit['method'],
                       confirmed_at=now,confirmed_source_manifest=path.name,confirmed_batch_lookup_cutoff=now,error='')
            row.setdefault('published_caption_text',job['caption_text'])
        upload.save_json(state_path,state)
        for job,item in zip(plan,audit['rows']):
            video=upload.inbox_for(daily.configured(job))/job['filename'];caption=video.with_suffix('.txt')
            item['archive_result']='原文件不在inbox或内容/文案已变化，未移动其他文件'
            try:
                if video.is_file() and caption.is_file() and upload.job_key(daily.configured(job),video)==job['key'] and batch.file_hash(caption)==job['caption_sha256']:
                    folder=upload.archive(video,caption)
                    state[job['key']].update(archived_video=str(folder/video.name),archived_caption=str(folder/caption.name),archived_at=now)
                    upload.save_json(state_path,state);item['archive_result']='原视频已归档'
            except Exception as error:item['archive_result']='成功记录保留；归档需核实：'+str(error).split('\n',1)[0]
        upload.save_json(backup/'confirmation-audit.json',audit)
        previous.base.refresh(path,value,final=False)
        print('昨天指定两条已按你的确认保留/补记成功；今天只处理11月5日新视频。',flush=True)


def comment_report(path,value,rows):
    state_path=upload.ROOT/'logs/publish_state.json';state=upload.read_json(state_path,{});changed=False
    ledger=upload.read_json(upload.ROOT/'logs/video_comments.json',{})
    for result in rows:
        row=state.get(result['key'],{});key=comments.hashlib.sha256((result['key']+'\0'+comments.text_hash(daily.COMMENT)).encode()).hexdigest()
        if (result.get('status')=='manual_required' and result.get('error','').startswith('自动定位暂未完成：')
                and row.get('status')=='published' and ledger.get(key,{}).get('status') not in PROTECTED):
            result['status']='lookup_pending';row['comment_status']='lookup_pending';changed=True
    if changed:upload.save_json(state_path,state)
    prior=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if prior.get('manifest')!=path.name or not isinstance(prior.get('attempts'),list):raise ValueError('今天原发布结果变化，未覆盖')
    batch.results(path,value,prior['attempts'],None,final=False)


def execute(real_footage):
    if not real_footage:raise ValueError('今天全批需明确确认不含AI生成或显著修改画面')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('此指令只处理北京时间11月5日的新批次')
    if (upload.VERSION!='2.47' or normal.LOCAL_FILE_INPUT_COMPATIBILITY!=local.VERSION
            or actual.LOOKUP_VERSION!='1.1-fragments-jsonld-noninteractive'
            or getattr(priority.retry,'VISIBILITY_RETRY_VERSION','')!='1.0-stage-bound-visibility'
            or getattr(actual,'REELS_ENTRY_VERSION','')!='1.0-owner-route-fallback'):raise ValueError('本机上传修复或自动评论模块版本不匹配')
    confirm_previous()
    original_prepare=priority.prepare;original_launch=upload.launch_context;original_report=priority.comment_report
    def prepare(date):
        path,value=original_prepare(date)
        if any(j['account'] in {'fb24','fb25','fb26'} for j in value['payload']['jobs']):raise ValueError('已删除账号不进入今天批次')
        with locked():
            if upload.read_json(path,{})!=value:raise ValueError('今天清单在启动期间变化，未运行')
            if value.get('browser_launch_mode') not in {None,MODE} or value.get('local_file_input_mode') not in {None,local.VERSION}:raise ValueError('今天批次浏览器或本机选文件策略不一致')
            value.update(browser_launch_mode=MODE,local_file_input_mode=local.VERSION)
            upload.save_json(path,value)
        jobs=value['payload']['jobs'];upload.launch_context=normal.launcher_for_jobs(jobs)
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        fresh=[j for j in jobs if j['key'] not in state and not any(r.get('account')==j['account'] and r.get('status') in {'preparing','posting'} for r in state.values())]
        if fresh:
            print('先做今天原文件的本机选取自检；此步骤不会上传或发布。',flush=True)
            previous.base.self_check(next((j for j in fresh if j.get('video_size',0)>50*1024*1024),fresh[0]))
        return path,value
    priority.prepare=prepare;priority.comment_report=comment_report
    print('11月5日新视频：先发布全部，再安全补发一次，最后自动评论并刷新核验；AI标签关闭。',flush=True)
    try:return priority.execute(DATE,True)
    finally:priority.prepare=original_prepare;priority.comment_report=original_report;upload.launch_context=original_launch


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='11月5日：发布新视频、一次安全补发、成功视频自动评论')
    parser.add_argument('--real-footage',action='store_true');args=parser.parse_args()
    try:raise SystemExit(execute(args.real_footage))
    except KeyboardInterrupt:print('已停止；全部发布、补发和评论发送记录保留，重跑继续今天原批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
