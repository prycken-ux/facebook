"""IG-only coordinator: allocate once, trial gate, contained 180s operations."""
import contextlib,hashlib,json,os,re,shutil,socket,subprocess,sys,time,urllib.request,uuid,zipfile
from pathlib import Path
import ig10_common_20261127 as c
import ig10_allocate_20261127 as allocation
from ig_windows_job import WindowsJobChild
LOG='logs/ig-2026-11-27-run.log';STATUS='logs/ig-2026-11-27-status.json'

class Tee:
 def __init__(self,*streams):self.streams=streams
 def write(self,text):
  for s in self.streams:s.write(text);s.flush()
  return len(text)
 def flush(self):
  for s in self.streams:s.flush()

def chrome():
 for key in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
  if os.environ.get(key):
   p=Path(os.environ[key])/'Google/Chrome/Application/chrome.exe'
   if p.is_file():return p
 found=shutil.which('chrome.exe')
 if found:return Path(found)
 raise RuntimeError('没有找到已登录资料使用的Google Chrome')

def browser_args(root,job,port):
 profile=c.safe(root,root/'profiles'/job['account'])
 return [str(chrome()),'--user-data-dir='+str(profile),'--profile-directory=Default','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(port),'--headless=new','--window-size=1440,1000','--mute-audio','--no-first-run','--no-default-browser-check','--hide-crash-restore-bubble','--disable-session-crashed-bubble','about:blank']

def launch(pw,root,job,started):
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 endpoint='http://127.0.0.1:'+str(port);args=browser_args(root,job,port)
 proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000 if os.name=='nt' else 0)
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));until=time.monotonic()+30
 while time.monotonic()<until:
  try:
   with opener.open(endpoint+'/json/version',timeout=1) as r:version=json.load(r)
   if str(version.get('webSocketDebuggerUrl','')).startswith('ws://127.0.0.1:'):break
  except (OSError,ValueError):pass
  if proc.poll() not in {None,0}:raise RuntimeError('IG Chrome启动失败')
  time.sleep(.2)
 else:raise RuntimeError('IG Chrome调试入口30秒内未就绪，未选择视频')
 browser=pw.chromium.connect_over_cdp(endpoint,timeout=15000)
 if not browser.contexts:browser.close();raise RuntimeError('IG原资料浏览器上下文缺失')
 context=browser.contexts[0];page=next((p for p in reversed(context.pages) if 'instagram.com' in p.url),None) or (context.pages[0] if context.pages else context.new_page());page.set_default_timeout(10000)
 return browser,context,page

def diagnostic(root,job,kind,error,page=None):
 folder=c.safe(root,root/'logs/diagnostics'/(job['account']+'-'+kind+'-'+uuid.uuid4().hex[:8]));folder.mkdir(parents=True)
 value=dict(account=job['account'],username=job['username'],key=job['key'],kind=kind,error=str(error),at=c.stamp())
 row=c.state(root).get(job['key'],{})
 if page is not None and row.get('identity_verified_at') and row['identity_verified_at']>=row.get('video_attempt_started_at',''):
  try:
   import ig10_browser_20261127 as ui
   value.update(page_url=page.url.split('?')[0],visible_text=page.locator('body').inner_text(timeout=3000)[:6000],creation_controls=ui.creation_snapshot(page));page.screenshot(path=str(folder/'page.png'),timeout=5000)
  except Exception:pass
 c.save(folder/'diagnostic.json',value)
 return str(folder.relative_to(root))

