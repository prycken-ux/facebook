"""Conservative browser trial: exact logged-in actor, exact media and verified comment."""
import json,os,re,socket,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
import ig10_common_20261127 as c
BASE='https://www.instagram.com'
OWN_PROFILE_NAV=r'''() => {
 const reserved = new Set(['accounts','explore','reels','direct','stories','create']);
 const anchors = Array.from(document.querySelectorAll('a[href]'));
 const names = anchors.filter(a => {
  const r = a.getBoundingClientRect();
  const own = /^(Profile|个人主页|個人檔案)$/i;
  return r.width > 0 && r.height > 0 && r.x < 230 &&
   (a.querySelector('img') || own.test(a.innerText.trim()) || own.test(a.getAttribute('aria-label') || ''));
 }).map(a => {
  try { const m = new URL(a.href).pathname.match(/^\/([A-Za-z0-9._]+)\/$/); return m ? m[1] : null; }
  catch (e) { return null; }
 }).filter(name => name && !reserved.has(name));
 return Array.from(new Set(names));
}'''
class SessionProblem(RuntimeError):pass
class ReceiptPending(RuntimeError):pass


def remaining(start,limit=15000):return max(1,min(limit,int((c.VIDEO_SECONDS-(time.monotonic()-start)-8)*1000)))
def visible(locator):
 for i in range(locator.count()):
  part=locator.nth(i)
  if part.is_visible():return part
 return None

def checked(control):
 value=control.get_attribute('aria-checked')
 if value in {'true','false'}:return value=='true'
 if control.evaluate('(e)=>e.tagName')=='INPUT':return control.is_checked()
 raise RuntimeError('无法读取AI/评论开关状态，未发布')

def click_named(scope,names,timeout=10000,required=True):
 for role in ('button','link'):
  part=visible(scope.get_by_role(role,name=names))
  if part is not None:part.click(timeout=timeout);return True
 if required:raise RuntimeError('网页按钮尚未找到：'+str(names.pattern))
 return False

def assert_session(page):
 if re.search(r'/accounts/login|/challenge|/checkpoint|/two_factor',page.url,re.I) or visible(page.locator('input[name="password"]')) is not None:raise SessionProblem('IG登录已失效或需要本人验证，未绕过')
 for label in [r'^Only allow essential cookies$',r'^Decline optional cookies$',r'^仅允许必要.*',r'^只允許必要.*']:
  click_named(page,re.compile(label,re.I),required=False,timeout=3000)

def actor(page,expected):
 assert_session(page)
 result=page.evaluate('''async () => {const a=new AbortController();const t=setTimeout(()=>a.abort(),8000);try{const r=await fetch('/api/v1/accounts/current_user/?edit=true',{credentials:'same-origin',headers:{'X-IG-App-ID':'936619743392459'},signal:a.signal});if(!r.ok)return null;const d=await r.json();if(d.status==='ok'&&d.user)return {username:d.user.username,pk:String(d.user.pk||d.user.id||''),is_private:d.user.is_private};return null;}catch(e){return null;}finally{clearTimeout(t);}}''')
 if not result or not result.get('username'):
  names=page.evaluate(OWN_PROFILE_NAV)
  if len(names)!=1:raise SessionProblem('无法唯一核对当前登录账号，未用个人主页网址代替登录证据')
  result=dict(username=names[0],pk=None,is_private=None)
 if result['username'].casefold()!=expected.casefold():raise SessionProblem('窗口账号不匹配：实际 '+result['username']+'，预期 '+expected)
 return result

