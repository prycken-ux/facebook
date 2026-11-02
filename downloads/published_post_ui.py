"""Read-only timeline proof: exact author, full caption, absolute time, one video ID."""
import re,time
from urllib.parse import urlparse
import safe_video_comments as comments

SCAN_JS=r'''({name,owners,caption,start,end})=>{
 const norm=s=>(s||'').replace(/\s+/g,' ').trim();
 const visible=e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
 const identity=value=>{try{const u=new URL(value,location.href);if(!['facebook.com','www.facebook.com'].includes(u.hostname))return null;
 if(u.pathname==='/profile.php')return 'id:'+u.searchParams.get('id');return 'slug:'+u.pathname.replace(/^\/|\/$/g,'').toLowerCase()}catch{return null}};
 const own=a=>owners.includes(identity(a.href)) && norm(a.innerText||a.getAttribute('aria-label')).replace(/, see owner profile$/i,'')===norm(name);
 const stamp=value=>{
  if(!value)return null;let t=null,precision=1;
  if(/^\d{10,13}$/.test(value)){t=Number(value);if(t>1e12)t/=1000}
  else if(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:?\d{2})$/.test(value)){t=Date.parse(value)/1000}
  else if(/\b20\d{2}\b/.test(value)&&/\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/i.test(value)&&/\d{1,2}:\d{2}/.test(value)){
    t=Date.parse(value.replace(/\bat\b/i,' '))/1000;precision=/\d{1,2}:\d{2}:\d{2}/.test(value)?1:60;
  }
  return Number.isFinite(t)&&t>946684800?{at:t,precision}:null;
 };
 let serial=window.__localPostProofSerial||0;
 const roots=[...document.querySelectorAll('[role="article"],article')].filter(visible).slice(0,25);
 const records=[];let loading=0;
 for(const root of roots){
   if(/^Comment by /i.test(root.getAttribute('aria-label')||''))continue;
   if([...root.querySelectorAll('[role="status"]')].some(e=>visible(e)&&/^Loading/i.test(e.innerText||e.getAttribute('aria-label')||'')))loading++;
   const belongs=e=>e.closest('[role="article"],article')===root;
   const authors=[...root.querySelectorAll('a[href]')].filter(a=>belongs(a)&&visible(a)&&own(a));
   if(!authors.length)continue;
   const messages=[...root.querySelectorAll('[data-ad-preview="message"],[data-ad-comet-preview="message"],[data-testid="post_message"]')].filter(e=>belongs(e)&&visible(e));
   const texts=[...new Set(messages.map(e=>norm(e.innerText).replace(/\s*(?:See more|See less)\s*$/i,'')))];
   if(texts.length!==1)continue;
   const exact=texts[0]===norm(caption);
   const prefix=texts[0].replace(/(?:\.{3}|…)$/,'').trim();
   if(!exact && !(prefix.length>=20&&norm(caption).startsWith(prefix)))continue;
   let token=root.getAttribute('data-local-post-proof');if(!token){token=String(++serial);root.setAttribute('data-local-post-proof',token)}
   const more=[];
   if(!exact)for(const message of messages){for(const e of message.querySelectorAll('button,[role="button"],a')){
     if(visible(e)&&/^See more$/i.test(norm(e.innerText||e.getAttribute('aria-label')))){e.setAttribute('data-local-post-expand',token);more.push(token)}
   }}
   const times=[];let stampIndex=0;
   for(const e of root.querySelectorAll('a[href],time[datetime],abbr[data-utime],[data-utime]')){
     if(!belongs(e)||!visible(e))continue;
     let href=null;
     if(e.matches('a[href]')){
       try{const u=new URL(e.href);if(!['facebook.com','www.facebook.com'].includes(u.hostname)||u.searchParams.has('comment_id')||own(e))continue;href=e.href}catch{continue}
     }
     const values=[e.getAttribute('data-utime'),e.getAttribute('datetime'),e.getAttribute('title'),e.getAttribute('aria-label'),e.innerText];
     const stamps=values.map(stamp).filter(Boolean);
     const s=stamps.find(s=>s.at<end && s.at+s.precision>start)||stamps[0];
     const label=norm(e.innerText||e.getAttribute('aria-label'));
     const couldHover=e.matches('a') && (/^\d+\s*[smhdw](?:\s*·)?$/i.test(label)||/[?&]__cft__/.test(href||''));
     if(s||couldHover){const id=token+'-'+String(++stampIndex);e.setAttribute('data-local-post-timestamp',id);times.push({id,time:s||null,hover:couldHover&&!s})}
   }
   const urls=[...root.querySelectorAll('a[href]')].filter(a=>belongs(a)&&visible(a)).map(a=>a.href);
   const explicit=[...root.querySelectorAll('[data-video-id]')].filter(belongs).map(e=>e.getAttribute('data-video-id')).filter(v=>/^\d+$/.test(v));
   records.push({token,exact,expand:more.length===1,urls,explicit,times});
 }
 window.__localPostProofSerial=serial;
 return {records,loading,articles:roots.length};
}'''

