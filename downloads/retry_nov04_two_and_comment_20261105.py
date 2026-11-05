"""User confirmed only Alice Luther/Prycken BK absent in the original Nov-4 batch."""
import contextlib,copy,shutil,sys,uuid
from datetime import datetime,timezone
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import safe_video_comments as comments
import actual_reels_comment_lookup as actual
import normal_chrome_batch as normal
import local_file_input as local
import retry_nov04_after_local_file_fix_20261105 as base
from add_fb_accounts import locked

GRANT='nov04-two-user-confirmed-absent-20261105'
SPEC={('fb11','personal'):('91185a39bc7c','1103权利1店1.0.mp4','Alice Luther'),
      ('fb13','page01'):('f49305f46d72','1103权利1店3.0.mp4','Prycken BK')}
PROTECTED={'sent','already_present','sending','verifying','needs_review'}


@contextlib.contextmanager
def grant_scope():
    previous=base.GRANT;base.GRANT=GRANT
    try:yield
    finally:base.GRANT=previous


def bound(job,state):
    row=state.get(job['key'])
    if (not isinstance(row,dict) or (row.get('account'),row.get('target'))!=(job['account'],job['target'])
            or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
            or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):raise ValueError('当前记录与11月4日原视频不一致')
    return row


def select(jobs,state):
    selected=[]
    for job in jobs:
        pair=job['account'],job['target'];row=bound(job,state)
        if pair in SPEC:
            prefix,filename,name=SPEC[pair]
            if not job['key'].startswith(prefix) or job['filename']!=filename:raise ValueError('原视频与指定两条失败记录不一致')
            entry=daily.configured(job)
            if comments.normalized(entry['name'])!=name:raise ValueError('账号名称与指定截图不一致，未猜选目标')
            selected.append(job)
        elif row.get('status') not in {'published','needs_review'}:raise ValueError('其余28条状态出现新的异常，未猜记成功')
    if len(selected)!=2 or {(j['account'],j['target']) for j in selected}!=set(SPEC):raise ValueError('未找到唯一的指定两个目标')
    return selected


def confirm_others(path,jobs,state,backup):
    now=datetime.now(timezone.utc).isoformat();audit=[];plan=[]
    for job in jobs:
        if (job['account'],job['target']) in SPEC:continue
        row=bound(job,state)
        if row['status']=='published':continue
        if row['status']!='needs_review':raise ValueError('用户确认条目的阶段变化，未覆盖')
        plan.append((job,daily.configured(job)))
        audit.append(dict(key=job['key'],account=job['account'],target=job['target'],previous_record=copy.deepcopy(row)))
    upload.save_json(backup/'user-confirmation-audit.json',dict(source_manifest=path.name,method='user_confirmed_nov04_all_except_two_20261105',changes=audit))
    for job,entry in plan:
        row=state[job['key']]
        row.update(status='published',status_before_user_confirmation=row['status'],confirmation_method='user_confirmed_nov04_all_except_two_20261105',
                   confirmed_at=now,confirmed_source_manifest=path.name,confirmed_batch_lookup_cutoff=now,error='')
        row.setdefault('published_caption_text',job['caption_text'])
    if plan:upload.save_json(upload.ROOT/'logs/publish_state.json',state)
    for (job,entry),item in zip(plan,audit):
        video=upload.inbox_for(entry)/job['filename'];caption=video.with_suffix('.txt')
        item['archive_result']='原文件不在inbox或内容/文案已变化；未移动其他文件'
        try:
            if video.is_file() and caption.is_file() and upload.job_key(entry,video)==job['key'] and batch.file_hash(caption)==job['caption_sha256']:
                folder=upload.archive(video,caption)
                state[job['key']].update(archived_video=str(folder/video.name),archived_caption=str(folder/caption.name),archived_at=now)
                upload.save_json(upload.ROOT/'logs/publish_state.json',state);item['archive_result']='原视频已归档'
        except Exception as error:item['archive_result']='成功记录已保存；归档需核实：'+str(error).split('\n',1)[0]
    upload.save_json(backup/'user-confirmation-audit.json',dict(source_manifest=path.name,method='user_confirmed_nov04_all_except_two_20261105',changes=audit))
    print('其余28条保留成功；本次按你的确认补记：',len(plan),'条。只会补发 fb11/personal 和 fb13/page01。',flush=True)