def media_nodes(payload):
 found=[];count=0
 def walk(node,depth=0):
  nonlocal count
  count+=1
  if count>25000 or depth>24:return
  if isinstance(node,list):
   for v in node:walk(v,depth+1)
  elif isinstance(node,dict):
   code=node.get('code') or node.get('shortcode');owner=node.get('user') or node.get('owner') or {}
   caption=node.get('caption');caption=caption.get('text') if isinstance(caption,dict) else caption
   if not isinstance(caption,str):
    edges=node.get('edge_media_to_caption',{}).get('edges',[])
    caption=edges[0].get('node',{}).get('text') if edges else None
   taken=node.get('taken_at') or node.get('taken_at_timestamp');video=node.get('is_video') is True or node.get('media_type')==2 or node.get('product_type')=='clips'
   if isinstance(code,str) and re.fullmatch('[A-Za-z0-9_-]{5,32}',code) and isinstance(owner,dict) and isinstance(caption,str) and isinstance(taken,(int,float)) and video:
    found.append(dict(code=code,owner=owner.get('username'),owner_id=str(owner.get('pk') or owner.get('id') or ''),caption=caption,taken_at=taken,is_video=True,blocked=any(node.get(k) is True for k in ('is_draft','is_pending','is_archived'))))
   for v in node.values():
    if isinstance(v,(dict,list)):walk(v,depth+1)
 walk(payload);return found

def matches(node,job,identity,since,until,baseline=()):
 return (not node['blocked'] and node['code'] not in baseline and (str(node.get('owner') or '').casefold()==job['username'].casefold() or bool(identity.get('pk')) and node.get('owner_id')==identity['pk']) and c.norm(node['caption'])==c.norm(c.CAPTION) and since-120<=node['taken_at']<=until+120)

class Capture:
 def __init__(self,page,job,identity,since,baseline):
  self.page=page;self.job=job;self.identity=identity;self.since=since;self.baseline=set(baseline);self.found={};self.armed=False;self.queue=[]
  # Never read a body inside a response event: it may still be downloading and
  # re-entrant sync Playwright calls can defer it until the page has navigated.
  page.on('requestfinished',self.receive)
 def add(self,payload):
  for node in media_nodes(payload):
   if matches(node,self.job,self.identity,self.since,time.time(),self.baseline):self.found[node['code']]=node
 def receive(self,request):
  if not self.armed:return
  from urllib.parse import urlparse
  p=urlparse(request.url)
  if p.hostname not in {'www.instagram.com','instagram.com'} or not re.search(r'/api/v1/media/configure|/api/v1/feed/user|/api/graphql|/graphql/query',p.path):return
  if len(self.queue)<64:self.queue.append(request)
 def drain(self):
  queued,self.queue=self.queue,[]
  for request in queued:
   try:
    r=request.response()
    if r is not None and r.status==200:
     raw=r.text()
     if len(raw)<=3_000_000:self.add(json.loads(raw))
   except Exception:pass
 def single(self):
  self.drain()
  if len(self.found)>1:raise RuntimeError('同一作者、正文和时间有多个视频匹配，未猜选最新一条')
  return next(iter(self.found.values())) if self.found else None

def links(page):
 return {c.shortcode(u):c.canonical(u) for u in page.locator('a[href]').evaluate_all('(xs)=>xs.map(x=>x.href)') if c.canonical(u)}
def collect_embedded(page,capture):
 for raw in page.locator('script[type="application/json"]').all_text_contents():
  if len(raw)>3_000_000:continue
  try:capture.add(json.loads(raw))
  except (json.JSONDecodeError,ValueError):pass

def detail(page,url,job,proof):
 if not c.canonical(url) or c.shortcode(url)!=proof['code']:raise RuntimeError('评论视频链接与提交证据不符')
 page.goto(url,wait_until='domcontentloaded',timeout=25000);assert_session(page)
 if c.shortcode(page.url)!=proof['code']:raise RuntimeError('视频页跳转到了其他视频')
 article=visible(page.locator('article'))
 if article is None:article=visible(page.locator('main'))
 if article is None:raise RuntimeError('确切视频详情尚未加载')
 owner=visible(article.locator('header a[href="/'+job['username']+'/"],h2 a[href="/'+job['username']+'/"],h3 a[href="/'+job['username']+'/"]'))
 if owner is None:raise RuntimeError('视频详情作者未核对通过')
 if c.norm(c.CAPTION) not in c.norm(article.inner_text()):
  for text in ['more','更多','展开','展開']:
   loc=visible(article.get_by_text(text,exact=True))
   if loc is not None:loc.click(timeout=3000);break
 if c.norm(c.CAPTION) not in c.norm(article.inner_text()):raise RuntimeError('视频详情未显示完整原正文，未评论')
 if visible(article.locator('video')) is None and article.locator('video').count()==0:raise RuntimeError('未核对到视频媒体，未评论')
 return article

