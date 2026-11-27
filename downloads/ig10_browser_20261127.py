"""Conservative browser trial: exact logged-in actor, exact media and verified comment."""
import json,os,re,socket,subprocess,time,uuid
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

CREATE_NAMES=re.compile(r'^(Create|New post|Create new post|New content|创建|创建新帖子|新建帖子|新帖子|新建内容|新内容|建立新貼文|建立|\+)$',re.I)
UPLOAD_NAMES=re.compile(r'^(Select from computer|从电脑中选择|从电脑选择|從電腦選擇|從電腦中選擇)$',re.I)
CREATE_TITLES=re.compile(r'^(Create new post|New post|创建新帖子|新建帖子|建立新貼文)$',re.I)
FIRST_PHOTO=re.compile(r'^(Share your first photo|分享你的首张照片|分享您的首张照片|分享你的第一張相片|分享你的首張相片)$',re.I)
CREATE_WAIT_SECONDS=30

def named_control(scope,names):
 for role in ('button','link'):
  item=visible(scope.get_by_role(role,name=names))
  if item is not None:return item
 return None

def creation_scope(page):
 # A cookie/highlight dialog does not count as the photo/video upload dialog.
 dialogs=page.get_by_role('dialog')
 for index in range(dialogs.count()-1,-1,-1):
  modal=dialogs.nth(index)
  if not modal.is_visible():continue
  if named_control(modal,UPLOAD_NAMES) is not None or modal.locator('input[type="file"][accept*="video" i]').count():return modal
 # Some portal layouts omit role=dialog; require both the observed title and upload action.
 if visible(page.get_by_text(CREATE_TITLES,exact=True)) is not None and (named_control(page,UPLOAD_NAMES) is not None or visible(page.get_by_text(UPLOAD_NAMES,exact=True)) is not None):return page
 return None

def creation_control(page,username):
 item=named_control(page,CREATE_NAMES)
 if item is not None:return item,'named_create'
 # Generic New is accepted only in the left rail, never the central New Highlight.
 for role in ('button','link'):
  controls=page.get_by_role(role,name=re.compile(r'^(New|新建)$',re.I))
  for index in range(controls.count()):
   item=controls.nth(index);box=item.bounding_box()
   if item.is_visible() and box and box['x']<140:return item,'sidebar_new'
 icons=page.locator('svg[aria-label]')
 for index in range(icons.count()):
  icon=icons.nth(index)
  if not icon.is_visible() or not CREATE_NAMES.fullmatch(icon.get_attribute('aria-label') or ''):continue
  parent=icon.locator('xpath=ancestor::*[self::a or self::button or @role="button" or @role="link"][1]')
  return (parent if parent.count() else icon),'sidebar_create_icon'
 if page.url.rstrip('/')==BASE+'/'+username:
  item=visible(page.get_by_text(FIRST_PHOTO,exact=True))
  if item is not None:return item,'empty_profile_first_photo'
 return None,None

def open_creation(page,job,start,record=lambda **kw:None):
 deadline=min(time.monotonic()+CREATE_WAIT_SECONDS,start+c.VIDEO_SECONDS-25);requested=False;menu_selected=False;went_home=False;origin=time.monotonic()
 while time.monotonic()<deadline:
  assert_session(page);scope=creation_scope(page)
  if scope is not None:record(creation_dialog_verified_at=c.stamp());return scope
  if requested and not menu_selected:
   menu=visible(page.get_by_role('menu'))
   item=visible(page.get_by_role('menuitem',name=re.compile(r'^(Post|帖子|貼文|Reel|连拍视频)$',re.I)))
   if item is None and menu is not None:item=named_control(menu,re.compile(r'^(Post|帖子|貼文)$',re.I))
   if item is not None:item.click(timeout=remaining(start,5000));menu_selected=True
  if not requested:
   item,method=creation_control(page,job['username'])
   if item is not None:
    item.click(timeout=remaining(start,5000));requested=True;record(creation_entry_method=method,creation_entry_clicked_at=c.stamp())
   elif not went_home and time.monotonic()-origin>min(10,CREATE_WAIT_SECONDS/2):
    # The user demonstrated the same plus entry from the authenticated home feed.
    page.goto(BASE+'/',wait_until='domcontentloaded',timeout=remaining(start,12000));actor(page,job['username']);went_home=True;record(creation_home_fallback_at=c.stamp())
  page.wait_for_timeout(200)
 raise RuntimeError('Instagram创建入口或视频上传窗口未在限时内就绪，未选择视频')

