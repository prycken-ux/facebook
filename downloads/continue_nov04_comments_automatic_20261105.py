"""Continue only Nov-4 successful-video comments; no video submissions or prompts."""
import hashlib,shutil,sys,uuid
from datetime import datetime,timezone
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import safe_video_comments as comments
import actual_reels_comment_lookup as actual
import normal_chrome_batch as normal
import retry_nov04_after_local_file_fix_20261105 as original_source
from add_fb_accounts import locked

PROTECTED={'sent','already_present','sending','verifying','needs_review'}
STEM='11月4日成功视频自动评论-20261105'


def comment_key(job):return hashlib.sha256((job['key']+'\0'+comments.text_hash(daily.COMMENT)).encode()).hexdigest()


def restore_link(job,row,item):
    if row.get('comment_status') in PROTECTED or item.get('status') in PROTECTED:return False
    if row.get('comment_link_job_key')==job['key'] and comments.direct_link(row.get('permalink','')):return False
    if row.get('comment_link_job_key') not in {None,'',job['key']}:return False
    method=item.get('link_method','');known=method in {'verified_owner_caption_time','verified_owner_caption_time_reels_tabs','user_supplied_exact_job_link','previously_verified_exact_job_link','published_video_owner_caption_creation_match'}
    known|=isinstance(method,str) and method.startswith('fresh_')
    link=comments.direct_link(item.get('permalink',''))
    if (not known or not link or item.get('status')!='manual_required' or item.get('video_job')!=job['key']
            or (item.get('account'),item.get('target'))!=(job['account'],job['target'])
            or item.get('text_sha256')!=comments.text_hash(daily.COMMENT)):return False
    row.update(permalink=link,comment_link_job_key=job['key'],comment_link_method='previously_verified_exact_job_link')
    return True


def report(path,value,jobs,rows,final=False):
    state_path=upload.ROOT/'logs/publish_state.json';state=upload.read_json(state_path,{});changed=False
    ledger=upload.read_json(upload.ROOT/'logs/video_comments.json',{})
    for result in rows:
        row=state.get(result['key'],{});receipt=ledger.get(comment_key(result),{})
        if (result.get('status')=='manual_required' and result.get('error','').startswith('自动定位暂未完成：')
                and row.get('status')=='published' and receipt.get('status') not in PROTECTED):
            result['status']='lookup_pending'
            if row.get('comment_status')!='lookup_pending':row['comment_status']='lookup_pending';changed=True
    if changed:upload.save_json(state_path,state)
    prior=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if prior.get('manifest')!=path.name or not isinstance(prior.get('attempts'),list):raise ValueError('原发布报告变化，未覆盖')
    batch.results(path,value,prior['attempts'],None,final=final)
    if final:
        upload.save_json(upload.ROOT/'logs'/(STEM+'.json'),dict(source_manifest=path.name,video_upload_started=False,interactive_selection=False,rows=rows))
        labels={'sent':'评论已刷新确认成功','already_present':'已有规定评论','lookup_pending':'待自动定位，未发送','manual_required':'评论未完成','needs_review':'发送结果待核实，不重复发','sending':'已有发送意图，不重复发','verifying':'已有发送意图，不重复发'}
        lines=['11月4日成功视频自动评论结果（本次没有上传或补发视频）']
        for row in rows:
            line=row['account']+'/'+row['target']+' '+row['filename']+'：'+labels.get(row['status'],row['status'])
            if row.get('error'):line+='；'+row['error'].split('\n',1)[0]
            lines.append(line)
        lines.append('本次确认成功/已存在：'+str(sum(r['status'] in {'sent','already_present'} for r in rows))+' / '+str(len(jobs)))
        print('\n'.join(lines),flush=True);(upload.ROOT/'logs'/(STEM+'.txt')).write_text('\n'.join(lines),encoding='utf-8-sig')


def execute():
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!='2026-11-05':raise ValueError('此继续程序仅用于11月5日处理11月4日原批次评论')
    if getattr(actual,'LOOKUP_VERSION','')!='1.1-fragments-jsonld-noninteractive':raise ValueError('自动定位改进模块未安装')
    with locked(),daily.keep_awake():
        path,value,all_jobs=original_source.source();state_path=upload.ROOT/'logs/publish_state.json';state=upload.read_json(state_path,{})
        jobs=[]
        for job in all_jobs:
            row=state.get(job['key'],{})
            if row.get('status')!='published':continue
            if ((row.get('account'),row.get('target'))!=(job['account'],job['target'])
                    or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
                    or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):raise ValueError('已成功记录与原视频不一致')
            daily.configured(job);jobs.append(job)
        backup=upload.ROOT/'backups'/('nov04-auto-comments-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        for file in (state_path,upload.ROOT/'logs/video_comments.json',path.with_name(path.stem+'-results.json')):
            if file.is_file():shutil.copy2(file,backup/file.name)
        ledger=upload.read_json(upload.ROOT/'logs/video_comments.json',{});restored=False
        for job in jobs:restored=restore_link(job,state[job['key']],ledger.get(comment_key(job),{})) or restored
        if restored:upload.save_json(state_path,state)
        print('本次只自动评论已确认成功的视频：',len(jobs),'条；其余原视频保留。不会逐条要求手动选视频。',flush=True)
        original_launch=upload.launch_context;original_finder=daily.find_published;rows=[]
        upload.launch_context=normal.launcher_for_jobs(jobs)
        daily.find_published=actual.make_finder(jobs,True,interactive=False)
        try:
            if jobs:
                work=dict(payload=dict(date='2026-11-04',jobs=jobs))
                daily.backfill(work,None,only_keys={j['key'] for j in jobs},rows=rows,already_locked=True,future_only=True,
                               reporter=lambda *_:report(path,value,jobs,rows))
            report(path,value,jobs,rows,final=True)
        finally:upload.launch_context=original_launch;daily.find_published=original_finder
    return 0 if all(r['status'] in {'sent','already_present'} for r in rows) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止；评论发送意图和原视频成功状态保留。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