def recover(page,job,row,identity,start):
 known=row.get('media_proof')
 if known:
  url='https://www.instagram.com/reel/'+known['code']+'/'
  detail(page,url,job,known);return url,known
 since=datetime.fromisoformat(row['upload_started_at']).timestamp();post=datetime.fromisoformat(row.get('submit_click_returned_at') or row['post_intent_at']).timestamp()
 capture=Capture(page,job,identity,since,row.get('baseline_codes',[]));capture.armed=True
 try:
  page.goto(BASE+'/'+job['username']+'/',wait_until='domcontentloaded',timeout=25000);assert_session(page);page.wait_for_timeout(1500);collect_embedded(page,capture)
  candidates=links(page);pending=[u for code,u in candidates.items() if code not in set(row.get('baseline_codes',[]))]
  for url in pending[:8]:
   if time.monotonic()-start>140:break
   page.goto(url,wait_until='domcontentloaded',timeout=20000);page.wait_for_timeout(800);collect_embedded(page,capture)
  capture.drain();values=[n for n in capture.found.values() if n['taken_at']<=post+600]
  if len(values)!=1:raise RuntimeError('未取得唯一原视频的作者/正文/时间/视频ID证明，未猜选或评论')
  proof=values[0];url='https://www.instagram.com/reel/'+proof['code']+'/'
  detail(page,url,job,proof);return url,proof
 finally:page.remove_listener('requestfinished',capture.receive)