def creation_snapshot(page):
 return page.locator('a,button,[role="button"],[role="link"],svg[aria-label],input[type="file"]').evaluate_all("""(xs)=>xs.filter(e=>{const r=e.getBoundingClientRect();return (r.width>0&&r.height>0)||e.type==='file';}).slice(0,100).map(e=>{const r=e.getBoundingClientRect();return {tag:e.tagName,role:e.getAttribute('role'),label:e.getAttribute('aria-label'),text:(e.innerText||'').slice(0,120),accept:e.type==='file'?e.accept:null,x:Math.round(r.x),y:Math.round(r.y)};})""")

NEXT_NAMES=re.compile(r'^(Continue|继续|繼續|Next|下一步)$',re.I)
SHARE_NAMES=re.compile(r'^(Share|分享|共享)$',re.I)
PHASE_NAMES=re.compile(r'^(Crop|裁剪|Edit|编辑|編輯|New Reels|新\s*Reels|Create new post|创建新帖子)$',re.I)
CAPTION_BOX='[contenteditable="true"][role="textbox"],textarea[aria-label*="caption" i],textarea[aria-label*="配文"],textarea[aria-label*="说明"],textarea[aria-label*="說明"]'
CROP_NAMES=re.compile(r'Select crop|选择.*裁剪|選擇.*裁切',re.I)

def editor_scope(page):
 dialogs=page.get_by_role('dialog')
 for i in range(dialogs.count()-1,-1,-1):
  modal=dialogs.nth(i)
  if modal.is_visible() and (named_control(modal,NEXT_NAMES) is not None or named_control(modal,SHARE_NAMES) is not None or visible(modal.locator(CAPTION_BOX)) is not None):return modal
 titles=page.get_by_text(PHASE_NAMES,exact=True)
 for i in range(titles.count()):
  heading=titles.nth(i)
  if not heading.is_visible():continue
  parent=heading
  for _ in range(7):
   parent=parent.locator('xpath=..')
   if not parent.count() or parent.evaluate('(e)=>e.tagName') in {'BODY','HTML'}:break
   has_media=parent.locator('video,canvas,input[type="file"]').count() or visible(parent.locator(CAPTION_BOX)) is not None
   if has_media and (named_control(parent,NEXT_NAMES) is not None or named_control(parent,SHARE_NAMES) is not None):return parent
 return None

def advance_to_caption(page,start,record=lambda **kw:None):
 deadline=min(time.monotonic()+50,start+c.VIDEO_SECONDS-20);last=None;advances=0
 # The recovered demonstration goes straight through Crop -> Continue. Preserve
 # the imported default; do not open a ratio menu or claim Original was selected.
 record(crop_policy='keep_imported_default_as_recorded',crop_controls_changed=False)
 while time.monotonic()<deadline:
  assert_session(page);scope=editor_scope(page)
  if scope is None:page.wait_for_timeout(150);continue
  caption=visible(scope.locator(CAPTION_BOX))
  if caption is not None:record(caption_editor_ready_at=c.stamp(),edit_advances=advances);return scope,caption
  crop=visible(scope.get_by_role('button',name=CROP_NAMES))
  titles=scope.get_by_text(PHASE_NAMES,exact=True);phase=tuple(titles.nth(i).inner_text() for i in range(titles.count()) if titles.nth(i).is_visible())
  fingerprint=(phase,crop is not None,scope.locator('input[type="file"]').count())
  control=named_control(scope,NEXT_NAMES)
  if control is not None and fingerprint!=last:
   if advances>=5:raise RuntimeError('视频编辑步骤超过预期，未点击分享')
   control.click(timeout=remaining(start,8000));last=fingerprint;advances+=1;record(last_edit_advance_at=c.stamp(),edit_advances=advances)
  page.wait_for_timeout(200)
 raise RuntimeError('视频编辑或添加配文页面未在限时内就绪，未点击分享')

