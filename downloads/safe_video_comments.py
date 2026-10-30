"""One authorized top-level comment on the exact newly published video, never replies."""
import hashlib
import json
import re
import time
from datetime import datetime,timezone
from urllib.parse import urlparse,parse_qs

import fb_upload as upload


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def normalized(text):
    return ' '.join(str(text or '').split())


def direct_link(value):
    try:
        parsed=urlparse(value)
        if parsed.scheme!='https' or parsed.hostname not in {'facebook.com','www.facebook.com'} or parsed.username or parsed.password or parsed.port:
            return None
        if parsed.path.rstrip('/') in {'/watch','/video.php'}:
            values=parse_qs(parsed.query).get('v',[])
            if len(values)==1 and values[0].isdecimal():return 'https://www.facebook.com/reel/'+values[0]
            return None
        match=re.fullmatch(r'/(?:reels/|[A-Za-z0-9._-]+/videos/)([0-9]+)/?',parsed.path)
        if match:return 'https://www.facebook.com/reel/'+match[1]
        return upload.normalize_video_permalink('https://www.facebook.com'+parsed.path)
    except (ValueError,TypeError):
        return None


def public_nodes(payload,expected_owner,caption,since):
    result=[]
    def walk(node,inherited_caption=''):
        if isinstance(node,list):
            for child in node:walk(child,inherited_caption)
        elif isinstance(node,dict):
            message=inherited_caption
            for field in ('message','description'):
                value=node.get(field)
                if isinstance(value,dict):value=value.get('text')
                if isinstance(value,str):message=value
            owner=node.get('owner') or node.get('video_owner')
            owner_id=str(owner.get('id','')) if isinstance(owner,dict) else ''
            video_id=str(node.get('id',''))
            created=node.get('creation_time',node.get('publish_time'))
            try:created=float(created)
            except (ValueError,TypeError):created=0
            if (node.get('__typename') in {'Video','Reel'} and video_id.isdecimal()
                and owner_id==expected_owner and normalized(message)==normalized(caption)
                and created>=since-5 and created<=time.time()+60 and node.get('is_published') is True):
                result.append('https://www.facebook.com/reel/'+video_id)
            for child in node.values():
                if isinstance(child,(dict,list)):walk(child,message)
    walk(payload)
    return result


class PublicationLinks:
    def __init__(self,context,entry,caption,created):
        key=upload.target_key(entry['url'])
        self.owner=key[3:] if key.startswith('id:') else None
        if self.owner is None and entry.get('type')=='personal':
            owners=[c['value'] for c in context.cookies(['https://www.facebook.com/']) if c['name']=='c_user']
            if len(owners)==1:self.owner=owners[0]
        self.caption=caption
        self.since=datetime.fromisoformat(created).timestamp()
        self.armed=False
        self.links=set()
        context.on('response',self.receive)

    def receive(self,response):
        if not self.armed or not self.owner:return
        try:
            parsed=urlparse(response.url)
            if parsed.hostname not in {'facebook.com','www.facebook.com'} or parsed.path.rstrip('/')!='/api/graphql':return
            raw=response.text()
            if len(raw)>4_000_000:return
            raw=re.sub(r'^\s*for\s*\(\s*;;\s*\)\s*;','',raw)
            try:payloads=[json.loads(raw)]
            except ValueError:
                payloads=[]
                for line in raw.splitlines():
                    try:payloads.append(json.loads(line))
                    except ValueError:pass
            for payload in payloads:self.links.update(public_nodes(payload,self.owner,self.caption,self.since))
        except Exception:
            pass  # Never export raw GraphQL, headers, cookies or request bodies.


class PublishedLinkNotReady(RuntimeError):pass