TOOLTIP_TIME_JS=r'''({target,previous})=>{
 const anchor=document.querySelector('[data-local-post-timestamp="'+target+'"]');
 if(!anchor || !anchor.matches(':hover'))return null;
 const described=(anchor.getAttribute('aria-describedby')||'').split(/\s+/);
 for(const e of document.querySelectorAll('[role="tooltip"]')){
  if(!e.getClientRects().length)continue;const s=(e.innerText||'').replace(/\s+/g,' ').trim();
  if(!described.includes(e.id) && previous.includes(s))continue;
  if(!/\b20\d{2}\b/.test(s)||!/[A-Za-z]{3,9} \d{1,2},? 20\d{2}/.test(s)||!/\d{1,2}:\d{2}/.test(s))continue;
  const t=Date.parse(s.replace(/\bat\b/i,' '))/1000;if(Number.isFinite(t))return {at:t,precision:/\d{1,2}:\d{2}:\d{2}/.test(s)?1:60};
 }return null;
}'''


class TimelineProofs:
    def __init__(self,entry,owner,caption,start,end):
        import fb_upload as upload
        self.args=dict(name=entry['name'],owners=list({upload.target_key(entry['url']),'id:'+owner}),caption=caption,start=start,end=end)
        self.links=set();self.expanded=set();self.hovered=set();self.hover_times={};self.unresolved=set()
        self.stats=dict(articles=0,loading=0,exact_captions=0,timed_posts=0,unique_video_posts=0,expanded=0,hovered=0,unresolved_times=0)

    def poll(self,page,deadline):
        value=page.evaluate(SCAN_JS,self.args);records=value.get('records',[])
        self.stats.update(articles=value.get('articles',0),loading=value.get('loading',0),exact_captions=sum(r['exact'] for r in records))
        self.unresolved.update(r['token'] for r in records)
        for row in records:
            if time.monotonic()>=deadline:break
            if not row['exact']:
                if row['expand'] and row['token'] not in self.expanded and len(self.expanded)<6:
                    self.expanded.add(row['token']);control=page.locator('[data-local-post-expand="'+row['token']+'"]')
                    if control.count()==1:control.click(timeout=max(1,min(3000,int((deadline-time.monotonic())*1000))))
                    self.stats['expanded']=len(self.expanded)
                continue
            stamps=[t['time'] for t in row['times'] if t['time']]
            for item in row['times']:
                if item['id'] in self.hover_times:stamps.append(self.hover_times[item['id']])
                elif not stamps and item['hover'] and item['id'] not in self.hovered and len(self.hovered)<12 and time.monotonic()<deadline:
                    self.hovered.add(item['id']);control=page.locator('[data-local-post-timestamp="'+item['id']+'"]')
                    if control.count()==1:
                        previous=[' '.join(t.split()) for t in page.locator('[role="tooltip"]').all_text_contents()]
                        control.hover(timeout=max(1,min(2000,int((deadline-time.monotonic())*1000))))
                        until=min(deadline,time.monotonic()+1.2)
                        while time.monotonic()<until:
                            stamp=page.evaluate(TOOLTIP_TIME_JS,dict(target=item['id'],previous=previous))
                            if stamp:self.hover_times[item['id']]=stamp;stamps.append(stamp);break
                            page.wait_for_timeout(100)
                    self.stats['hovered']=len(self.hovered)
            if stamps:self.unresolved.discard(row['token'])
            else:self.unresolved.add(row['token'])
            self.stats['unresolved_times']=len(self.unresolved)
            if not any(s['at']<self.args['end'] and s['at']+s['precision']>self.args['start'] for s in stamps):continue
            self.stats['timed_posts']+=1
            links={link for url in row['urls'] if (link:=comments.direct_link(url))}
            links.update('https://www.facebook.com/reel/'+v for v in row['explicit'])
            if len(links)==1:self.links.update(links);self.stats['unique_video_posts']+=1
            elif len(links)>1:raise RuntimeError('同一匹配帖子包含多个视频，未猜选评论目标')
        self.stats['unresolved_times']=len(self.unresolved)
        return set(self.links)