def setting_toggle(scope,names,labels):
 for role in ['switch','checkbox']:
  matches=scope.get_by_role(role,name=names);items=[matches.nth(i) for i in range(matches.count()) if matches.nth(i).is_visible()]
  if len(items)>1:raise RuntimeError('设置开关匹配不唯一，未点击分享')
  if items:return items[0]
 loc=scope.get_by_text(labels,exact=True);seen=False
 for i in range(loc.count()):
  label=loc.nth(i)
  if not label.is_visible():continue
  seen=True;parent=label
  for _ in range(6):
   parent=parent.locator('xpath=..')
   if not parent.count() or parent.evaluate('(e)=>e.tagName') in {'BODY','HTML'}:break
   candidates=parent.locator('input[type="checkbox"],[role="switch"],[role="checkbox"]');controls=[candidates.nth(k) for k in range(candidates.count()) if candidates.nth(k).is_visible()]
   if len(controls)==1:return controls[0]
 if seen:raise RuntimeError('已找到设置文字，但无法唯一核对对应开关，未点击分享')
 return None

def prepare_caption_settings(page,scope,caption,start):
 caption.fill(c.CAPTION,timeout=remaining(start,10000))
 ai_names=re.compile('AI label|AI info|AI.*标签|AI.*標籤|人工智能',re.I)
 ai_labels=re.compile(r'^(添加\s*AI\s*标签|Add AI label|AI label|AI info|添加\s*AI\s*標籤)$',re.I)
 ai=setting_toggle(scope,ai_names,ai_labels);evidence='not_exposed_no_self_label_added'
 if ai is not None:
  if checked(ai):ai.click(timeout=remaining(start,3000))
  if checked(ai):raise RuntimeError('AI标签未关闭，未发布')
  evidence='visible_control_verified_off'
 off_names=re.compile('Turn off commenting|关闭评论|關閉留言',re.I)
 off_labels=re.compile(r'^(Turn off commenting|关闭评论|關閉留言)$',re.I)
 off=setting_toggle(scope,off_names,off_labels);advanced=named_control(scope,re.compile(r'^(Advanced settings|高级设置|進階設定)$',re.I))
 if off is None and advanced is not None and advanced.get_attribute('aria-expanded')!='true':
  advanced.click(timeout=remaining(start,3000));until=min(time.monotonic()+3,start+c.VIDEO_SECONDS-15)
  while time.monotonic()<until:
   off=setting_toggle(scope,off_names,off_labels)
   if off is not None:break
   page.wait_for_timeout(100)
 comments='not_exposed_no_disable_added'
 if off is not None:
  if checked(off):off.click(timeout=remaining(start,3000))
  if checked(off):raise RuntimeError('评论仍被关闭，未发布')
  comments='visible_control_verified_enabled'
 current=caption.input_value() if caption.evaluate('(e)=>e.tagName') in {'TEXTAREA','INPUT'} else caption.inner_text()
 if c.norm(current)!=c.norm(c.CAPTION):raise RuntimeError('原正文未完整填写，未发布')
 ai=setting_toggle(scope,ai_names,ai_labels)
 if ai is not None:
  if checked(ai):ai.click(timeout=remaining(start,3000))
  if checked(ai):raise RuntimeError('设置变化后AI标签未保持关闭，未发布')
  evidence='visible_control_verified_off'
 return evidence,comments