def worker(root,batch_path,key,kind,started):
 import ig10_browser_20261127 as ui
 from playwright.sync_api import sync_playwright
 batch=allocation.validate(root,batch_path);job=next((j for j in batch['payload']['jobs'] if j['key']==key),None)
 if not job or kind not in {'video','comment'}:raise ValueError('IG操作不属于当前冻结清单')
 row=c.state(root).get(key,{})
 if kind=='video' and c.submission(row):print('已有IG视频提交记录，未重复上传：'+job['account'],flush=True);return 0
 info=c.file_info(c.safe(root,root/job['video'])) if kind=='video' else None
 if kind=='video' and info!=dict(size=job['video_size'],sha256=job['video_sha256']):raise ValueError('本次IG视频指纹变化，未选择其他素材')
 if kind=='video':c.update(root,key,error='',browser_mode='headless',video_attempt_started_at=c.stamp())
 browser=None;page=None
 try:
  with sync_playwright() as pw:
   try:
    browser,context,page=launch(pw,root,job,started)
    if kind=='video':ui.prepare_and_share(page,context,root,job,started,local_browser=True)
    else:ui.comment(page,context,root,job,started)
    return 0
   except Exception as error:
    row=c.state(root).get(key,{})
    if kind=='video':
     assumed=isinstance(error,ui.ReceiptPending) and bool(row.get('submit_click_returned_at')) and row.get('failure_stage')=='wait_receipt'
     c.update(root,key,video_status='needs_review' if c.submission(row) else 'failed_before_post',assumed_published=assumed,publication_confirmation_source='user_requested_FB_rules_post_click_timeout' if assumed else row.get('publication_confirmation_source',''),error=str(error),diagnostic=diagnostic(root,job,kind,error,page))
    else:c.update(root,key,comment_status='needs_review' if row.get('comment_send_intent_at') else 'failed_before_send',comment_error=str(error),diagnostic=diagnostic(root,job,kind,error,page))
    print('IG操作保留结果：'+job['account']+' '+kind+' '+str(error),flush=True);return 3
   finally:
    if browser is not None:
     try:browser.close()
     except Exception:pass
 except Exception as error:
  row=c.state(root).get(key,{})
  c.update(root,key,**({'video_status':'needs_review' if c.submission(row) else 'failed_before_post','error':str(error)} if kind=='video' else {'comment_status':'needs_review' if row.get('comment_send_intent_at') else 'failed_before_send','comment_error':str(error)}));return 3

def release_profile(root,job,run,started,status):
 packet=root/'logs'/('ig-release-'+uuid.uuid4().hex+'.json')
 c.save(packet,dict(root=str(root),accounts=[job['account']],caller_pid=os.getpid(),authorization='ig10-publication-normal-close-20261127'))
 log=root/'logs'/('ig-release-'+uuid.uuid4().hex+'.log')
 with log.open('ab') as out:
  p=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('ig10_profile_release.ps1')),'-Packet',str(packet)],stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,creationflags=0x08000000)
  last=time.monotonic()
  while p.poll() is None:
   if time.monotonic()-started>35:p.kill();p.wait();raise RuntimeError('IG窗口释放超过35秒，尚未选择或提交视频；诊断：'+str(log))
   if time.monotonic()-last>=5:status('running','正在释放'+job['account']+'资料占用',account=job['account'],kind='profile_check');last=time.monotonic()
   time.sleep(.2)
 if p.returncode:raise RuntimeError('IG资料未释放，未上传：'+log.read_text(encoding='utf-8-sig',errors='replace')[-1800:])