def prepare_and_share(page,context,root,job,start):
 page.goto(BASE+'/'+job['username']+'/',wait_until='domcontentloaded',timeout=25000)
 identity=actor(page,job['username']);base=links(page);upload_at=c.stamp()
 c.update(root,job['key'],identity=identity,identity_verified_at=c.stamp(),upload_started_at=upload_at,baseline_codes=sorted(base),video_status='preparing')
 capture=Capture(page,job,identity,datetime.fromisoformat(upload_at).timestamp(),base);capture.armed=False
 try:
  if not click_named(page,re.compile(r'^(Create|创建|新建|建立)$',re.I),required=False):
   icon=visible(page.locator('svg[aria-label="New post"],svg[aria-label="新建帖子"],svg[aria-label="Create"]'))
   if icon is None:raise RuntimeError('未找到Instagram创建入口，未选择视频')
   icon.locator('xpath=ancestor::*[self::a or self::button or @role="button"][1]').click(timeout=10000)
  page.wait_for_timeout(700)
  upload_scope=visible(page.get_by_role('dialog'))
  inputs=upload_scope.locator('input[type="file"]') if upload_scope is not None else page.locator('input[type="file"][accept*="video" i]')
  if inputs.count()==0:click_named(page,re.compile(r'^(Post|帖子|貼文|Reel|连拍视频)$',re.I),required=False)
  upload_scope=visible(page.get_by_role('dialog'))
  inputs=upload_scope.locator('input[type="file"]') if upload_scope is not None else page.locator('input[type="file"][accept*="video" i]')
  if inputs.count()==0:
   with page.expect_file_chooser(timeout=10000) as event:click_named(page,re.compile(r'^(Select from computer|从电脑中选择|從電腦選擇)$',re.I))
   event.value.set_files(str(root/job['video']))
  else:inputs.last.set_input_files(str(root/job['video']),timeout=15000)
  c.update(root,job['key'],selected_file=job['video'],selected_video_sha256=job['video_sha256'])
  caption=None;scope=page
  for _ in range(5):
   modal=visible(page.get_by_role('dialog'));scope=modal or page
   caption=visible(scope.locator('[contenteditable="true"][role="textbox"],textarea[aria-label*="caption" i],textarea[aria-label*="说明"],textarea[aria-label*="說明"]'))
   if caption is not None:break
   crop=visible(scope.get_by_role('button',name=re.compile('Select crop|选择裁剪|選擇裁切',re.I)))
   if crop is not None:
    crop.click();original=visible(page.get_by_text(re.compile(r'^(Original|原图|原始比例|原始)$',re.I)))
    if original is None:raise RuntimeError('未找到原始比例，未擅自裁剪上传视频')
    original.click()
   click_named(scope,re.compile(r'^(Next|下一步)$',re.I),timeout=remaining(start,45000));page.wait_for_timeout(700)
  if caption is None:raise RuntimeError('未找到Instagram正文编辑框，未点击发布')
  caption.fill(c.CAPTION,timeout=10000)
  current=caption.input_value() if caption.evaluate('(e)=>e.tagName') in {'TEXTAREA','INPUT'} else caption.inner_text()
  if c.norm(current)!=c.norm(c.CAPTION):raise RuntimeError('原正文未完整填写，未发布')
  click_named(scope,re.compile(r'^(Advanced settings|高级设置|進階設定)$',re.I),required=False,timeout=3000)
  ai=visible(scope.get_by_role('switch',name=re.compile('AI label|AI info|AI.*标签|AI.*標籤|人工智能',re.I)))
  if ai is None:ai=visible(scope.get_by_role('checkbox',name=re.compile('AI label|AI.*标签|AI.*標籤',re.I)))
  ai_evidence='not_exposed_no_self_label_added'
  if ai is not None:
   if checked(ai):ai.click(timeout=3000)
   if checked(ai):raise RuntimeError('AI标签未关闭，未发布')
   ai_evidence='visible_control_verified_off'
  off=visible(scope.get_by_role('switch',name=re.compile('Turn off commenting|关闭评论|關閉留言',re.I)))
  if off is not None:
   if checked(off):off.click(timeout=3000)
   if checked(off):raise RuntimeError('评论仍被关闭，未发布')
  actor(page,job['username'])
  c.update(root,job['key'],ai_label_requested=False,ai_control_evidence=ai_evidence,post_intent_at=c.stamp(),failure_stage='click_share',video_status='posting')
  capture.armed=True
  click_named(scope,re.compile(r'^(Share|分享|共享)$',re.I),timeout=remaining(start,12000))
  c.update(root,job['key'],submit_click_returned_at=c.stamp(),failure_stage='wait_receipt')
  page.wait_for_timeout(500)
  while time.monotonic()-start<170:
   assert_session(page);proof=capture.single()
   if proof:
    c.update(root,job['key'],media_proof=proof)
    url='https://www.instagram.com/reel/'+proof['code']+'/'
    detail(page,url,job,proof)
    c.update(root,job['key'],video_status='published',assumed_published=False,permalink=url,confirmed_at=c.stamp(),publication_confirmation_source='exact_owner_caption_time_media_id_and_detail')
    return
   # The share notice alone never invents a media ID/link. Try own-profile metadata once.
   notice=visible(page.get_by_text(re.compile(r'(Your (?:post|reel) has been shared|已分享你的|已分享您的|帖子已分享|连拍视频已分享)',re.I)))
   if notice is not None:
    page.wait_for_timeout(500)
    if capture.single():continue
    row=c.state(root)[job['key']];url,proof=recover(page,job,row,identity,start)
    c.update(root,job['key'],video_status='published',assumed_published=False,media_proof=proof,permalink=url,confirmed_at=c.stamp(),publication_confirmation_source='exact_owner_caption_time_media_id_and_detail');return
   page.wait_for_timeout(1000)
  raise ReceiptPending('已点击Share，但未取得确切视频回执；按用户规则保留视为成功的出处，不重复上传')
 finally:page.remove_listener('requestfinished',capture.receive)

