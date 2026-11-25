"""Recover comments for Nov25 frozen jobs only; never submit a video."""
import contextlib,contextvars,copy,json,re,time,uuid,zipfile,os
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import publication_file_state_20261124 as files

VERSION='1.0-nov25-comments-only-created-window-evidence'
DAY='2026-11-25'
RESULT='logs/nov25-comments-repair-results.json'
ACTIVE=contextvars.ContextVar('nov25_comment_diagnostic',default=None)

def verified(first,root,key,text):
    c=first.priority.daily.comments;ledger_key=c.hashlib.sha256((key+'\0'+c.text_hash(text)).encode()).hexdigest()
    item=first.upload.read_json(root/'logs/video_comments.json',{}).get(ledger_key,{})
    record=first.upload.read_json(root/'logs/publish_state.json',{}).get(key,{})
    return (record.get('comment_status') in {'sent','already_present'}
            and (item.get('account'),item.get('target'))==(record.get('account'),record.get('target'))
            and item.get('video_job')==key and item.get('text_sha256')==c.text_hash(text)
            and item.get('status') in {'sent','already_present'} and item.get('verification')=='own_comment_seen_after_reload'
            and bool(item.get('verified_at')) and bool(c.direct_link(item.get('permalink','')))
            and c.direct_link(record.get('permalink',''))==c.direct_link(item.get('permalink','')))

def evidence_rows(payload,limit=60):
    """Only explicit public post fields, never headers, cookies or raw responses."""
    found=[]
    def walk(node,depth=0):
        if depth>24 or len(found)>=limit:return
        if isinstance(node,list):
            for value in node:walk(value,depth+1)
        elif isinstance(node,dict):
            if node.get('__typename') in {'Story','Video','Reel'}:
                row={k:node[k] for k in ('__typename','id','creation_time','created_time','publish_time','is_published','is_pending','is_draft') if isinstance(node.get(k),(str,int,float,bool))}
                for field in ('message','description'):
                    value=node.get(field);value=value.get('text') if isinstance(value,dict) else value
                    if isinstance(value,str):row[field]=value[:4500]
                row['owner_ids']=sorted({str(v['id']) for field in ('owner','video_owner','owning_profile') if isinstance((v:=node.get(field)),dict) and v.get('id')}|{str(a['id']) for a in (node.get('actors') or []) if isinstance(a,dict) and a.get('id')})
                if row.get('id') or 'message' in row or 'description' in row:found.append(row)
            for value in node.values():
                if isinstance(value,(dict,list)):walk(value,depth+1)
    walk(payload);return found

def checked_jobs(day,root,req,controller):
    first=day.first;seen={};waves={}
    if req.get('sha256')!=first.batch.digest(req.get('payload',{})) or req['payload'].get('material_date')!=DAY:raise ValueError('不是11月25日原授权批次')
    if controller.get('request_sha256')!=req['sha256']:raise ValueError('原发布进度指纹不符')
    for wave in controller.get('waves',[]):
        name=wave.get('manifest','')
        if not re.fullmatch(r'frozen-material-\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json',name):raise ValueError('原冻结来源路径异常')
        value=first.archive.checked_json(root/'logs'/name);p=value['payload']
        if value['sha256']!=wave['sha256'] or p.get('queue_id')!=req['sha256'] or p.get('material_source_date')!=DAY or p.get('publication_content_sha256')!=day.CONTENT_SHA:raise ValueError('原视频来源、日期或正文版本不符')
        for job in p['jobs']:
            pair=job['account'],job['target']
            if pair not in day.app.EXPECTED or pair in seen or not job['filename'].startswith('20261125-'):raise ValueError('原评论目标重复或混入其他批次')
            seen[pair]=job;waves[job['key']]=wave
    return list(seen.values()),waves

def write_report(day,root,jobs,blocked=''):
    first=day.first;state=first.upload.read_json(root/'logs/publish_state.json',{});rows=[]
    for job in jobs:
        row=state.get(job['key'],{})
        rows.append(dict(account=job['account'],target=job['target'],key=job['key'],video_status=row.get('status','not_started'),comment_status=row.get('comment_status','not_started'),verified_after_reload=verified(first,root,job['key'],day.app.content_today.COMMENT),reason=row.get('comment_error','')))
    value=dict(material_date=DAY,mode='comments_only',blocked_reason=blocked,automatic_verified=sum(r['verified_after_reload'] for r in rows),rows=rows,updated_at=datetime.now(timezone.utc).isoformat())
    files.save(root/RESULT,value);print('25号仅补评论：刷新核验成功',value['automatic_verified'],'条；',blocked,'报告：',root/RESULT,flush=True)
    return value

def export_diagnostics(root):
    desktop=Path(os.environ.get('USERPROFILE',str(root)))/'Desktop'
    if not desktop.is_dir():desktop=root/'logs'
    output=desktop/('FB-comments-1125-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.zip')
    paths={root/RESULT,root/'logs/eligible60-2026-11-25-comments-repair-run.log'}
    result=json.loads((root/RESULT).read_text(encoding='utf-8-sig'))
    prefixes={r['key'][:12] for r in result['rows']}
    for pattern in ('nov25-comment-evidence-*.json','comment-*-lookup*.json','pending-comment-*-lookup*.json'):
        paths.update(path for path in (root/'logs').glob(pattern) if any(prefix in path.name for prefix in prefixes))
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            if path.is_file() and not path.is_symlink():archive.write(path,path.name)
    print('评论结果及诊断包：',output,flush=True)
    return output