def run_operation(root,path,job,kind,run,status,child_factory=WindowsJobChild):
 started=time.monotonic();limit=c.VIDEO_SECONDS if kind=='video' else c.COMMENT_SECONDS;status('running',job['account']+' '+kind+' 开始，独立上限'+str(limit)+'秒',account=job['account'],kind=kind,elapsed_seconds=0)
 try:release_profile(root,job,run,started,status)
 except Exception as error:
  row=c.state(root).get(job['key'],{})
  c.update(root,job['key'],**({'video_status':'needs_review' if c.submission(row) else 'failed_before_post','error':str(error)} if kind=='video' else {'comment_status':'needs_review' if row.get('comment_send_intent_at') else 'failed_before_send','comment_error':str(error)}));return 3
 output=root/'logs'/('ig-worker-'+job['account']+'-'+kind+'-'+uuid.uuid4().hex[:8]+'.log')
 env=dict(os.environ,IG10_ROLE=kind,IG10_BATCH=str(path),IG10_KEY=job['key'],IG10_STARTED=str(started),PYTHONIOENCODING='utf-8')
 with output.open('ab') as stream:
  try:child=child_factory([sys.executable,'-u',str(Path(__file__).resolve()),str(root)],env,root,stream)
  except Exception as error:
   row=c.state(root).get(job['key'],{})
   c.update(root,job['key'],**({'video_status':'needs_review' if c.submission(row) else 'failed_before_post','error':'IG工作进程未能建立：'+str(error)} if kind=='video' else {'comment_status':'needs_review' if row.get('comment_send_intent_at') else 'failed_before_send','comment_error':'IG工作进程未能建立：'+str(error)}));return 3
  last=time.monotonic()
  try:
   while child.poll() is None:
    now=time.monotonic()
    if now-started>=limit:
     child.stop();row=c.state(root).get(job['key'],{})
     if kind=='video' and row.get('video_status')!='published':c.update(root,job['key'],video_status='needs_review' if c.submission(row) else 'failed_before_post',error='本视频操作已达180秒，保留原提交记录，不重复上传')
     if kind=='comment' and row.get('comment_verification')!='own_comment_seen_after_reload':c.update(root,job['key'],comment_status='needs_review' if row.get('comment_send_intent_at') else 'failed_before_send',comment_error='本评论操作已达180秒，保留可能发送记录')
     return 3
    if now-last>=15:status('running',job['account']+' '+kind+' 已用'+str(int(now-started))+'秒',account=job['account'],kind=kind,elapsed_seconds=int(now-started));last=now
    time.sleep(.25)
   code=child.poll()
   if code not in {0,3}:
    row=c.state(root).get(job['key'],{});c.update(root,job['key'],**({'video_status':'needs_review' if c.submission(row) else 'failed_before_post','error':'IG工作进程退出：'+str(code)+'，诊断：'+str(output)} if kind=='video' else {'comment_status':'needs_review' if row.get('comment_send_intent_at') else 'failed_before_send','comment_error':'IG工作进程退出：'+str(code)}))
   return code
  finally:child.close()

def verified(root,job):
 row=c.state(root).get(job['key'],{});key=c.digest(dict(video_job=job['key'],text=c.COMMENT));item=c.read(root/'logs/ig-comment-state.json',{}).get(key,{})
 return (row.get('video_status')=='published' and not row.get('assumed_published') and bool(c.canonical(row.get('permalink',''))) and item.get('video_job')==job['key'] and item.get('username')==job['username'] and item.get('text_sha256')==c.digest(c.COMMENT) and item.get('verification')=='own_comment_seen_after_reload' and item.get('verified_at') and c.shortcode(item.get('permalink',''))==c.shortcode(row['permalink']))

def report(root,batch,phase,reason=''):
 ledger=c.state(root);rows=[]
 for j in batch['payload']['jobs']:
  r=ledger.get(j['key'],{});rows.append(dict(account=j['account'],username=j['username'],source_name=j['source_name'],video_status=r.get('video_status','not_started'),assumed_published=r.get('assumed_published',False),permalink=r.get('permalink'),comment_status=r.get('comment_status','not_started'),comment_verified=bool(verified(root,j)),error=r.get('comment_error') or r.get('error','')))
 value=dict(batch_sha256=batch['sha256'],material_date=c.DAY,phase=phase,reason=reason,confirmed_videos=sum(r['video_status']=='published' and not r['assumed_published'] for r in rows),assumed_videos=sum(bool(r['assumed_published']) for r in rows),verified_comments=sum(r['comment_verified'] for r in rows),rows=rows,updated_at=c.stamp())
 c.save(root/'logs/ig-2026-11-27-results.json',value)
 text=['IG本批：确认视频 '+str(value['confirmed_videos'])+'；规则视成功 '+str(value['assumed_videos'])+'；评论刷新核验 '+str(value['verified_comments'])+'；'+reason]
 text += [r['account']+'/'+r['username']+' 视频='+r['video_status']+' 评论='+r['comment_status']+' '+r['error'] for r in rows]
 (root/'logs/ig-2026-11-27-results.txt').write_text('\n'.join(text),encoding='utf-8-sig');print(text[0],flush=True);return value