def own_comment(article,username,text):
 rows=article.evaluate('''(root)=>[...root.querySelectorAll('ul li')].filter(li=>!li.querySelector('li')).map(li=>({author:li.querySelector('h3 a[href],h2 a[href]')?.getAttribute('href')||'',text:li.innerText}));''')
 return any(r['author'].strip('/').casefold()==username.casefold() and c.norm(text) in c.norm(r['text']) for r in rows)

def comment(page,context,root,job,start):
 page.goto(BASE+'/',wait_until='domcontentloaded',timeout=25000);identity=actor(page,job['username']);row=c.state(root)[job['key']]
 if not c.submission(row):raise RuntimeError('视频没有提交记录，未评论')
 url,proof=recover(page,job,row,identity,start);article=detail(page,url,job,proof)
 c.update(root,job['key'],video_status='published',assumed_published=False,permalink=url,media_proof=proof,confirmed_at=row.get('confirmed_at') or c.stamp())
 ledger_path=root/'logs/ig-comment-state.json';ledger=c.read(ledger_path,{})
 key=c.digest(dict(video_job=job['key'],text=c.COMMENT));item=ledger.get(key,{})
 if item and (item.get('permalink')!=url or item.get('username')!=job['username']):raise RuntimeError('评论账本身份/视频冲突')
 if item.get('verification')=='own_comment_seen_after_reload':
  c.update(root,job['key'],comment_status=item['status'],comment_verification=item['verification'],comment_verified_at=item['verified_at']);return
 present=own_comment(article,job['username'],c.COMMENT)
 if not present and (item.get('status') in {'sending','verifying','needs_review'} or row.get('comment_send_intent_at')):raise RuntimeError('此前评论已发送或结果不明，未重复发送；保留待核实')
 if not present:
  editor=visible(article.locator('textarea[aria-label*="comment" i],textarea[placeholder*="comment" i],textarea[aria-label*="评论"],textarea[aria-label*="留言"],[contenteditable="true"][role="textbox"]'))
  if editor is None:raise RuntimeError('未找到这条视频的评论输入框')
  editor.fill(c.COMMENT,timeout=10000)
  got=editor.input_value() if editor.evaluate('(e)=>e.tagName') in {'TEXTAREA','INPUT'} else editor.inner_text()
  if c.norm(got)!=c.norm(c.COMMENT):raise RuntimeError('首评正文未完整填写')
  c.update(root,job['key'],comment_send_intent_at=c.stamp(),comment_status='sending')
  item=dict(video_job=job['key'],username=job['username'],account=job['account'],permalink=url,text_sha256=c.digest(c.COMMENT),status='sending',send_intent_at=c.stamp());ledger[key]=item;c.save(ledger_path,ledger)
  form=editor.locator('xpath=ancestor::form[1]');button=visible(form.get_by_role('button',name=re.compile(r'^(Post|发布|發佈|发送|張貼)$',re.I)))
  if button is not None:button.click(timeout=10000)
  else:editor.press('Enter',timeout=10000)
  item.update(status='verifying',click_returned_at=c.stamp());c.save(ledger_path,ledger);page.wait_for_timeout(1500)
 page.reload(wait_until='domcontentloaded',timeout=25000);actor(page,job['username']);article=detail(page,url,job,proof)
 for _ in range(15):
  if own_comment(article,job['username'],c.COMMENT):
   item=dict(item,video_job=job['key'],username=job['username'],account=job['account'],permalink=url,text_sha256=c.digest(c.COMMENT),status='sent' if not present else 'already_present',verification='own_comment_seen_after_reload',verified_at=c.stamp());ledger[key]=item;c.save(ledger_path,ledger)
   c.update(root,job['key'],comment_status=item['status'],comment_verification=item['verification'],comment_verified_at=item['verified_at']);return
  page.wait_for_timeout(1000)
 item.update(status='needs_review',error='刷新后未核验到本人的原文评论');ledger[key]=item;c.save(ledger_path,ledger);raise RuntimeError(item['error'])