def _execute_current(day,root,real_footage_confirmed=False,comment_lookup_seen=None):
    app=day.app;first=day.first;root=Path(root).resolve()
    if root!=first.upload.ROOT.resolve() or real_footage_confirmed is not True:raise ValueError('原目录或本批实拍确认不符')
    if app.current_workers(root):raise ValueError('仍有发布或登录任务，本入口不并发占用账号')
    if not (root/day.REQUEST).is_file():raise ValueError('尚无25号发布任务，不新建上传批次')
    _,source,journal,material=app.allocation(root)
    with first.locked():req=app.request(root,source,journal,material)
    controller=first.upload.read_json(root/'logs'/('eligible60-real-publication-'+req['sha256'][:16]+'.json'),{})
    jobs,waves=checked_jobs(day,root,req,controller);blocked='';progress=first.upload.read_json(root/'logs'/('nov25-comments-progress-'+os.environ.get('FB_NOV25_COMMENTS_RUN','')+'.json'),{})
    all_verified=False
    for job in sorted(jobs,key=lambda j:(j['account'],j['target'])):
        row=first.upload.read_json(root/'logs/publish_state.json',{}).get(job['key'],{})
        if (job['account'] in app.PAUSED or job['key'] in progress.get('skipped_comments',{})
                or row.get('status') not in {'published','needs_review'} or not row.get('post_intent_at')):continue
        if (row.get('account'),row.get('target'))!=(job['account'],job['target']):raise ValueError('原视频记录与当前目标不符')
        if verified(first,root,job['key'],app.content_today.COMMENT):all_verified=True;continue
        if row.get('comment_status') in {'sent','already_present'}:continue
        day._comment_scope_keys={job['key']}
        detail=dict(account=job['account'],target=job['target'],expected_caption=job['caption_text'],created=row.get('created'),post_intent_at=row.get('post_intent_at'),observed=[],evidence_path=str(root/'logs'/('nov25-comment-evidence-'+job['key'][:12]+'.json')))
        token=ACTIVE.set(detail)
        try:app.run_phase('comments',req,source,journal,material,waves[job['key']],controller,{})
        finally:
            files.save(root/'logs'/('nov25-comment-evidence-'+job['key'][:12]+'.json'),detail);ACTIVE.reset(token)
        if verified(first,root,job['key'],app.content_today.COMMENT):all_verified=True
        elif not all_verified:
            blocked='首条补评未通过刷新核验，已保留诊断；先修复共同卡点，再批量补评。';break
    report=write_report(day,root,jobs,blocked);export_diagnostics(root)
    return 3 if blocked or any(r['video_status'] in {'published','needs_review'} and not r['verified_after_reload'] for r in report['rows'] if r['account'] not in app.PAUSED) else 0

def execute_current(day,root,real_footage_confirmed=False,comment_lookup_seen=None):
    app=day.app
    with patch.object(day.first.batch,'excluded_accounts',side_effect=app.exclusions),patch.object(app.owned,'reservation',side_effect=app.active_reservation):
        return _execute_current(day,root,real_footage_confirmed,comment_lookup_seen)

@contextlib.contextmanager
def installed(day):
    app=day.app;first=day.first
    import published_video_lookup as lookup
    native_add=lookup.Lookup.add;native_evidence=first.priority.actual.Evidence.add;native_request=app.request
    def capture(payload):
        active=ACTIVE.get()
        if active is not None and len(active['observed'])<60:
            changed=False
            for item in evidence_rows(payload,60-len(active['observed'])):
                if item not in active['observed']:active['observed'].append(item);changed=True
            if changed:files.save(Path(active['evidence_path']),active)
    def add(instance,raw):
        for payload in lookup.payloads(raw):capture(payload)
        return native_add(instance,raw)
    def evidence(instance,payload):capture(payload);return native_evidence(instance,payload)
    def existing_request(root,*args,**kwargs):
        if not (Path(root)/day.REQUEST).is_file():raise ValueError('没有已启动的25号批次，不新建视频请求')
        return native_request(root,*args,**kwargs)
    def worker_status(root,phase,message):
        attempt=os.environ.get('FB_PUBLISH_LAUNCH_ID','')
        if re.fullmatch('[a-f0-9]{32}',attempt):files.save(Path(root)/'logs'/('nov25-comments-worker-'+attempt+'.json'),dict(phase=phase,message=message,mode='comments_only',material_date=DAY))
    def no_video(*args,**kwargs):raise ValueError('此入口只补25号评论，禁止上传或点击发布视频')
    def execute(root):
        with day.authorized_context():return app.execute(root,True)
    try:
        with patch.object(app,'execute_current',side_effect=lambda root,real_footage_confirmed=False,comment_lookup_seen=None:execute_current(day,root,real_footage_confirmed,comment_lookup_seen)),patch.object(app,'request',side_effect=existing_request),patch.object(first.upload,'run_entry',side_effect=no_video),patch.object(day,'execute',side_effect=execute),patch.object(day,'worker_status',side_effect=worker_status),patch.object(lookup.Lookup,'add',add),patch.object(first.priority.actual.Evidence,'add',evidence):yield
    finally:
        if hasattr(day,'_comment_scope_keys'):del day._comment_scope_keys
