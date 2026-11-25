"""Nov25-only receipt-timeout policy and exact-video comment lookup."""
import contextlib,copy,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

VERSION='1.0-nov25-post-click-assumption-exact-comments'
DAY_PREFIX='20261125-'

def timeout_record(upload,entry,args,kwargs):
    key=kwargs.get('expected_job_key');filename=kwargs.get('filename','')
    if not key or not filename.startswith(DAY_PREFIX) or len(args)<3 or args[2] is not True:return None
    state,path=args[0],Path(args[1]);row=upload.read_json(path,{}).get(key,{})
    # post_intent_at alone is insufficient: it is persisted BEFORE button.click.
    # The native stage changes to wait_success_receipt ONLY after click returns.
    if (row.get('status')!='needs_review' or row.get('review_reason')!='publication_receipt_timeout'
            or row.get('failure_stage')!='wait_success_receipt' or not row.get('post_intent_at')
            or (row.get('account'),row.get('target'))!=(entry.get('account'),entry.get('target'))
            or Path(str(row.get('video','')).replace('\\','/')).name!=filename):return None
    if upload.target_key(row.get('url',''))!=upload.target_key(entry['url']):return None
    return key,state,path,row

def wrap_upload(upload,native):
    def run(entry,*args,**kwargs):
        try:return native(entry,*args,**kwargs)
        except upload.ReceiptNeedsReview:
            found=timeout_record(upload,entry,args,kwargs)
            if found is None:raise
            key,state,path,row=found
            row.update(status='published',assumed_published=True,video_status_before_policy='needs_review',
                       publication_confirmation_source='user_authorized_post_receipt_timeout_policy',
                       assumed_published_at=datetime.now(timezone.utc).isoformat(),comment_status='deferred')
            # Preserve original errors and submission evidence. Never invent a
            # Facebook receipt, confirmed_at, permalink, or archival result.
            disk=upload.read_json(path,{});disk[key]=row;upload.save_json(path,disk);state[key]=copy.deepcopy(row)
            print('已点击发布后回执超时；按用户规则视为成功，禁止重复上传；评论先核对对应视频：',entry['account'],entry['target'],flush=True)
            return True
    return run

def finder_factory(actual,lookup,upload,comments,native):
    def make(jobs,automatic,interactive=False,total_timeout_ms=240000):
        pairs={(j['account'],j['target']) for j in jobs}
        fallback=native(jobs,automatic,interactive=interactive,total_timeout_ms=total_timeout_ms)
        def find(page,context,entry,caption,start,end,timeout_ms=45000,diagnostic_path=None):
            if (entry['account'],entry['target']) not in pairs:raise ValueError('评论目标不在本次冻结清单')
            if not automatic:return fallback(page,context,entry,caption,start,end,timeout_ms=timeout_ms,diagnostic_path=diagnostic_path)
            began=time.monotonic()
            profile_path=diagnostic_path.with_name(diagnostic_path.stem+'-profile.json') if diagnostic_path else None
            try:
                link,method=lookup.find_published(page,context,entry,caption,start,end,
                    timeout_ms=min(18000,timeout_ms,total_timeout_ms),diagnostic_path=profile_path)
            except Exception as error:
                # Ambiguous ownership or multiple exact matches must stop the
                # operation rather than fall back and choose another candidate.
                if any(word in str(error) for word in ('多个','冲突','作者编号')):raise
                remaining=total_timeout_ms-int((time.monotonic()-began)*1000)
                if remaining<=0:raise
                # The profile lookup may navigate elsewhere; return to this
                # exact actor before opening the original Reels fallback.
                page.goto(upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=20000)
                upload.ensure_identity(page,entry)
                return native(jobs,True,interactive=interactive,total_timeout_ms=remaining)(page,context,entry,caption,start,end,timeout_ms=timeout_ms,diagnostic_path=diagnostic_path)
            # Metadata proof binds owner + full caption + upload-time + video
            # ID. The detail page must still bind exact URL and visible author;
            # a headless video player need not be playing to allow commenting.
            canonical=comments.direct_link(link)
            if not canonical or method not in {'verified_owner_caption_time','verified_owner_caption_time_reels_tabs'}:raise ValueError('缺少对应视频的完整核实证据')
            page.goto(upload.english_url(canonical),wait_until='domcontentloaded',timeout=20000)
            upload.checkpoint(page);upload.require_no_advanced_protection(page)
            if comments.direct_link(page.url)!=canonical:raise ValueError('已核实视频链接跳转到其他视频')
            actual.require_target_author(page,entry)
            editor=page.get_by_role('form',name='Reels',exact=True)
            if any(editor.nth(i).is_visible() for i in range(editor.count())):raise ValueError('仍处于未发布的Reels编辑器，未评论')
            if diagnostic_path:upload.save_json(diagnostic_path,dict(matches=[canonical],method=method,lookup_version=VERSION,profile_proof=str(profile_path)))
            return canonical,method
        return find
    return make

@contextlib.contextmanager
def installed(app):
    upload=app.first.upload;actual=app.first.priority.actual;native=upload.run_entry;report=app.report
    import published_video_lookup as lookup
    import safe_video_comments as comments
    make=finder_factory(actual,lookup,upload,comments,actual.make_finder)
    def annotated_report(req,material,controller,path):
        rows=report(req,material,controller,path);state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        for row in rows:
            source=state.get(row.get('key'),{})
            row.update(assumed_published=source.get('assumed_published',False),publication_confirmation_source=source.get('publication_confirmation_source',''))
        controller['rows']=rows;controller['assumed_published_count']=sum(r['assumed_published'] for r in rows if not r['user_paused'])
        upload.save_json(path,controller)
        note='其中按用户超时规则视为成功：'+str(controller['assumed_published_count'])+'；原始超时证据保留，评论结果单独统计。'
        print(note,flush=True)
        with path.with_suffix('.txt').open('a',encoding='utf-8') as handle:handle.write('\n'+note+'\n')
        return rows
    with patch.object(upload,'run_entry',side_effect=wrap_upload(upload,native)),patch.object(app,'report',side_effect=annotated_report),patch.object(actual,'make_finder',side_effect=make):yield
