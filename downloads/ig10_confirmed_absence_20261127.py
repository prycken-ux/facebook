"""One additional attempt, preserving the diagnosed submitted attempt unchanged."""
from pathlib import Path
import ig10_common_20261127 as c

PLAN='logs/ig-confirmed-absence-retry-20261127.json'
AUTH='user-confirmed-ins01-profile-and-reels-absent-after-f5308ad8-20261127-v1'
SOURCE_BATCH='e77ae5b5c9b0fc69719d5420c532f5d053e8638b1da4d4e24a2fda451af22346'
SOURCE_JOB='d4b9fdfcf975eaed576e8bb408e6dfcafba3cd88b834f16c5e1658eae2475f20'
SOURCE_VIDEO='17147588b83a6367670c8d9e55b773dca288e2dbf322d943dedf314e311d1ba1'
SOURCE_ROW_SHA='84206041e3369ea0dda1b590fab0ff7afab6837c2236d58a185f080f4d423cf1'

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