def _published_link_once(page,context,collector):
    current=direct_link(page.url)
    if current:return current,'fresh_post_navigation'
    links=set()
    receipts=page.evaluate('() => window.__fbUploadWatch && window.__fbUploadWatch.receiptLinks || []')
    if isinstance(receipts,list):
        for link in receipts:
            value=direct_link(link)
            if value:links.add(value)
    proven=set(collector.links) if collector else set()
    if links and proven and len(links|proven)!=1:
        raise RuntimeError('成功提示的视频链接与本次发布数据不一致，评论需手动核实')
    if len(links)==1:return next(iter(links)),'fresh_success_view_reel_link'
    if len(proven)==1:return next(iter(proven)),'published_video_owner_caption_creation_match'
    area=page.locator('[data-local-current-publication-receipt="true"]')
    views=area.get_by_role('button',name=re.compile(r'^(?:View|See) (?:your )?(?:reel|video)$',re.I))
    visible=[views.nth(i) for i in range(views.count()) if views.nth(i).is_visible()]
    opened=page.evaluate('() => Boolean(window.__fbUploadWatch && window.__fbUploadWatch.viewOpened)')
    if len(visible)==1 and not opened:
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        old_pages=set(context.pages)
        page.evaluate('() => {window.__fbUploadWatch.viewOpened=true}')
        visible[0].click(timeout=10000)
        deadline=time.monotonic()+5000/1000
        while time.monotonic()<deadline:
            current=direct_link(page.url)
            if current:return current,'fresh_success_view_reel_button'
            new_links={direct_link(p.url) for p in context.pages if p not in old_pages}
            new_links.discard(None)
            if len(new_links)==1:return next(iter(new_links)),'fresh_success_view_reel_new_tab'
            page.wait_for_timeout(100)
    if len(links)>1 or len(proven)>1:
        raise RuntimeError('出现多条候选视频链接，未猜选评论目标')
    raise PublishedLinkNotReady('无法唯一定位刚发布的视频直达链接，视频保留成功状态；评论需手动处理')



def publication_link_hint(page,collector):
    """Collect only passive evidence while uploads take priority; never open comments."""
    links=set(collector.links) if collector else set()
    current=direct_link(page.url)
    if current:links.add(current)
    receipts=page.evaluate('() => window.__fbUploadWatch && window.__fbUploadWatch.receiptLinks || []')
    if isinstance(receipts,list):
        links.update(value for item in receipts if (value:=direct_link(item)))
    ids={urlparse(value).path.rstrip('/').split('/')[-1] for value in links}
    if len(ids)==1:return 'https://www.facebook.com/reel/'+next(iter(ids))
    return None


def resolve_published_link(page,context,collector,timeout_ms=0):
    from playwright.sync_api import Error as BrowserError
    deadline=time.monotonic()+timeout_ms/1000
    navigation_retries=0
    while True:
        try:return _published_link_once(page,context,collector)
        except PublishedLinkNotReady:
            upload.checkpoint(page);upload.require_no_advanced_protection(page)
            if time.monotonic()>=deadline:raise
            page.wait_for_timeout(250)
        except BrowserError as error:
            if 'Execution context was destroyed' not in str(error) or navigation_retries or time.monotonic()>=deadline:raise
            navigation_retries+=1
            upload.checkpoint(page)
            page.wait_for_load_state('domcontentloaded',timeout=max(1,min(5000,int((deadline-time.monotonic())*1000))))


COMMENT_SCAN_JS=r'''({name,text,urls}) => {
 const norm=s=>(s||'').replace(/\s+/g,' ').trim();
 const matches=[];
 for(const node of document.querySelectorAll('[role="article"][aria-label]')){
   const label=node.getAttribute('aria-label')||'';
   if(!label.toLowerCase().startsWith('comment by '+name.toLowerCase())) continue;
   if(!node.getClientRects().length)continue;
   const copy=node.cloneNode(true);
   for(const e of copy.querySelectorAll('[contenteditable],textarea,[role="textbox"]')) e.remove();
   const body=norm(copy.textContent);
   const prefix=norm(text.split('\n')[0]);
   if(!body.includes(prefix))continue;
   const found=[...node.querySelectorAll('a[href]')].map(a=>{
     try{let u=new URL(a.href);if(u.hostname==='l.facebook.com')return u.searchParams.get('u');return u.href}catch{return null}
   });
   if(!urls.every(url=>found.includes(url)||body.includes(url)))continue;
   const author=[...node.querySelectorAll('a[href]')].some(a=>norm(a.innerText)===norm(name));
   if(author) matches.push({label,body:body.slice(0,600)});
 }
 return matches;
}'''


def scan_comments(page,entry,text):
    urls=re.findall(r'https://[^\s]+',text)
    found=page.evaluate(COMMENT_SCAN_JS,dict(name=entry['name'],text=text,urls=urls))
    return found if isinstance(found,list) else []


class CommentComposerMissing(RuntimeError):pass