def export(root,batch):
 desktop=c.desktop_path(root)
 output=desktop/('IG-publish-check-'+c.DAY.replace('-','')+'-'+uuid.uuid4().hex[:8]+'.zip')
 with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
  for name in ['ig-2026-11-27-results.json','ig-2026-11-27-results.txt','ig-2026-11-27-status.json','ig-publication-state.json','ig-comment-state.json','ig-first-trial-20261127.json']:
   p=root/'logs'/name
   if p.is_file():archive.write(p,p.name)
  for p in (root/'logs').glob('ig-*.log'):
   if p.is_file() and not p.is_symlink():archive.writestr(p.name,p.read_bytes()[-1_000_000:])
  for p in (root/'logs/diagnostics').rglob('*') if (root/'logs/diagnostics').is_dir() else []:
   if p.is_file() and not p.is_symlink():archive.write(p,str(p.relative_to(root/'logs')))
  for p in (root/'logs/repairs').glob('ig-*.json'):
   if p.is_file() and not p.is_symlink():archive.write(p,str(p.relative_to(root/'logs')))
 print('IG结果/页面诊断包：'+str(output),flush=True);return output

def recover_navigation_syntax_gate(root,batch,gate):
 """One audited retry only for the proven, pre-identity navigation syntax bug."""
 if not gate.get('blocked') or gate.get('navigation_syntax_repair'):return gate
 first=batch['payload']['jobs'][0];row=c.state(root).get(first['key'],{})
 if gate.get('batch_sha256')!=batch['sha256'] or gate.get('job_key')!=first['key']:return gate
 if (row.get('batch_sha256')!=batch['sha256'] or row.get('account')!=first['account'] or row.get('username')!=first['username'] or row.get('video_sha256')!=first['video_sha256']):return gate
 if row.get('video_status')!='failed_before_post' or c.submission(row):return gate
 if any(row.get(k) for k in ['identity_verified_at','upload_started_at','selected_file','comment_send_intent_at','comment_verified_at','media_proof']):return gate
 if "Page.evaluate: SyntaxError: Unexpected token '}'" not in row.get('error',''):return gate
 comments=c.read(root/'logs/ig-comment-state.json',{})
 if any(v.get('video_job')==first['key'] for v in comments.values()):return gate
 if not isinstance(row.get('diagnostic'),str):return gate
 folder=c.safe(root,root/row['diagnostic'])
 if not folder.is_relative_to(root/'logs/diagnostics'):return gate
 evidence=c.read(folder/'diagnostic.json',required=True)
 if any(evidence.get(k)!=v for k,v in dict(account=first['account'],username=first['username'],key=first['key'],kind='video',error=row['error']).items()):return gate
 audit=root/'logs/repairs'/('ig-nav-syntax-'+uuid.uuid4().hex+'.json')
 payload=dict(schema='ig-pre-post-navigation-syntax-repair-v1',batch_sha256=batch['sha256'],first_job=first['key'],gate_before=gate,row_before=row,diagnostic=evidence,at=c.stamp())
 c.save(audit,dict(payload=payload,sha256=c.digest(payload)))
 updated=dict(gate,blocked=False,passed=False,navigation_syntax_repair=str(audit.relative_to(root)),repair_at=c.stamp())
 c.save(root/'logs/ig-first-trial-20261127.json',updated)
 print('已核对首条在提交前因导航脚本语法错误停止；原记录已备份，使用修复脚本重新验证首条。',flush=True)
 return updated

