"""Find the exact submitted video before commenting, even with no Post receipt."""
import contextlib
import copy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

VERSION='1.0-pending-video-exact-lookup-before-comments'
DONE={'sent','already_present'}
PENDING={'sending','verifying','needs_review'}


def resolve(first,manifest,only_keys,validate,allowed,seen):
    from playwright.sync_api import sync_playwright
    jobs=manifest['payload']['jobs']
    state_path=first.upload.ROOT/'logs/publish_state.json'
    for job in jobs:
        if (only_keys is not None and job['key'] not in only_keys) or not allowed(job):
            continue
        state=first.upload.read_json(state_path,{})
        old=copy.deepcopy(state.get(job['key'],{}))
        if old.get('status')!='needs_review' or not old.get('post_intent_at') or old.get('comment_status') in DONE:
            continue
        token=job['key'],old.get('post_intent_at'),old.get('source_frozen_manifest')
        if token in seen:
            continue
        seen.add(token)
        print('待核实视频进入原评论定位：',job['account'],job['target'],'；不重新上传。',flush=True)
        try:
            if ((old.get('account'),old.get('target'))!=(job['account'],job['target'])
                    or first.upload.target_key(old.get('url',''))!=first.upload.target_key(job['url'])
                    or str(old.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):
                raise ValueError('待核实记录与本次原视频不符')
            name=old.get('source_frozen_manifest','')
            if not name or Path(name).name!=name:
                raise ValueError('缺少本次原冻结来源')
            source_path=first.upload.ROOT/'logs'/name
            source=first.archive.checked_json(source_path)
            validate(source_path,source)
            if (source['sha256']!=old.get('source_frozen_sha256')
                    or not any(j==job for j in source['payload']['jobs'])
                    or source['payload'].get('queue_id')!=manifest['payload'].get('queue_id')
                    or source['payload'].get('publication_content_sha256')!=manifest['payload'].get('publication_content_sha256')):
                raise ValueError('待核实视频不属于本次授权清单')
            entry=dict(first.priority.daily.configured(job))
            if (first.batch.digest(entry)!=job['entry_sha256']
                    or not first.batch.eligible(entry,True,date=manifest['payload']['date'])):
                raise ValueError('原登记目标或发布授权发生变化')
            first.batch.content_for_payload(source['payload'])
            if any(r.get('account')==job['account'] and r.get('status') in {'preparing','posting'} for r in state.values()):
                raise ValueError('该账号另有进行中的视频，先跳过评论定位')
            since=datetime.fromisoformat(old['post_intent_at']).timestamp()-5
            if datetime.fromisoformat(old['created']).timestamp()<datetime.fromisoformat(source['created_at']).timestamp()-5:
                raise ValueError('原任务时间与本次冻结来源不符')
            end=datetime.now(timezone.utc).timestamp()+5
            comments=first.priority.daily.comments
            unique_hint=(old.get('fresh_publication_job_key')==job['key']
                         and old.get('fresh_publication_candidate_count')==1)
            hint=comments.direct_link(old.get('fresh_publication_candidate','')) if unique_hint else None
            explicit=(hint and old.get('fresh_publication_explicit_published') is True)
            if explicit:
                link,method=hint,'fresh_owned_published_metadata_for_comment'
            else:
                entry=dict(entry,auto_switch_personal=True)
                first.close_selected_window(entry['account'])
                with sync_playwright() as pw:
                    context=first.upload.launch_context(pw,entry)
                    try:
                        page=context.pages[0] if context.pages else context.new_page()
                        page.set_default_timeout(15000)
                        page.goto(first.upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000)
                        first.upload.ensure_identity(page,entry)
                        valid=False
                        if hint:
                            valid,_=first.priority.actual.inspect_video(page,context,entry,job['caption_text'],since,end,hint)
                        if valid:
                            link,method=hint,'verified_owner_caption_time_for_comment'
                        else:
                            finder=first.priority.actual.make_finder([job],True,interactive=False,total_timeout_ms=45000)
                            link,method=finder(page,context,entry,job['caption_text'],since,end,
                                diagnostic_path=first.upload.ROOT/'logs'/('pending-comment-'+job['key'][:12]+'-lookup.json'))
                    finally:
                        context.close()
            if not comments.direct_link(link):
                raise ValueError('没有取得本次视频的有效直链')
            current=first.upload.read_json(state_path,{})
            if current.get(job['key'])!=old:
                raise ValueError('定位期间记录变化，未覆盖')
            row=current[job['key']];now=datetime.now(timezone.utc).isoformat()
            row.update(status='published',confirmation_method=method,confirmed_at=now,confirmed_batch_lookup_cutoff=now,
                       permalink=link,comment_link_job_key=job['key'],comment_link_method=method,
                       video_status_before_comment_lookup='needs_review',error='',review_reason='')
            if row.get('comment_status') not in DONE|PENDING:
                row['comment_status']='deferred'
            first.upload.save_json(state_path,current)
            video=first.upload.inbox_for(entry)/job['filename']
            if (video.is_file() and first.upload.job_key(entry,video)==job['key']
                    and video.with_suffix('.txt').is_file()
                    and first.batch.file_hash(video.with_suffix('.txt'))==job['caption_sha256']):
                try:
                    folder=first.upload.archive(video,video.with_suffix('.txt'))
                    row.update(archived_video=str(folder/video.name),archived_caption=str(folder/video.with_suffix('.txt').name),archived_at=now)
                    first.upload.save_json(state_path,current)
                except Exception as error:
                    print('视频已核实；本地归档稍后处理：',job['account'],str(error).split('\n',1)[0],flush=True)
            print('已定位本次视频，继续原评论：',job['account'],job['target'],link,flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as error:
            message=(str(error) or type(error).__name__).split('\n',1)[0]
            current=first.upload.read_json(state_path,{})
            if current.get(job['key'])==old and old.get('comment_status') not in DONE|PENDING:
                current[job['key']].update(comment_status='lookup_pending',comment_error=message,
                                         pending_comment_lookup_at=datetime.now(timezone.utc).isoformat())
                first.upload.save_json(state_path,current)
            print('本次视频评论待定位，先继续其他目标：',job['account'],job['target'],message,flush=True)


@contextlib.contextmanager
def installed(first,validate,allowed):
    native=first.priority.daily.backfill
    seen=set()
    def backfill(manifest,output_dir,*args,**kwargs):
        with (contextlib.nullcontext() if kwargs.get('already_locked') else first.locked()):
            resolve(first,manifest,kwargs.get('only_keys'),validate,allowed,seen)
        return native(manifest,output_dir,*args,**kwargs)
    with patch.object(first.priority.daily,'backfill',side_effect=backfill):
        yield seen
