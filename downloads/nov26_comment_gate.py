"""Require a real reload-verified first comment before repeating across the batch."""
import json,os,uuid,zipfile
from datetime import datetime,timezone
from pathlib import Path
import publication_file_state_20261124 as files

def verified(first,root,key,text):
 c=first.priority.daily.comments;ledger_key=c.hashlib.sha256((key+'\0'+c.text_hash(text)).encode()).hexdigest()
 item=first.upload.read_json(root/'logs/video_comments.json',{}).get(ledger_key,{})
 record=first.upload.read_json(root/'logs/publish_state.json',{}).get(key,{})
 return (record.get('comment_status') in {'sent','already_present'} and (item.get('account'),item.get('target'))==(record.get('account'),record.get('target')) and item.get('video_job')==key and item.get('text_sha256')==c.text_hash(text) and item.get('status') in {'sent','already_present'} and item.get('verification')=='own_comment_seen_after_reload' and bool(item.get('verified_at')) and bool(c.direct_link(item.get('permalink',''))) and c.direct_link(record.get('permalink',''))==c.direct_link(item.get('permalink','')))

def save_result(first,root,req,job,passed,reason):
 value=dict(material_date='2026-11-26',request_sha256=req,key=job['key'],account=job['account'],target=job['target'],verified=passed,blocked=not passed,reason=reason,at=datetime.now(timezone.utc).isoformat())
 path=root/'logs'/('nov26-comment-gate-'+req[:12]+'.json');files.save(path,value)
 if not passed:
  desktop=Path(os.environ.get('USERPROFILE',str(root)))/'Desktop'
  if not desktop.is_dir():desktop=root/'logs'
  output=desktop/('FB-Nov26-comment-diagnostic-'+uuid.uuid4().hex[:10]+'.zip');paths={path}
  for pattern in ['comment-*-lookup*.json','pending-comment-*-lookup*.json']:
   paths.update(p for p in (root/'logs').glob(pattern) if job['key'][:12] in p.name)
  state=first.upload.read_json(root/'logs/publish_state.json',{}).get(job['key'],{})
  with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
   archive.writestr('first-comment-result.json',json.dumps(dict(gate=value,record=state),ensure_ascii=False,indent=2))
   for p in sorted(paths):
    if p.is_file() and not p.is_symlink():archive.write(p,p.name)
  print('首条评论未通过刷新核验；保留后续评论，视频不重传。诊断包：',output,flush=True)
 return value
