"""One additional attempt, preserving the diagnosed submitted attempt unchanged."""
from pathlib import Path
import ig10_common_20261127 as c

PLAN='logs/ig-confirmed-absence-retry-20261127.json'
AUTH='user-confirmed-ins01-profile-and-reels-absent-after-f5308ad8-20261127-v1'
SOURCE_BATCH='e77ae5b5c9b0fc69719d5420c532f5d053e8638b1da4d4e24a2fda451af22346'
SOURCE_JOB='d4b9fdfcf975eaed576e8bb408e6dfcafba3cd88b834f16c5e1658eae2475f20'
SOURCE_VIDEO='17147588b83a6367670c8d9e55b773dca288e2dbf322d943dedf314e311d1ba1'
SOURCE_ROW_SHA='84206041e3369ea0dda1b590fab0ff7afab6837c2236d58a185f080f4d423cf1'
FALLBACK='logs/ig-trial-fallback-ins02-20261127.json'
FALLBACK_AUTH='user-skip-failed-ins01-try-ins02-after-045d4f2b-20261127-v1'
FAILED_RETRY_SHA='7b010d9b1bd705a18f5e53fc1a7cabed12d4f5e86105b968f370d810ee52422e'

def plan(root,batch,gate=None,create=False):
 first=batch['payload']['jobs'][0];path=c.safe(root,root/PLAN)
 matches=batch['sha256']==SOURCE_BATCH and first['key']==SOURCE_JOB and first['account']=='ins01' and first['username']=='ted47868' and first['video_sha256']==SOURCE_VIDEO
 if path.exists():
  value=c.checked(path);p=value['payload'];expected=c.digest(dict(authorization=AUTH,batch_sha256=batch['sha256'],original_job=first['key']))
  if not matches or p.get('authorization')!=AUTH or p.get('batch_sha256')!=batch['sha256'] or p.get('original_job')!=first['key'] or p.get('retry_key')!=expected or p.get('original_row_sha256')!=SOURCE_ROW_SHA or c.digest(p.get('original_row',{}))!=SOURCE_ROW_SHA:raise ValueError('IG单次补发许可与原批次/原提交不符，保留待核实')
  if c.digest(c.state(root).get(first['key'],{}))!=SOURCE_ROW_SHA:raise ValueError('原提交记录已变化，未使用旧的未发布确认重传')
  return value
 if not create or not matches or not gate or not gate.get('blocked') or gate.get('job_key')!=first['key'] or gate.get('batch_sha256')!=batch['sha256']:return None
 row=c.state(root).get(first['key'],{})
 if c.digest(row)!=SOURCE_ROW_SHA:return None
 if row.get('video_status')!='needs_review' or not row.get('submit_click_returned_at') or row.get('permalink') or row.get('media_proof') or row.get('comment_send_intent_at'):return None
 if any(v.get('video_job')==first['key'] for v in c.read(root/'logs/ig-comment-state.json',{}).values()):return None
 folder=c.safe(root,root/str(row['diagnostic']).replace('\\','/'));comment=c.read(folder/'diagnostic.json',required=True)
 video=c.read(c.safe(root,root/'logs/diagnostics/ins01-video-5567c3ab/diagnostic.json'),required=True)
 for item,kind in [(video,'video'),(comment,'comment')]:
  if any(item.get(k)!=v for k,v in dict(account=first['account'],username=first['username'],key=first['key'],kind=kind).items()):return None
  if item.get('page_url')!='https://www.instagram.com/'+first['username']+'/':return None
 if '正在分享' not in video.get('visible_text','') or '0帖子' not in comment.get('visible_text','') or video.get('error')!=row.get('error') or comment.get('error')!=row.get('comment_error'):return None
 payload=dict(schema='ig-confirmed-absence-single-additional-attempt-v1',authorization=AUTH,user_confirmation='主页和Reels都没有',source_archive='IG-publish-check-20261127-f5308ad8.zip',batch_sha256=batch['sha256'],original_job=first['key'],retry_key=c.digest(dict(authorization=AUTH,batch_sha256=batch['sha256'],original_job=first['key'])),original_row_sha256=SOURCE_ROW_SHA,original_row=row,original_gate=gate,video_diagnostic=video,comment_diagnostic=comment,created_at=c.stamp())
 value=dict(payload=payload,sha256=c.digest(payload));c.save(path,value)
 print('已保存用户确认主页和Reels均无视频的一次补发许可；原提交记录保留，重试前仍核对主页为空。',flush=True)
 return value

