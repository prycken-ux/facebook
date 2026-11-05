"""Exact comment-target lookup; unresolved targets continue without prompting."""
import re,time
from datetime import datetime
from urllib.parse import parse_qs,urljoin,urlparse,urlencode
import fb_upload as upload
import safe_video_comments as comments
import published_video_lookup as lookup
import daily_publish_and_comments as daily

LOOKUP_VERSION='1.1-fragments-jsonld-noninteractive'
REELS_ENTRY_VERSION='1.0-owner-route-fallback'


class AutomaticLookupPending(RuntimeError):pass

SCAN=r'''()=>{const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const read=s=>[...document.querySelectorAll(s)].filter(visible).map(e=>e.href);
 return {main:read('main a[href],[role="main"] a[href]'),all:read('a[href]')}}'''


def stamp(value):
    try:
        if isinstance(value,(int,float)) or str(value).replace('.','',1).isdigit():
            result=float(value);return result/1000 if result>1e12 else result
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed.timestamp() if parsed.tzinfo else 0
    except (ValueError,TypeError,OverflowError):return 0


def text(value):return value.get('text','') if isinstance(value,dict) else value if isinstance(value,str) else ''


class Evidence:
    def __init__(self,owner,caption,start,end,link,owner_aliases=()):
        self.owner=owner;self.caption=comments.normalized(caption);self.start=start;self.end=end;self.link=link
        self.vid=urlparse(link).path.rstrip('/').split('/')[-1]
        self.matched=False;self.blocked=False;self.published=False;self.owner_seen=False;self.caption_seen=False;self.time_seen=False;self.nodes=0
        self.typed_seen=False;self.ld_nodes=0;self.owner_keys={'id:'+owner}|set(owner_aliases)
    def add(self,payload):
        if self.caption and self.link in lookup.story_videos(payload,self.owner,self.caption,self.start,self.end):
            self.matched=True;self.owner_seen=True;self.caption_seen=True;self.time_seen=True
        def walk(node,blocked=False):
            if isinstance(node,list):
                for child in node:walk(child,blocked)
            elif isinstance(node,dict):
                bad=node.get('is_published') is False or bool(node.get('is_pending')) or bool(node.get('is_draft'))
                inherited=blocked or (node.get('__typename')=='Story' and bad)
                if node.get('__typename') in {None,'Video','Reel'} and str(node.get('id',''))==self.vid:
                    self.typed_seen|=node.get('__typename') in {'Video','Reel'}
                    self.nodes+=1;story=node.get('creation_story',{})
                    if not isinstance(story,dict):story={}
                    story_bad=story.get('is_published') is False or bool(story.get('is_pending')) or bool(story.get('is_draft'))
                    if inherited or bad or story_bad:self.blocked=True
                    owners={str(v['id']) for field in ('owner','video_owner','owning_profile') if isinstance((v:=node.get(field)),dict) and v.get('id')}
                    actors={str(v['id']) for v in story.get('actors',[]) if isinstance(v,dict) and v.get('id')}
                    if owners and owners!={self.owner}:self.blocked=True
                    if actors and actors!={self.owner}:self.blocked=True
                    owned=owners=={self.owner} or not owners and actors=={self.owner}
                    caption=bool(self.caption) and any(comments.normalized(text(v))==self.caption for v in (node.get('message'),node.get('description'),story.get('message')))
                    timed=any(self.start<=stamp(v)<self.end for area in (node,story) for v in (area.get('creation_time'),area.get('publish_time'),area.get('created_time')))
                    for field in ('permalink_url','url'):
                        canonical=comments.direct_link(node.get(field,''))
                        if canonical and canonical!=self.link:self.blocked=True
                    self.owner_seen|=owned;self.caption_seen|=caption;self.time_seen|=timed
                    self.published|=node.get('is_published') is True
                for child in node.values():
                    if isinstance(child,(dict,list)):walk(child,inherited)
        walk(payload)
        self.matched|=self.typed_seen and self.owner_seen and self.caption_seen and self.time_seen
    def add_ld(self,payload):
        def walk(node):
            if isinstance(node,list):
                for child in node:walk(child)
            elif isinstance(node,dict):
                types=node.get('@type',[]);types=[types] if isinstance(types,str) else types
                links={comments.direct_link(node.get(k,'')) for k in ('url','@id','embedUrl')};links.discard(None)
                if isinstance(types,list) and 'VideoObject' in types and self.link in links:
                    self.ld_nodes+=1
                    if links!={self.link}:self.blocked=True
                    authors=node.get('author',[]);authors=authors if isinstance(authors,list) else [authors]
                    keys=set()
                    for author in authors:
                        values=[author.get('url'),author.get('@id')] if isinstance(author,dict) else [author]
                        for value in values:
                            try:
                                if value:keys.add(upload.target_key(value))
                            except (ValueError,TypeError):pass
                    owned=bool(keys&self.owner_keys)
                    if keys and (not owned or keys-self.owner_keys):self.blocked=True
                    caption=bool(self.caption) and comments.normalized(text(node.get('description')))==self.caption
                    timed=any(self.start<=stamp(node.get(k))<self.end for k in ('uploadDate','datePublished'))
                    self.owner_seen|=owned;self.caption_seen|=caption;self.time_seen|=timed
                    self.matched|=owned and caption and timed
                for child in node.values():
                    if isinstance(child,(dict,list)):walk(child)
        walk(payload)
    def diagnostic(self):return dict(video=self.link,nodes=self.nodes,json_ld_nodes=self.ld_nodes,owner=self.owner_seen,caption=self.caption_seen,time=self.time_seen,matched=self.matched,blocked=self.blocked,explicit_published=self.published)