def recover_create_entry_gate(root,batch,gate):
 """Only the diagnosed, authenticated empty-profile failure before file choice."""
 if not gate.get('blocked') or gate.get('create_entry_repair'):return gate
 first=batch['payload']['jobs'][0];row=c.state(root).get(first['key'],{})
 if gate.get('batch_sha256')!=batch['sha256'] or gate.get('job_key')!=first['key']:return gate
 if any(row.get(k)!=v for k,v in dict(batch_sha256=batch['sha256'],account=first['account'],username=first['username'],video_sha256=first['video_sha256']).items()):return gate
 if row.get('video_status')!='failed_before_post' or row.get('error')!='未找到Instagram创建入口，未选择视频' or c.submission(row):return gate
 if any(row.get(k) for k in ['selected_file','selected_video_sha256','creation_entry_clicked_at','creation_dialog_verified_at','comment_send_intent_at','comment_verified_at','media_proof']):return gate
 if not row.get('identity_verified_at') or row.get('identity',{}).get('username')!=first['username']:return gate
 comments=c.read(root/'logs/ig-comment-state.json',{})
 if any(v.get('video_job')==first['key'] for v in comments.values()):return gate
 if not isinstance(row.get('diagnostic'),str):return gate
 folder=c.safe(root,root/row['diagnostic'])
 if not folder.is_relative_to(root/'logs/diagnostics'):return gate
 evidence=c.read(folder/'diagnostic.json',required=True)
 if any(evidence.get(k)!=v for k,v in dict(account=first['account'],username=first['username'],key=first['key'],kind='video',error=row['error']).items()):return gate
 if evidence.get('page_url')!='https://www.instagram.com/'+first['username']+'/':return gate
 text=evidence.get('visible_text','')
 if first['username'] not in text or not any(x in text for x in ['分享你的首张照片','Share your first photo','分享你的首張相片']):return gate
 audit=root/'logs/repairs'/('ig-create-entry-'+uuid.uuid4().hex+'.json')
 payload=dict(schema='ig-pre-file-create-entry-repair-v1',batch_sha256=batch['sha256'],first_job=first['key'],gate_before=gate,row_before=row,diagnostic=evidence,at=c.stamp())
 c.save(audit,dict(payload=payload,sha256=c.digest(payload)))
 updated=dict(gate,blocked=False,passed=False,create_entry_repair=str(audit.relative_to(root)),repair_at=c.stamp())
 c.save(root/'logs/ig-first-trial-20261127.json',updated)
 print('已核对首条仅在创建入口识别前停止、未选文件或提交；保留原记录，按新入口重新验证。',flush=True)
 return updated

def recover_recorded_editor_gate(root,batch,gate):
 """One retry for the recorded Continue-vs-Next mismatch before Share."""
 if not gate.get('blocked') or gate.get('recorded_editor_repair'):return gate
 first=batch['payload']['jobs'][0];row=c.state(root).get(first['key'],{})
 if gate.get('batch_sha256')!=batch['sha256'] or gate.get('job_key')!=first['key']:return gate
 if any(row.get(k)!=v for k,v in dict(batch_sha256=batch['sha256'],account=first['account'],username=first['username'],video_sha256=first['video_sha256'],selected_file=first['video'],selected_video_sha256=first['video_sha256']).items()):return gate
 if row.get('video_status')!='failed_before_post' or row.get('error')!='网页按钮尚未找到：^(Next|下一步)$' or c.submission(row):return gate
 if any(row.get(k) for k in ['comment_send_intent_at','comment_verified_at','media_proof']):return gate
 if not row.get('identity_verified_at') or row.get('identity',{}).get('username')!=first['username']:return gate
 if any(v.get('video_job')==first['key'] for v in c.read(root/'logs/ig-comment-state.json',{}).values()):return gate
 if not isinstance(row.get('diagnostic'),str):return gate
 folder=c.safe(root,root/row['diagnostic'])
 if not folder.is_relative_to(root/'logs/diagnostics'):return gate
 evidence=c.read(folder/'diagnostic.json',required=True)
 if any(evidence.get(k)!=v for k,v in dict(account=first['account'],username=first['username'],key=first['key'],kind='video',error=row['error']).items()):return gate
 text=evidence.get('visible_text','')
 if evidence.get('page_url') not in {'https://www.instagram.com/','https://www.instagram.com/'+first['username']+'/'} or '继续' not in text or not any(x in text for x in ['裁剪','编辑']):return gate
 audit=root/'logs/repairs'/('ig-recorded-editor-'+uuid.uuid4().hex+'.json');payload=dict(schema='ig-recorded-editor-pre-share-repair-v1',batch_sha256=batch['sha256'],first_job=first['key'],gate_before=gate,row_before=row,diagnostic=evidence,at=c.stamp());c.save(audit,dict(payload=payload,sha256=c.digest(payload)))
 updated=dict(gate,blocked=False,passed=False,recorded_editor_repair=str(audit.relative_to(root)),repair_at=c.stamp());c.save(root/'logs/ig-first-trial-20261127.json',updated)
 print('已核对仅在继续按钮识别前停止、未提交；保留原记录，按实际录制流程重新验证首条。',flush=True);return updated