def comment_field(page):
    fields=page.get_by_role('textbox',name=re.compile(r'^(?:Write a (?:public )?comment(?: as .+)?(?:\.{3}|…)?|Comment as .+)$',re.I))
    visible=[fields.nth(i) for i in range(fields.count()) if fields.nth(i).is_visible() and fields.nth(i).is_editable()]
    if not visible:raise CommentComposerMissing('评论输入框尚未出现')
    if len(visible)!=1:raise RuntimeError('未找到唯一顶层评论输入框，不使用 Reply 或猜测位置；请手动评论')
    field=visible[0]
    if not field.evaluate('''e=>{
      if(/reply/i.test((e.getAttribute('aria-label')||'')+' '+(e.getAttribute('data-placeholder')||'')))return false;
      if(e.closest('[role="article"][aria-label^="Comment by " i]'))return false;
      const modals=[...document.querySelectorAll('[role="dialog"],[role="alertdialog"],dialog')].filter(d=>d.getClientRects().length);
      return modals.every(d=>d.contains(e));
    }'''):raise RuntimeError('评论框属于回复或被其他弹窗遮挡，未发送')
    return field



def ready_comment_field(page,timeout_ms=30000):
    deadline=time.monotonic()+timeout_ms/1000
    expanded=False
    while True:
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        try:return comment_field(page)
        except CommentComposerMissing:pass
        if not expanded:
            # Bare "Comment" can be a draft's send button, so never use it to expand.
            controls=page.get_by_role('button',name=re.compile(r'^(?:Comments|Leave a comment|See comments)$',re.I))
            buttons=[controls.nth(i) for i in range(controls.count()) if controls.nth(i).is_visible()]
            if len(buttons)>1:raise RuntimeError('展开评论入口不唯一，未猜选')
            if buttons:
                button=buttons[0]
                if not button.evaluate("""e=>[...document.querySelectorAll('[role="dialog"],[role="alertdialog"],dialog')]
                    .filter(d=>d.getClientRects().length).every(d=>d.contains(e))"""):
                    raise RuntimeError('评论入口被其他弹窗遮挡，未发送')
                if button.get_attribute('aria-expanded')!='true':button.click(timeout=5000)
                expanded=True
        if time.monotonic()>=deadline:raise RuntimeError('顶层评论框未加载；不使用 Reply 或不明 Comment 按钮，需手动评论')
        page.wait_for_timeout(250)


def send_control(field):
    area=field.locator('..')
    for _ in range(4):
        if area.evaluate("e=>e.matches('body,main,[role=main]')"):break
        if area.locator('video').count() or area.get_by_role('textbox').count()!=1 or area.get_by_role('button').count()>8:break
        controls=area.get_by_role('button',name=re.compile(r'^(?:Comment|Send comment|Post comment|Post a comment|Send)$',re.I))
        visible=[controls.nth(i) for i in range(controls.count()) if controls.nth(i).is_visible()]
        if len(visible)==1:
            from playwright.sync_api import expect
            expect(visible[0]).to_be_enabled(timeout=15000)
            return visible[0]
        if len(visible)>1:raise RuntimeError('评论发送按钮不唯一，未发送')
        area=area.locator('..')
    # Enter is allowed only when this exact field has an explicit UI instruction.
    hint=field.evaluate(r"""e=>{
      let text=e.getAttribute('aria-description')||'';
      for(const id of (e.getAttribute('aria-describedby')||'').split(/\s+/)){
        const node=document.getElementById(id);if(node)text+=' '+node.innerText;
      }return text;
    }""")
    if isinstance(hint,str) and re.search(r'\bPress Enter to (?:post|send)(?: your comment)?[.!]?(?:\s|$)',hint,re.I):
        return ExplicitEnter(field)
    raise RuntimeError('没有唯一明确的评论发送按钮或明确的 Enter 发送说明，需手动评论')


class ExplicitEnter:
    def __init__(self,field):self.field=field
    def click(self,timeout=10000):self.field.press('Enter',timeout=timeout)


def capture_failure(page,key,error):
    folder=upload.ROOT/'logs'
    (folder/('comment-'+key[:12]+'-error.txt')).write_text(str(error),encoding='utf-8')
    try:
        if page.locator('input[type=password]:visible').count():return
        page.screenshot(path=str(folder/('comment-'+key[:12]+'.png')),timeout=10000)
        (folder/('comment-'+key[:12]+'.aria.txt')).write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
    except Exception:pass


