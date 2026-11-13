"""Print Nov12 new-batch state from local JSON only; never import the publisher."""
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

DAY='2026-11-12'
SCOPE='nov12-current-materials-fb01-to-fb24-v1'


def read(path,default):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else default


def checked(value):
    payload=value.get('payload',{})
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if value.get('sha256')!=digest:raise ValueError('清单指纹不一致，未猜测发布结果。')
    return payload


def allowed(account,target):
    return bool(re.fullmatch(r'fb(?:0[1-9]|[1-9][0-9]+)',str(account)) and 1<=int(account[2:])<=24 and re.fullmatch(r'personal|page[0-9]{2,}',str(target)))


def collect(root):
    logs=Path(root)/'logs'
    if not logs.is_dir():raise ValueError('没有找到原上传程序的logs目录。')
    state=read(logs/'publish_state.json',{})
    if not isinstance(state,dict):raise ValueError('发布状态文件格式异常。')
    controller=read(logs/'nov12-current-materials-original-accounts.json',None)
    snapshot=[];issues={}
    if controller is not None:
        payload=checked(controller)
        if payload.get('scope')!=SCOPE or payload.get('date')!=DAY:raise ValueError('素材快照不属于11月12日新批次。')
        snapshot=payload.get('records',[])
        issues={r.get('account'):r.get('reason','') for r in controller.get('setup_issues',[])}
    rows={};covered=set();plans=0
    for path in sorted(logs.glob('frozen-material-'+DAY+'-*.json')):
        value=read(path,{})
        if value.get('payload',{}).get('current_material_scope')!=SCOPE:continue
        payload=checked(value)
        if payload.get('date')!=DAY or not path.stem.endswith(value['sha256'][:16]):raise ValueError('发布清单的日期或文件名异常。')
        plans+=1
        report=read(path.with_name(path.stem+'-results.json'),{})
        attempts={r['key']:r for r in report.get('attempts',[]) if isinstance(r,dict) and r.get('key')} if report.get('manifest')==path.name else {}
        for job in payload.get('jobs',[]):
            account,target=job['account'],job['target']
            if not allowed(account,target):raise ValueError('清单混入本次不发布的账号，未合并统计。')
            key=job['key'];record=state.get(key,{})
            identity_ok=(not record or (record.get('account'),record.get('target'),record.get('url'))==(account,target,job['url']))
            status=record.get('status','not_started')
            if not identity_ok:label='待核实'
            elif status=='published':label='发布成功'
            elif status=='failed_before_post' and not record.get('post_intent_at'):label='发布前失败'
            elif status in {'preparing','posting','needs_review','failed_before_post'}:label='待核实'
            elif status=='not_started':label='未开始'
            elif status in {'cancelled','paused','skipped'}:label='未发布/已暂停'
            else:label='待核实'
            reason=(record.get('comment_error','') if label=='发布成功' else record.get('error') or attempts.get(key,{}).get('error',''))
            if not identity_ok:reason='状态记录与清单身份不一致，需核对。'
            if status in {'preparing','posting'}:reason='窗口关闭或任务中断时尚无最终结果，需先核实。'
            row=dict(account=account,target=target,filename=job['filename'],video_status=label,
                     comment_status=record.get('comment_status','not_started') if label=='发布成功' else 'not_started',reason=str(reason).split('\n',1)[0])
            if key in rows and rows[key]!=row:raise ValueError('同一视频在不同清单中的记录不一致。')
            rows[key]=row
            covered.add((account,target,job['filename']))
    for record in snapshot:
        pair=(record['account'],record['target'],record['filename'])
        if not allowed(pair[0],pair[1]):raise ValueError('素材快照包含本次范围外的账号。')
        if pair not in covered:
            rows['snapshot:'+str(pair)]=dict(account=pair[0],target=pair[1],filename=pair[2],video_status='未进入发布清单',comment_status='not_started',reason=issues.get(pair[0],'未生成发布任务，可能仍在核验身份或检查素材。'))
    return sorted(rows.values(),key=lambda r:(int(r['account'][2:]),r['target'],r['filename'])),plans,controller is not None


def summarize(root):
    rows,plans,has_snapshot=collect(root)
    print('11月12日新素材批次：本地保存记录的最新状态（只读汇总）',flush=True)
    if not rows:
        print('未找到该批次的逐条发布记录。'+('已找到素材快照。' if has_snapshot else '也未找到新素材快照，流程可能尚未进入视频发布阶段。'),flush=True)
        print('本次没有打开浏览器、上传视频、发送评论或修改记录。',flush=True)
        return
    counts=Counter(r['video_status'] for r in rows)
    print('合计 '+str(len(rows))+' 条；'+ '；'.join(name+' '+str(counts.get(name,0))+' 条' for name in ('发布成功','发布前失败','待核实','未开始','未进入发布清单','未发布/已暂停')),flush=True)
    comments={'sent':'已确认成功','already_present':'已有规定评论（已核实）','sending':'提交中待核实','verifying':'刷新核实中','needs_review':'待核实','manual_required':'未确认成功/需处理','preparing':'准备评论','deferred':'等待评论','lookup_pending':'等待定位','not_started':'未开始'}
    for label in ('发布成功','发布前失败','待核实','未开始','未进入发布清单','未发布/已暂停'):
        group=[r for r in rows if r['video_status']==label]
        if not group:continue
        print('\n'+label+'：'+str(len(group))+'条',flush=True)
        for row in group:
            line=row['account']+'/'+row['target']+' '+row['filename']
            if label=='发布成功':line+='；评论：'+comments.get(row['comment_status'],row['comment_status'])
            if row['reason']:line+='；'+row['reason'][:350]
            print(line,flush=True)
    confirmed=sum(r['video_status']=='发布成功' and r['comment_status'] in {'sent','already_present'} for r in rows)
    pending=sum(r['video_status']=='发布成功' and r['comment_status'] in {'sending','verifying','needs_review'} for r in rows)
    remaining=counts.get('发布成功',0)-confirmed-pending
    print('\n评论确认成功：'+str(confirmed)+'条；评论待核实：'+str(pending)+'条；其余成功视频评论未完成：'+str(remaining)+'条。',flush=True)
    print('仅统计11月12日新素材批次，未合并旧视频补发；本次没有重新发布或改动记录。',flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:summarize(Path(sys.argv[1]))
    except Exception as error:print('汇总停止：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