def recover_local_file_gate(root,batch,gate):
 """One audited retry for Playwright's known pre-transfer 50 MiB attachment guard."""
 if not gate.get('blocked') or gate.get('local_file_repair'):return gate
 first=batch['payload']['jobs'][0];row=c.state(root).get(first['key'],{})
 if gate.get('batch_sha256')!=batch['sha256'] or gate.get('job_key')!=first['key']:return gate
 if any(row.get(k)!=v for k,v in dict(batch_sha256=batch['sha256'],account=first['account'],username=first['username'],video_sha256=first['video_sha256']).items()):return gate
 if row.get('video_status')!='failed_before_post' or c.submission(row) or first.get('video_size',0)<=50*1024*1024:return gate
 if not row.get('creation_dialog_verified_at') or not row.get('identity_verified_at') or row.get('identity',{}).get('username')!=first['username']:return gate
 error=row.get('error','')
 if 'Cannot transfer files larger than 50Mb to a browser not co-located with the server' not in error or not re.match(r'^(Locator|ElementHandle)\.set_input_files:|^FileChooser\.set_files:',error):return gate
 if any(row.get(k) for k in ['selected_file','selected_video_sha256','browser_file_verified_at','media_proof','comment_send_intent_at','comment_verified_at']):return gate
 if any(v.get('video_job')==first['key'] for v in c.read(root/'logs/ig-comment-state.json',{}).values()):return gate
 if not isinstance(row.get('diagnostic'),str):return gate
 folder=c.safe(root,root/row['diagnostic'])
 if not folder.is_relative_to(root/'logs/diagnostics'):return gate
 evidence=c.read(folder/'diagnostic.json',required=True)
 if any(evidence.get(k)!=v for k,v in dict(account=first['account'],username=first['username'],key=first['key'],kind='video',error=error).items()):return gate
 text=evidence.get('visible_text','')
 if evidence.get('page_url') not in {'https://www.instagram.com/','https://www.instagram.com/'+first['username']+'/'} or '创建新帖子' not in text or '从电脑中选择' not in text:return gate
 audit=root/'logs/repairs'/('ig-local-file-'+uuid.uuid4().hex+'.json');payload=dict(schema='ig-local-file-pre-transfer-repair-v1',batch_sha256=batch['sha256'],first_job=first['key'],video_size=first['video_size'],gate_before=gate,row_before=row,diagnostic=evidence,at=c.stamp());c.save(audit,dict(payload=payload,sha256=c.digest(payload)))
 updated=dict(gate,blocked=False,passed=False,local_file_repair=str(audit.relative_to(root)),repair_at=c.stamp());c.save(root/'logs/ig-first-trial-20261127.json',updated)
 print('已核对大文件在附件传输前被50 MiB限制拒绝、未提交；保留原记录，改用本机Chrome路径重新验证首条。',flush=True);return updated

