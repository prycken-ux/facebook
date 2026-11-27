"""Resume only the existing Nov26 request; protect every prior submission."""
import contextlib,copy,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import publication_state_io_20261127 as state_io
import publication_file_state_20261124 as files
VERSION='1.0-original-nov26-only-protect-posted-page09'
KNOWN_PAIR=('fb10','page09')
KNOWN_SUFFIX='035_pagesforpurposeco_7709294079082810637.mp4'


def protect(row):
    if not isinstance(row,dict):raise ValueError('原发布记录格式异常，未恢复上传')
    return row.get('status') in {'preparing','posting','needs_review','published','archived'} or any(row.get(k) for k in ('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at')) or any(protect(v) if isinstance(v,dict) else any(protect(i) for i in v if isinstance(i,dict)) for v in row.values() if isinstance(v,(dict,list)))

def ledger(root):return state_io.read(root/'logs/publish_state.json',required=True,max_bytes=64_000_000)

def audit(day,root,quiet=False):
    req_path=root/day.REQUEST
    req=state_io.read(req_path,required=True)
    p=req.get('payload',{})
    if req.get('sha256')!=day.first.batch.digest(p) or p.get('material_date')!='2026-11-26' or p.get('authorization')!=day.AUTH or p.get('targets')!=[list(pair) for pair in sorted(day.app.EXPECTED)] or p.get('ai_label') is not False or p.get('real_footage_confirmed') is not True or p.get('content_sha256')!=day.CONTENT_SHA:raise ValueError('不是原26号58目标授权，未新建或替换请求')
    _,source,journal,material=day.allocation(root)
    if p.get('stage_sha256')!=source['sha256'] or p.get('distribution_sha256')!=material['sha256']:raise ValueError('原26号分配来源变化，未继续')
    control=state_io.read(root/'logs'/('eligible58-real-publication-'+req['sha256'][:16]+'.json'),required=True)
    if control.get('request_sha256')!=req['sha256']:raise ValueError('原26号控制记录不符')
    jobs={}
    for wave in control.get('waves',[]):
        path=day.app.stage.safe_child(root,root/'logs'/wave['manifest']);value=day.first.archive.checked_json(path);payload=value['payload']
        if value['sha256']!=wave['sha256'] or payload.get('queue_id')!=req['sha256'] or payload.get('material_source_date')!='2026-11-26':raise ValueError('原冻结清单归属异常')
        for job in payload['jobs']:
            if (job['account'],job['target']) not in day.app.EXPECTED or not job['filename'].startswith('20261126-'):raise ValueError('冻结清单混入其他日期目标')
            if job['key'] in jobs and jobs[job['key']]!=job:raise ValueError('冻结视频键冲突')
            jobs[job['key']]=job
    frozen_pairs={(j['account'],j['target']) for j in jobs.values()}
    if not frozen_pairs or not frozen_pairs<=day.app.EXPECTED:raise ValueError('原冻结清单范围异常，未猜选视频')
    state=ledger(root)
    if not isinstance(state,dict):raise ValueError('原发布账本格式异常')
    known=[j for j in jobs.values() if (j['account'],j['target'])==KNOWN_PAIR]
    if len(known)!=1 or not known[0]['filename'].endswith(KNOWN_SUFFIX):raise ValueError('日志已证明提交的fb10/page09原视频不符，未上传')
    preserved={k for k in jobs if k in state and protect(state[k])}
    if len(preserved)<28:raise ValueError('原账本保留的提交/不确定记录少于日志已证明的28项，未将缺失记录当成未开始')
    preserved.add(known[0]['key'])
    result=dict(schema='nov26-state-io-safe-resume-v1',material_date='2026-11-26',request_sha256=req['sha256'],checked_at=datetime.now(timezone.utc).isoformat(),frozen_jobs=len(jobs),protected_keys=sorted(preserved),remaining_unsubmitted_keys=sorted(set(jobs)-preserved),remaining_unfrozen_pairs=[list(p) for p in sorted(day.app.EXPECTED-frozen_pairs)],known_post_click_key=known[0]['key'],known_post_click_source='user-uploaded-Nov26-log-on-Nov27',new_allocation=False)
    if not quiet:
        files.save(root/'logs/nov26-state-io-resume-audit.json',result)
        print('26号原58目标续跑核对：保留已提交/不确定',len(preserved),'条；其余',58-len(preserved),'条按原账本继续；未重建分配。',flush=True)
    return result,jobs

@contextlib.contextmanager
def installed(day,root):
    proof,jobs=audit(day,root)
    first=day.first;native_upload=first.upload.run_entry
    def blocked(key):
        if key not in jobs:
            _,refreshed=audit(day,root,quiet=True);jobs.update(refreshed)
        if key not in jobs:raise ValueError('续跑任务不属于原26号冻结清单')
        return key in proof['protected_keys'] or protect(ledger(root).get(key,{}))
    def upload(entry,*args,**kwargs):
        if blocked(kwargs.get('expected_job_key')):raise RuntimeError('原视频已有提交或不确定记录，禁止再次选择/提交')
        return native_upload(entry,*args,**kwargs)
    with patch.object(first.upload,'run_entry',side_effect=upload):yield
