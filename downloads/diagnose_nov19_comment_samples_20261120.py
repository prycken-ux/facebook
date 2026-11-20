"""Read-only checks of the user's two manually commented Nov19 sample reels."""
import contextlib,json,sys,uuid,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import archive_nov19_user_confirmed_20261120 as archive
import publish_eligible60_materials_20261119 as app

VERSION='1.0-two-user-linked-reels-readonly-comment-diagnostics'
DOM=r'''()=>{
 const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const norm=s=>(s||'').replace(/\s+/g,' ').trim();
 const texts=s=>[...document.querySelectorAll(s)].filter(visible).map(e=>norm(e.innerText||e.getAttribute('aria-label'))).filter(Boolean);
 return {headings:texts('h1,h2,[role="heading"]').slice(0,15),
  buttons:texts('button,[role="button"]').filter(t=>/comment|repl|relevant|all comments|评论|留言/i.test(t)).slice(0,25),
  textboxes:[...document.querySelectorAll('[role="textbox"],textarea')].filter(visible).map(e=>({tag:e.tagName,role:e.getAttribute('role'),label:e.getAttribute('aria-label'),placeholder:e.getAttribute('data-placeholder')||e.getAttribute('placeholder')})).slice(0,12),
  comment_articles:texts('[role="article"][aria-label^="Comment by " i]').slice(0,10).map(t=>t.slice(0,700)),
  visible_video:[...document.querySelectorAll('video')].some(visible)};
}'''


def collect(root):
    root=Path(root).resolve();first=app.first
    if root!=first.upload.ROOT.resolve():raise ValueError('评论诊断目录不符。')
    live=archive.inspect_workers(root)
    if live:raise ValueError('仍有其他发布/登录检查任务，本次未打开诊断浏览器：'+','.join(str(r['pid']) for r in live))
    _,jobs=archive.source_jobs(root)
    paused=app.read_live_pauses(root)
    folder=archive.base.safe(root,root/'logs'/('nov19-comment-samples-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]));folder.mkdir(parents=True)
    rows=[]
    from playwright.sync_api import sync_playwright
    pairs=set(archive.MANUAL_COMMENTS);pages={(a,t) for a,t in pairs if t!='personal'}
    print('归档后只读检查你提供的两个视频链接及评论定位；后台运行，不发送或修改任何评论。',flush=True)
    with first.locked(),app.response_guard.installed(),app.background_policy.installed(),first.personals.scoped({a for a,t in pairs}),first.numeric.scoped(pages),patch.object(first.numeric,'ensure',side_effect=app.browser.staged.page_identity),sync_playwright() as pw:
        for pair,link in archive.MANUAL_COMMENTS.items():
            row=dict(account=pair[0],target=pair[1],permalink=link,user_confirmed_manual_comment=True,readonly=True);context=None
            try:
                if pair[0] in paused:raise ValueError('用户暂停的账号不打开验证，保留用户手动评论确认。')
                job=jobs[pair];entry=dict(first.priority.daily.configured(job),auto_switch_personal=True)
                state=first.upload.read_json(root/'logs/publish_state.json',{});record=state.get(job['key'],{})
                row['local_comment_status']=record.get('comment_status','not_started')
                day_start=datetime.fromisoformat(archive.DAY).replace(tzinfo=timezone(timedelta(hours=8))).timestamp()
                try:start=datetime.fromisoformat(record['post_intent_at']).timestamp()-5
                except (KeyError,TypeError,ValueError):start=day_start
                end=datetime.now(timezone.utc).timestamp()+5
                context=first.normal.launch_normal(pw,entry);page=context.pages[-1] if context.pages else context.new_page();page.set_default_timeout(10000)
                first.upload.ensure_identity(page,entry);row['identity_passed']=True
                valid,diagnostic=first.priority.actual.inspect_video(page,context,entry,job['caption_text'],start,end,link,seconds=7)
                row.update(video_lookup_match=valid,video_evidence=diagnostic,comment_match_count=len(first.priority.daily.comments.scan_comments(page,entry,app.content_today.COMMENT)),page_structure=page.evaluate(DOM))
                try:page.screenshot(path=str(folder/(pair[0]+'-'+pair[1]+'.png')),timeout=3000)
                except Exception:row['screenshot_unavailable']=True
                print(pair[0]+'/'+pair[1],'视频核对=',valid,'可见本人原评论=',row['comment_match_count'],flush=True)
            except KeyboardInterrupt:raise
            except Exception as error:
                row['error']=(str(error) or type(error).__name__).split('\n',1)[0][:400]
                print('评论样本保留待检查：',pair[0],row['error'],flush=True)
            finally:
                if context is not None:
                    try:context.close()
                    except Exception as error:row['close_error']=(str(error) or type(error).__name__).split('\n',1)[0][:200]
                rows.append(row)
                first.upload.save_json(folder/'summary.json',dict(schema=VERSION,read_only=True,samples=rows))
    output=folder.with_suffix('.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix in {'.json','.png'}:z.write(path,path.name)
    print('评论定位诊断文件：',output,flush=True)
    print('请提供这个诊断ZIP，便于修复其余视频的定位；两个样本评论没有重复发送。',flush=True)
    return output