def require_target_author(page,entry):
    comments.require_video_author(page,entry,timeout_ms=3000)
    owners={upload.target_key(entry['url'])}
    if entry.get('type')=='personal':
        owners.update('id:'+c['value'] for c in page.context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and str(c.get('value','')).isdecimal())
    anchors=page.get_by_role('link',name=re.compile(r'^'+re.escape(entry['name'])+r'(?:, see owner profile)?$',re.I))
    for i in range(anchors.count()):
        anchor=anchors.nth(i)
        if not anchor.is_visible() or not anchor.evaluate('''e=>!e.closest('[role="article"][aria-label^="Comment by " i],nav,[role="navigation"]')'''):continue
        try:
            if upload.target_key(urljoin('https://www.facebook.com/',anchor.get_attribute('href') or '')) in owners:return
        except ValueError:pass
    raise ValueError('未看到视频作者的有效主页链接；不使用评论里的作者链接作为视频作者证据')


def inspect_video(page,context,entry,caption,start,end,link,seconds=7):
    owner=upload.target_key(entry['url'])
    aliases={owner}
    if not owner.startswith('id:') and entry.get('type')=='personal':
        try:
            upload.personal_actor_fingerprint(page,entry)
            owners={c['value'] for c in context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and str(c.get('value','')).isdecimal()}
            if len(owners)==1:owner='id:'+next(iter(owners))
        except Exception:return False,dict(video=link,error='无法核验本人个人号身份')
    if not owner.startswith('id:'):return False,dict(video=link,error='缺少已核验的视频作者编号')
    evidence=Evidence(owner[3:],caption,start,end,link,aliases)
    def receive(response):
        try:
            parsed=urlparse(response.url)
            if parsed.hostname in {'facebook.com','www.facebook.com'} and parsed.path.rstrip('/')=='/api/graphql':
                for payload in lookup.payloads(response.text()):evidence.add(payload)
        except Exception:pass
    context.on('response',receive)
    try:
        page.goto(upload.english_url(link),wait_until='domcontentloaded',timeout=20000)
        deadline=time.monotonic()+seconds;since=None;seen=set()
        while time.monotonic()<deadline:
            upload.checkpoint(page);upload.require_no_advanced_protection(page)
            if comments.direct_link(page.url)!=link:raise ValueError('视频页跳转到其他视频')
            for kind in ('application/json','application/ld+json'):
                for raw in page.locator('script[type="'+kind+'"]').all_text_contents():
                    if (kind,raw) in seen:continue
                    seen.add((kind,raw))
                    for payload in lookup.payloads(raw):
                        if kind=='application/ld+json':evidence.add_ld(payload)
                        else:evidence.add(payload)
            if evidence.blocked:break
            if evidence.matched:
                if since is None:since=time.monotonic()
                if time.monotonic()-since>=1:break
            page.wait_for_timeout(200)
        visible_video=any(page.locator('video').nth(i).is_visible() for i in range(page.locator('video').count()))
        editor=page.get_by_role('form',name='Reels',exact=True)
        has_editor=any(editor.nth(i).is_visible() for i in range(editor.count()))
        valid=evidence.matched and not evidence.blocked and (visible_video or evidence.published) and not has_editor
        if valid:require_target_author(page,entry)
        return bool(valid),dict(evidence.diagnostic(),visible_video=visible_video,editor=has_editor)
    except Exception as error:return False,dict(evidence.diagnostic(),error=(str(error) or type(error).__name__).split('\n',1)[0][:300])
    finally:context.remove_listener('response',receive)


def open_actual_reels(page):
    tabs=page.get_by_role('tab',name='Reels',exact=True)
    visible=[tabs.nth(i) for i in range(tabs.count()) if tabs.nth(i).is_visible()]
    if len(visible)!=1:raise ValueError('没有唯一可见的本主页Reels标签')
    visible[0].click(timeout=10000)


def collect_links(page,seconds=8,entry=None):
    try:open_actual_reels(page)
    except ValueError:
        if entry is None:raise
        upload.target_key(entry['url'])
        parsed=urlparse(entry['url']);params=parse_qs(parsed.query);params['sk']=['reels_tab']
        route=parsed._replace(query=urlencode(params,doseq=True),fragment='').geturl()
        print('没有唯一可见的Reels标签；改从该主页的Reels地址只读查找。',flush=True)
        page.goto(upload.english_url(route),wait_until='domcontentloaded',timeout=30000)
    end=time.monotonic()+seconds;links=set();scrolls=0
    while time.monotonic()<end:
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        scan=page.evaluate(SCAN)
        for value in scan['main'] or scan['all']:
            link=comments.direct_link(value)
            if link:links.add(link)
        if scrolls<3:page.mouse.wheel(0,600);scrolls+=1
        page.wait_for_timeout(350)
    return sorted(links)