def refresh(path,value,selected,comment_rows,attempt=None,final=False):
    state_path=upload.ROOT/'logs/publish_state.json';state=upload.read_json(state_path,{});changed=False
    ledger=upload.read_json(upload.ROOT/'logs/video_comments.json',{})
    for result in comment_rows:
        row=state.get(result['key'],{});key=comments.hashlib.sha256((result['key']+'\0'+comments.text_hash(daily.COMMENT)).encode()).hexdigest()
        if (result.get('status')=='manual_required' and result.get('error','').startswith('自动定位暂未完成：')
                and row.get('status')=='published' and ledger.get(key,{}).get('status') not in PROTECTED):
            result['status']='lookup_pending';row['comment_status']='lookup_pending';changed=True
    if changed:upload.save_json(state_path,state)
    rows=base.refresh(path,value,attempt,final=final)
    if final:
        selected_keys={j['key'] for j in selected};own=[r for r in rows if r['key'] in selected_keys]
        names={'published':'发布成功','failed_before_post':'发布前失败','needs_review':'已提交待核实，不自动重发','posting':'已提交待核实','preparing':'准备中待核实'}
        comment_names={'sent':'评论已刷新确认成功','already_present':'已有规定评论','lookup_pending':'评论待定位，未发送','manual_required':'评论未完成','deferred':'等待评论','not_started':'评论未开始','needs_review':'评论发送结果待核实，不重复发'}
        lines=['11月4日指定两个账号补发及评论结果']
        for row in own:
            lines.append(row['account']+'/'+row['target']+' '+row['filename']+'：'+names.get(row['video_status'],row['video_status']))
            if row['video_status']=='published':lines.append('评论：'+comment_names.get(row['comment_status'],row['comment_status']))
            if row['reason']:lines.append('原因：'+row['reason'].split('\n',1)[0])
        print('\n'.join(lines),flush=True)
        folder=upload.ROOT/'logs';(folder/(GRANT+'-results.txt')).write_text('\n'.join(lines),encoding='utf-8-sig')
        upload.save_json(folder/(GRANT+'-results.json'),dict(grant=GRANT,source_manifest=path.name,rows=own,comment_results=comment_rows))
    return rows


def execute():
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!='2026-11-05':raise ValueError('此指令仅限11月5日处理11月4日原批次')
    if (upload.VERSION!='2.47' or normal.LOCAL_FILE_INPUT_COMPATIBILITY!=local.VERSION
            or actual.LOOKUP_VERSION!='1.1-fragments-jsonld-noninteractive'):raise ValueError('现有发布/本机选文件/自动评论版本不匹配')
    state_path=upload.ROOT/'logs/publish_state.json';comment_rows=[]
    with locked(),daily.keep_awake(),grant_scope():
        path,value,jobs=base.source();state=upload.read_json(state_path,{});selected=select(jobs,state)
        backup=upload.ROOT/'backups'/(GRANT+'-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        for file in (state_path,path,path.with_name(path.stem+'-results.json'),upload.ROOT/'logs/video_comments.json',
                     upload.ROOT/'logs/automatic_before_post_retry_claims.json',upload.ROOT/'logs'/(GRANT+'-claims.json')):
            if file.is_file():shutil.copy2(file,backup/file.name)
        confirm_others(path,jobs,state,backup)
        ledger_path,ledger=base.claims(value);eligible=[]
        for job in selected:
            try:
                if base.validate(job,state,ledger)[1]=='ready':eligible.append(job)
            except Exception as error:print('保留不重发：',job['account'],job['target'],str(error).split('\n',1)[0],flush=True)
        original_launch=upload.launch_context;original_finder=daily.find_published
        upload.launch_context=normal.launcher_for_jobs(selected)
        try:
            if eligible:
                print('先验证原视频的本机选取；随后只补发指定两条，每条仅再尝试一次。',flush=True)
                base.self_check(next((j for j in eligible if j.get('video_size',0)>50*1024*1024),eligible[0]))
            for job in eligible:
                state=upload.read_json(state_path,{});replacement=None;attempt=None
                try:
                    entry,status=base.validate(job,state,ledger)
                    if status=='published':continue
                    base.close_selected_window(entry['account'])
                    if upload.read_json(state_path,{})!=state:raise ValueError('关闭窗口期间记录变化，未覆盖')
                    entry,replacement=base.reserve(job,state,ledger_path,ledger)
                    attempt=dict(account=job['account'],target=job['target'],key=job['key'],started_at=datetime.now(timezone.utc).isoformat(),action='manual_required',attempt_phase=GRANT)
                    print('补发指定原视频：',entry['name'],job['account'],job['target'],job['filename'],flush=True)
                    upload.run_entry(entry,state,state_path,True,filename=job['filename'],ai_label_override=False,
                                     expected_job_key=job['key'],preserve_old_review_for_exact_job=True,retry_before_post=True,defer_comments=True)
                    attempt['action']='finished'
                except KeyboardInterrupt:raise
                except Exception as error:
                    message=(str(error) or type(error).__name__)[:2000]
                    if attempt is not None:attempt['error']=message
                    print('此条保留结果，继续下一个指定账号：',message.split('\n',1)[0],flush=True)
                finally:
                    if replacement is not None:base.settle(job,replacement,ledger_path,ledger)
                    refresh(path,value,selected,comment_rows,attempt)
            state=upload.read_json(state_path,{});published=[j for j in selected if state.get(j['key'],{}).get('status')=='published']
            if published:
                print('指定视频补发阶段结束，现在只给这两个账号中已确认成功的原视频补评论。',flush=True)
                daily.find_published=actual.make_finder(published,True,interactive=False)
                daily.backfill(dict(payload=dict(date='2026-11-04',jobs=published)),None,only_keys={j['key'] for j in published},
                               rows=comment_rows,already_locked=True,future_only=True,reporter=lambda *_:refresh(path,value,selected,comment_rows))
            rows=refresh(path,value,selected,comment_rows,final=True)
        finally:upload.launch_context=original_launch;daily.find_published=original_finder
    own=[r for r in rows if (r['account'],r['target']) in SPEC]
    return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in own) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止；已有补发和评论发送意图保留，不会重复提交。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
