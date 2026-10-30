"""Locate a user-confirmed published video by owner, caption, time and unique ID.

Never select the newest reel or a global View reel link. Raw responses stay in RAM.
"""
import json
import re
import time
from datetime import datetime
from urllib.parse import urlparse
import fb_upload as upload
import safe_video_comments as comments


def payloads(raw):
    if not isinstance(raw,str) or len(raw)>4_000_000:return []
    raw=re.sub(r'^\s*for\s*\(\s*;;\s*\)\s*;','',raw)
    try:return [json.loads(raw)]
    except ValueError:
        result=[]
        for line in raw.splitlines():
            try:result.append(json.loads(line))
            except ValueError:pass
        return result


def story_videos(payload,owner,caption,start,end):
    found=set();fragments={};standalone=[];blocked=set()
    fields=('actors','message','creation_time','attachments','is_published','is_pending','is_draft')
    def collect(node):
        if isinstance(node,list):
            for child in node:collect(child)
        elif isinstance(node,dict):
            if node.get('__typename')=='Story':
                identity=node.get('id')
                if isinstance(identity,str) and identity:
                    merged=fragments.setdefault(identity,{'__typename':'Story','id':identity})
                    for field in fields:
                        value=node.get(field)
                        if value is None or value=='' or value==[] or value=={}:continue
                        if field in merged and merged[field]!=value:blocked.add(identity)
                        else:merged[field]=value
                else:standalone.append(node)
            for child in node.values():
                if isinstance(child,(dict,list)):collect(child)
    collect(payload)
    def walk(node):
        if isinstance(node,list):
            for child in node:walk(child)
        elif isinstance(node,dict):
            if node.get('__typename')=='Story':
                if node.get('id') in blocked:return
                actors=node.get('actors',[])
                ids={str(a.get('id','')) for a in actors if isinstance(a,dict)} if isinstance(actors,list) else set()
                message=node.get('message',{})
                text=message.get('text','') if isinstance(message,dict) else message
                try:created=float(node.get('creation_time',0))
                except (TypeError,ValueError):created=0
                if (ids=={owner} and comments.normalized(text)==comments.normalized(caption)
                        and start<=created<end and node.get('is_published') is not False
                        and not node.get('is_pending') and not node.get('is_draft')):
                    links=set();conflict=False
                    def media(value):
                        nonlocal conflict
                        if isinstance(value,list):
                            for child in value:media(child)
                        elif isinstance(value,dict):
                            # Never descend into a nested shared story or unrelated actor.
                            if value.get('__typename')=='Story':return
                            if value.get('__typename') in {'Video','Reel'}:
                                own=value.get('owner') or value.get('video_owner')
                                if isinstance(own,dict) and str(own.get('id',''))!=owner:
                                    conflict=True;return
                                if value.get('is_published') is False:return
                                for field in ('permalink_url','url'):
                                    link=comments.direct_link(value.get(field,''))
                                    if link:links.add(link)
                                vid=str(value.get('id',''))
                                if vid.isdecimal():links.add('https://www.facebook.com/reel/'+vid)
                            for child in value.values():
                                if isinstance(child,(dict,list)):media(child)
                    media(node.get('attachments',[]))
                    # /owner/videos/id and /reel/id are the same video ID.
                    keyed={urlparse(link).path.rstrip('/').split('/')[-1]:link for link in links}
                    if not conflict and len(keyed)==1:found.add('https://www.facebook.com/reel/'+next(iter(keyed)))
            for child in node.values():
                if isinstance(child,(dict,list)):walk(child)
    for identity,value in fragments.items():
        if identity not in blocked:walk(value)
    for value in standalone:walk(value)
    return found


class Lookup:
    def __init__(self,context,entry,caption,start,end):
        key=upload.target_key(entry['url'])
        self.owner=key[3:] if key.startswith('id:') else None
        if self.owner is None and entry.get('type')=='personal':
            owners=[c['value'] for c in context.cookies(['https://www.facebook.com/']) if c['name']=='c_user']
            if len(owners)==1:self.owner=owners[0]
        if not self.owner:raise RuntimeError('缺少可核实的视频作者编号，未猜选评论目标')
        self.caption=caption;self.start=start;self.end=end;self.links=set()
        self.context=context;context.on('response',self.receive)

    def add(self,raw):
        for value in payloads(raw):self.links.update(story_videos(value,self.owner,self.caption,self.start,self.end))

    def receive(self,response):
        try:
            parsed=urlparse(response.url)
            if parsed.hostname not in {'facebook.com','www.facebook.com'} or parsed.path.rstrip('/')!='/api/graphql':return
            self.add(response.text())
        except Exception:pass

    def close(self):self.context.remove_listener('response',self.receive)


def find_published(page,context,entry,caption,start,end,timeout_ms=25000):
    lookup=Lookup(context,entry,caption,start,end)
    deadline=time.monotonic()+timeout_ms/1000
    try:
        page.goto(upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=min(15000,timeout_ms))
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        scrolled=False
        while time.monotonic()<deadline:
            for raw in page.locator('script[type="application/json"]').all_text_contents():lookup.add(raw)
            if len(lookup.links)>1:raise RuntimeError('同作者、文案及日期匹配多个视频，未猜选最新评论目标')
            if not scrolled:
                page.mouse.wheel(0,650);scrolled=True
            page.wait_for_timeout(min(1000,max(1,int((deadline-time.monotonic())*1000))))
        if len(lookup.links)!=1:raise RuntimeError('未找到唯一匹配作者、文案和发布时间的视频，请补该原视频链接')
        return next(iter(lookup.links)),'verified_owner_caption_time'
    finally:lookup.close()