def validate_selected(page,entry,raw):
    parsed=urlparse(raw)
    if parsed.scheme!='https' or parsed.hostname not in {'facebook.com','www.facebook.com','m.facebook.com','web.facebook.com','fb.watch'} or parsed.username or parsed.password or parsed.port:
        raise ValueError('请使用Facebook具体视频的https网址')
    normalized=parsed._replace(netloc='www.facebook.com').geturl() if parsed.hostname in {'m.facebook.com','web.facebook.com'} else raw
    canonical=comments.direct_link(normalized)
    if not canonical and not (parsed.hostname=='fb.watch' or re.fullmatch(r'/share/[rv]/[A-Za-z0-9]+/?',parsed.path)):
        raise ValueError('这不是具体视频链接；请打开视频或复制视频分享链接')
    page.goto(upload.english_url(canonical or raw),wait_until='domcontentloaded',timeout=30000)
    end=time.monotonic()+15
    while time.monotonic()<end:
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        link=comments.direct_link(page.url)
        if link:
            require_target_author(page,entry);return link
        page.wait_for_timeout(250)
    raise ValueError('分享链接未跳转到具体视频，请复制打开后的视频地址')


def manual_choice(page,context,entry,job,baseline):
    print('\n需要你选定这一条原视频：',entry['account'],entry['target'],job['filename'],flush=True)
    print('在浏览器打开对应视频后回到此窗口按回车；也可直接粘贴视频网址。S跳过本条，Q结束。选择后程序自动评论并刷新核验。',flush=True)
    while True:
        raw=input('视频网址/回车读取/S/Q：').strip()
        if raw.upper()=='Q':raise KeyboardInterrupt
        if raw.upper()=='S':raise RuntimeError('用户跳过本条，尚未发送评论')
        if not raw:
            links=set()
            for candidate in context.pages:
                if candidate is page or candidate not in baseline:
                    try:
                        if not candidate.is_closed() and (link:=comments.direct_link(candidate.url)):links.add(link)
                    except Exception:pass
            if len(links)!=1:
                print('未读到唯一视频地址，请先点开正确视频，或直接粘贴该视频网址。',flush=True);continue
            raw=next(iter(links))
        try:return validate_selected(page,entry,raw),'user_supplied_exact_job_link'
        except Exception as error:print('未发送评论：',str(error).split('\n',1)[0],flush=True)


def make_finder(jobs,automatic,interactive=False,total_timeout_ms=240000):
    by_pair={(j['account'],j['target']):j for j in jobs}
    def find(page,context,entry,caption,start,end,timeout_ms=45000,diagnostic_path=None):
        job=by_pair[(entry['account'],entry['target'])];baseline=set(context.pages);proofs=[];matches=[];candidates=[];error=''
        deadline=time.monotonic()+total_timeout_ms/1000
        if automatic:
            try:
                candidates=collect_links(page,entry=entry)
                print('从实际Reels入口取得候选视频：',len(candidates),'条；按作者、原文案和时间核对。',flush=True)
                for i,link in enumerate(candidates,1):
                    if time.monotonic()>=deadline:raise ValueError('自动核对时间已到，候选尚未全部核验；保留待定位')
                    child=context.new_page()
                    try:valid,proof=inspect_video(child,context,entry,caption,start,end,link)
                    finally:child.close()
                    proofs.append(proof);print('只读核对候选',i,'/',len(candidates),'：','匹配' if valid else '数据或条件未满足完整匹配',flush=True)
                    if valid:matches.append(link)
                if len(matches)==1:
                    page.goto(upload.english_url(matches[0]),wait_until='domcontentloaded',timeout=30000)
                    require_target_author(page,entry)
                    return matches[0],'verified_owner_caption_time'
                error='未取得唯一匹配：候选'+str(len(candidates))+'条，完整匹配'+str(len(matches))+'条；作者/文案/时间缺少或不符：'+str(sum(not p.get('owner') for p in proofs))+'/'+str(sum(not p.get('caption') for p in proofs))+'/'+str(sum(not p.get('time') for p in proofs))
                print(error,flush=True)
            except Exception as failure:error=str(failure).split('\n',1)[0];print('自动定位未完成：',error,flush=True)
            finally:
                if diagnostic_path:upload.save_json(diagnostic_path,dict(candidates=candidates,matches=matches,proofs=proofs,error=error))
        else:
            try:open_actual_reels(page)
            except Exception:pass
        if not interactive:raise AutomaticLookupPending('自动定位暂未完成：'+(error or '缺少唯一匹配证据')+'；未发送评论，已记录待自动核验')
        return manual_choice(page,context,entry,job,baseline)
    return find