def job(root,batch,original):
 value=plan(root,batch)
 if value and original['key']==value['payload']['original_job']:
  return dict(original,key=value['payload']['retry_key'],retry_of=original['key'],retry_authorization=value['sha256'])
 return original

def fallback(root,batch,gate=None,create=False):
 """User explicitly allows ins02 to become the trial after this failed ins01."""
 path=c.safe(root,root/FALLBACK)
 if not path.exists() and not create:return None
 permit=plan(root,batch)
 if not permit:return None
 p=permit['payload'];source=c.state(root).get(p['retry_key'],{});jobs=batch['payload']['jobs']
 if len(jobs)<2 or jobs[1]['account']!='ins02' or jobs[1]['username']!=c.MAPPING['ins02']:return None
 if path.exists():
  value=c.checked(path);f=value['payload']
  if f.get('authorization')!=FALLBACK_AUTH or f.get('batch_sha256')!=batch['sha256'] or f.get('source_retry')!=p['retry_key'] or f.get('target_job')!=jobs[1]['key'] or f.get('source_row_sha256')!=FAILED_RETRY_SHA or c.digest(f.get('source_row',{}))!=FAILED_RETRY_SHA or c.digest(source)!=FAILED_RETRY_SHA:raise ValueError('ins02试发切换记录与原诊断不符，未更改账号范围')
  return value
 if not gate or not gate.get('blocked') or gate.get('job_key')!=p['original_job'] or gate.get('effective_job_key')!=p['retry_key'] or gate.get('absence_retry_authorization')!=permit['sha256']:return None
 error='无法唯一核对当前登录账号，未用个人主页网址代替登录证据'
 if c.digest(source)!=FAILED_RETRY_SHA or source.get('video_status')!='failed_before_post' or source.get('error')!=error:return None
 if source.get('retry_of')!=p['original_job'] or source.get('retry_authorization')!=permit['sha256']:return None
 if c.submission(source) or any(source.get(k) for k in ['selected_file','selected_video_sha256','upload_started_at','browser_file_verified_at','identity_verified_at','media_proof','comment_send_intent_at','comment_verified_at']):return None
 if any(v.get('video_job')==p['retry_key'] for v in c.read(root/'logs/ig-comment-state.json',{}).values()):return None
 folder=c.safe(root,root/str(source['diagnostic']).replace('\\','/'));e=c.read(folder/'diagnostic.json',required=True)
 if any(e.get(k)!=v for k,v in dict(account='ins01',username=c.MAPPING['ins01'],key=p['retry_key'],kind='video',error=error).items()):return None
 target=c.state(root).get(jobs[1]['key'],{})
 if target and (c.submission(target) or target.get('video_status') not in {None,'not_started'}):return None
 payload=dict(schema='ig-user-authorized-ins02-trial-fallback-v1',authorization=FALLBACK_AUTH,user_instruction='如果这个还是不行的话跳过in01尝试下一个',batch_sha256=batch['sha256'],skipped_account='ins01',source_retry=p['retry_key'],source_row_sha256=FAILED_RETRY_SHA,source_row=source,source_gate=gate,diagnostic=e,target_account='ins02',target_job=jobs[1]['key'],created_at=c.stamp())
 value=dict(payload=payload,sha256=c.digest(payload));c.save(path,value)
 print('按用户要求保留并跳过ins01；改由ins02核验视频和首评，通过后再继续其余8个账号。',flush=True)
 return value