def coordinator(root,path,run,operation=run_operation):
 root=c.workspace(root);batch=allocation.validate(root,path)
 with c.lock(root,'publisher'):
  c.state(root)
  def status(phase,message,**more):
   value=dict(phase=phase,message=message,run_id=run,batch_sha256=batch['sha256'],material_date=c.DAY,browser_mode='headless',pid=os.getpid(),updated_at=c.stamp(),**more);c.save(root/STATUS,value);print(message,flush=True)
  status('preparing','IG监控已建立，先试发ins01并核验首评')
  c.save(root/'logs'/('ig-launch-'+run+'.json'),dict(phase='started',pid=os.getpid(),run_id=run))
  first=batch['payload']['jobs'][0];gate_path=root/'logs/ig-first-trial-20261127.json';gate=c.read(gate_path,{})
  if gate and gate.get('batch_sha256')!=batch['sha256']:raise ValueError('原IG首条门禁清单不符')
  gate=recover_navigation_syntax_gate(root,batch,gate)
  gate=recover_create_entry_gate(root,batch,gate)
  gate=recover_recorded_editor_gate(root,batch,gate)
  gate=recover_local_file_gate(root,batch,gate)
  if gate.get('blocked'):
   reason='首条IG试发已保留待核实；未清除门禁或重发，请提供上次诊断包';report(root,batch,'review_required',reason);status('review_required',reason);export(root,batch);return 3
  for j in batch['payload']['jobs']:
   row=c.state(root).get(j['key'],{})
   c.update(root,j['key'],account=j['account'],username=j['username'],video_sha256=j['video_sha256'],batch_sha256=batch['sha256'])
   if not c.submission(row):
    operation(root,path,j,'video',run,status)
    row=c.state(root).get(j['key'],{})
    if row.get('video_status')=='failed_before_post' and not row.get('video_retry_used') and re.search('net::ERR_|Timeout|browser.*closed',row.get('error',''),re.I):
     c.update(root,j['key'],video_retry_used=True,video_retry_claimed_at=c.stamp());operation(root,path,j,'video',run,status)
   row=c.state(root).get(j['key'],{})
   if c.submission(row) and not verified(root,j):operation(root,path,j,'comment',run,status)
   if verified(root,j):
    src=c.safe(root,root/j['video']);dest=c.safe(root,root/j['published_video'])
    if src.exists() and c.file_info(src)==dict(size=j['video_size'],sha256=j['video_sha256']) and not dest.exists():dest.parent.mkdir(parents=True,exist_ok=True);src.replace(dest)
   if j['key']==first['key']:
    ok=bool(verified(root,j));c.save(gate_path,dict(batch_sha256=batch['sha256'],job_key=j['key'],passed=ok,blocked=not ok,checked_at=c.stamp(),**{k:gate[k] for k in ['navigation_syntax_repair','create_entry_repair','recorded_editor_repair','local_file_repair'] if gate.get(k)}))
    if not ok:
     reason='首条IG视频/评论未完整通过，保留其余9个账号，不重复点击发布';report(root,batch,'review_required',reason);status('review_required',reason);export(root,batch);return 3
    print('ins01视频及首评刷新核验通过；继续其余9个IG账号。',flush=True)
   report(root,batch,'running')
  result=report(root,batch,'finished');phase='finished' if result['verified_comments']==10 else 'review_required';status(phase,'IG本轮结束；视频和评论结果分别见报告');export(root,batch);return 0 if phase=='finished' else 3

def main(root):
 root=Path(root).resolve();role=os.environ.get('IG10_ROLE','coordinator');run=os.environ.get('IG10_RUN','')
 with (root/LOG).open('a',encoding='utf-8') as out,contextlib.redirect_stdout(Tee(sys.stdout,out)),contextlib.redirect_stderr(Tee(sys.stderr,out)):
  if role in {'video','comment'}:return worker(root,Path(os.environ['IG10_BATCH']),os.environ['IG10_KEY'],role,float(os.environ['IG10_STARTED']))
  try:return coordinator(root,Path(os.environ['IG10_BATCH']),run)
  except Exception as error:
   busy='已有IG任务' in str(error)
   c.save(root/'logs'/('ig-launch-'+run+'.json'),dict(phase='already_running' if busy else 'failed',message=str(error),run_id=run))
   if not busy:c.save(root/STATUS,dict(phase='failed',message=str(error),run_id=run,material_date=c.DAY,pid=os.getpid(),updated_at=c.stamp()))
   print('STOP：'+str(error),flush=True);return 1

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
 raise SystemExit(main(Path(sys.argv[1])))