def after_publication(page,context,entry,proof,key,record,text,collector,verified_link=None):
    if record.get('status')!='published':raise ValueError('视频未确认成功，不评论')
    if not text.strip() or len(text)>5000:raise ValueError('评论文案为空或过长')
    ledger_path=upload.ROOT/'logs/video_comments.json'
    ledger=upload.read_json(ledger_path,{})
    comment_key=hashlib.sha256((key+'\0'+text_hash(text)).encode()).hexdigest()
    existing=ledger.get(comment_key)
    if existing:
        if existing.get('status') in {'sent','already_present'}:return existing
        if existing.get('status') in {'sending','needs_review'}:
            raise RuntimeError('此条评论已有发送意图或结果待核实，不自动重发')
    attempted=False
    item=dict(account=entry['account'],target=entry['target'],video_job=key,text=text,
        text_sha256=text_hash(text),created=datetime.now(timezone.utc).isoformat(),status='preparing')
    try:
        if verified_link is not None:
            permalink,method=verified_link
            if method not in {'verified_owner_caption_time','user_supplied_exact_job_link','previously_verified_exact_job_link'} or not direct_link(permalink):
                raise ValueError('补评论链接缺少确切任务核验')
            permalink=direct_link(permalink)
        else:
            try:
                permalink,method=resolve_published_link(page,context,collector,timeout_ms=15000)
            except PublishedLinkNotReady:
                caption_text=record.get('published_caption_text')
                if not isinstance(caption_text,str) or not caption_text.strip():raise
                from published_video_lookup import find_published
                since=datetime.fromisoformat(record['created']).timestamp()-5
                permalink,method=find_published(page,context,entry,caption_text,since,time.time()+60,timeout_ms=15000)
        item.update(permalink=permalink,link_method=method)
        record['permalink']=permalink
        record['comment_link_job_key']=key
        record['comment_link_method']=method
        if direct_link(page.url)!=permalink:
            page.goto(upload.english_url(permalink),wait_until='domcontentloaded',timeout=90000)
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        upload.recheck_publish_identity(page,entry,proof)
        if entry.get('type')=='page' and not upload.page_actor_matches(page,entry):
            raise RuntimeError('无法确认当前评论身份为该公共主页，视频保持成功，评论需手动处理')
        author=page.get_by_role('link',name=entry['name'],exact=True)
        from playwright.sync_api import expect
        expect(author.first).to_be_visible(timeout=30000)
        if scan_comments(page,entry,text):
            item['status']='already_present';ledger[comment_key]=item;upload.save_json(ledger_path,ledger);return item
        field=ready_comment_field(page)
        field.fill(text)
        actual=field.input_value() if field.evaluate("e=>e.matches('input,textarea')") else field.inner_text()
        if actual.replace('\r\n','\n')!=text.replace('\r\n','\n'):raise RuntimeError('评论框文字与授权原文不一致，未发送')
        send=send_control(field)
        if direct_link(page.url)!=permalink:raise RuntimeError('发送前视频页面已变化，未发送')
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        upload.recheck_publish_identity(page,entry,proof)
        if entry.get('type')=='page' and not upload.page_actor_matches(page,entry):
            raise RuntimeError('发送前公共主页评论身份未通过核验，未发送')
        item['status']='sending';ledger[comment_key]=item;upload.save_json(ledger_path,ledger)
        attempted=True
        send.click(timeout=10000)
        deadline=time.monotonic()+60000/1000
        while time.monotonic()<deadline:
            upload.checkpoint(page)
            if scan_comments(page,entry,text):
                actual=field.input_value() if field.evaluate("e=>e.matches('input,textarea')") else field.inner_text()
                if not actual.strip():
                    item.update(status='sent',confirmed_at=datetime.now(timezone.utc).isoformat())
                    ledger[comment_key]=item;upload.save_json(ledger_path,ledger);return item
            page.wait_for_timeout(500)
        raise RuntimeError('已尝试发送，但未确认本人评论出现并清空输入框；结果需手动核实，勿重复发')
    except Exception as error:
        item.update(status='needs_review' if attempted else 'manual_required',error=str(error)[:2000])
        ledger[comment_key]=item;upload.save_json(ledger_path,ledger)
        capture_failure(page,key,error)
        return item