def set_video_file(page,context,target,root,job,start,local_browser=False):
 """Use Chrome's own local path setter only for a verified loopback attachment."""
 if c.MAPPING.get(job['account'])!=job['username']:raise ValueError('视频输入账号不符')
 file=c.safe(root,root/job['video'])
 if file.parent!=root/'videos'/job['account']/'inbox':raise ValueError('只选择本账号原分配inbox视频')
 info=c.file_info(file)
 if info!=dict(size=job['video_size'],sha256=job['video_sha256']):raise ValueError('原视频指纹变化，未选择文件')
 owned=hasattr(target,'element_handle');handle=target.element_handle(timeout=remaining(start,5000)) if owned else target
 if handle is None:raise RuntimeError('原视频输入框已消失，未选择其他文件')
 session=None;marker=uuid.uuid4().hex;old=None;marked=False
 try:
  if handle.evaluate('(e)=>e.tagName!=="INPUT"||e.type!=="file"'):raise ValueError('目标不是视频文件输入框')
  # Capture before the app can clear or detach its input in a change handler.
  handle.evaluate('''(e,key)=>{const state={files:null};state.onChange=event=>{if(event.target===e)state.files=Array.from(e.files||[]).map(f=>({name:f.name,size:f.size}));};e[key]=state;window.addEventListener('change',state.onChange,true);}''',marker)
  if local_browser:
   old=handle.get_attribute('data-ig-local-upload');handle.evaluate('(e,key)=>e.setAttribute("data-ig-local-upload",key)',marker);marked=True
   session=context.new_cdp_session(page);document=session.send('DOM.getDocument',dict(depth=0));node=session.send('DOM.querySelector',dict(nodeId=document['root']['nodeId'],selector='input[data-ig-local-upload="'+marker+'"]'))
   if not node.get('nodeId'):raise RuntimeError('本机Chrome未唯一定位原视频输入框')
   # No byte/base64 transfer: the owned local Chrome opens this verified local file.
   session.send('DOM.setFileInputFiles',dict(nodeId=node['nodeId'],files=[str(file)]));transport='local_chrome_cdp_path'
  else:
   if job['video_size']>50*1024*1024:raise RuntimeError('大视频要求本机Chrome路径选择，未向远程附件接口传输视频')
   handle.set_input_files(str(file),timeout=remaining(start,15000));transport='playwright_file_input'
  selected=handle.evaluate('(e,key)=>e[key]?.files??Array.from(e.files||[]).map(f=>({name:f.name,size:f.size}))',marker)
  if selected!=[dict(name=file.name,size=job['video_size'])]:raise RuntimeError('浏览器选中文件与原分配视频不符，未点击分享')
  return dict(video_file_transport=transport,browser_selected_name=selected[0]['name'],browser_selected_size=selected[0]['size'],browser_file_verified_at=c.stamp())
 finally:
  try:handle.evaluate('(e,key)=>{if(e[key]){window.removeEventListener("change",e[key].onChange,true);delete e[key];}}',marker)
  except Exception:pass
  if marked:
   try:handle.evaluate('(e,old)=>{if(old===null)e.removeAttribute("data-ig-local-upload");else e.setAttribute("data-ig-local-upload",old);}',old)
   except Exception:pass
  if session is not None:
   try:session.detach()
   except Exception:pass
  if owned:
   try:handle.dispose()
   except Exception:pass

def prepare_and_share(page,context,root,job,start,local_browser=False):
 page.goto(BASE+'/'+job['username']+'/',wait_until='domcontentloaded',timeout=25000)
 identity=actor(page,job['username']);base=links(page);upload_at=c.stamp()
 c.update(root,job['key'],identity=identity,identity_verified_at=c.stamp(),upload_started_at=upload_at,baseline_codes=sorted(base),video_status='preparing')
 capture=Capture(page,job,identity,datetime.fromisoformat(upload_at).timestamp(),base);capture.armed=False
 try:
  scope=open_creation(page,job,start,record=lambda **fields:c.update(root,job['key'],**fields))
  inputs=scope.locator('input[type="file"][accept*="video" i]')
  if inputs.count()==0 and scope is not page:inputs=scope.locator('input[type="file"]')
  if inputs.count():file_evidence=set_video_file(page,context,inputs.last,root,job,start,local_browser=local_browser)
  else:
   button=named_control(scope,UPLOAD_NAMES) or visible(scope.get_by_text(UPLOAD_NAMES,exact=True))
   if button is None:raise RuntimeError('创建新帖子窗口缺少从电脑中选择按钮，未选择视频')
   with page.expect_file_chooser(timeout=remaining(start,10000)) as event:button.click(timeout=remaining(start,5000))
   file_evidence=set_video_file(page,context,event.value.element,root,job,start,local_browser=local_browser)
  c.update(root,job['key'],selected_file=job['video'],selected_video_sha256=job['video_sha256'],**file_evidence)
  scope,caption=advance_to_caption(page,start,record=lambda **fields:c.update(root,job['key'],**fields))
  ai_evidence,comment_evidence=prepare_caption_settings(page,scope,caption,start)
  actor(page,job['username'])
  c.update(root,job['key'],ai_label_requested=False,ai_control_evidence=ai_evidence,comment_control_evidence=comment_evidence,post_intent_at=c.stamp(),failure_stage='click_share',video_status='posting')
  capture.armed=True
  click_named(scope,SHARE_NAMES,timeout=remaining(start,12000))
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
