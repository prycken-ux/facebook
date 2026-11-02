"""Only repair comments on confirmed-published Oct-31 jobs; never upload videos."""
import argparse,hashlib,json,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import safe_video_comments as comments
from add_fb_accounts import locked

DATE='2026-11-02'
SOURCE='frozen-material-2026-10-31-154db1cebacb7ab5.json'
PROTECTED={'sent','already_present','sending','verifying','needs_review'}


def retry_audit():
    path=upload.ROOT/'logs/automatic_before_post_retry_claims.json'
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    ledger=upload.read_json(path,{'schema':'automatic-before-post-retry-claims-v1','jobs':{}})
    if ledger.get('schema')!='automatic-before-post-retry-claims-v1' or not isinstance(ledger.get('jobs'),dict):
        return dict(message='自动补发账本格式异常，不能核实实际执行；没有重置账本',rows=[])
    rows=[]
    for key,claim in ledger['jobs'].items():
        record=state.get(key,{});marker=record.get('automatic_retry',{})
        bound=(marker.get('source_sha256')==claim.get('source_sha256') and marker.get('source_manifest')==claim.get('source_manifest') and marker.get('retry_number')==1)
        try:after=bool(record.get('post_intent_at')) and datetime.fromisoformat(record['post_intent_at'])>=datetime.fromisoformat(claim['reserved_at'])
        except (ValueError,KeyError,TypeError):after=False
        if bound and after and record.get('status')=='published' and record.get('confirmation_method')=='fresh_success_ui_and_composer_closed':category='自动补发后已取得成功回执'
        elif bound and after:category='自动补发已提交，结果待核实'
        elif bound and record.get('status')=='failed_before_post':category='自动补发仍在 Post 前失败'
        else:category='机会已占用，日志尚不足以确认实际补发结果'
        rows.append(dict(account=claim.get('account'),target=claim.get('target'),key=key,category=category))
    checked=len(list((upload.ROOT/'logs').glob('automatic-retry-audit-*.json')))
    message=('已检查队列'+str(checked)+'批，保留补发机会'+str(len(rows))+'条。')
    if not rows:message+='目前没有实际自动补发记录；安装成功本身不代表补发已实测完成。'
    return dict(message=message,rows=rows)


def source_manifest():
    value=upload.read_json(upload.ROOT/'logs'/SOURCE,{})
    payload=value.get('payload',{});checksum=batch.digest(payload)
    if (value.get('sha256')!=checksum or not Path(SOURCE).stem.endswith(checksum[:16]) or payload.get('schema')!=batch.SCHEMA
            or payload.get('date')!='2026-10-31' or len(payload.get('jobs',[]))!=30 or payload.get('comment_text')!=daily.COMMENT
            or set(payload.get('excluded_accounts',[]))!={'fb16','fb18','fb21'}):raise ValueError('10月31日原清单校验失败，未改选其他批次')
    return value


def write_report(value,rows,audit,output_dir,final=False,note=''):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    by_key={r['key']:r for r in rows};jobs=[j for j in value['payload']['jobs'] if state.get(j['key'],{}).get('status')=='published']
    lines=['10月31日已成功视频的评论修复（本次：11月2日）','未上传任何视频，只核验并处理原成功视频的评论。','', '自动补发核验：'+audit['message']]
    lines.extend(str(r['account'])+'/'+str(r['target'])+'：'+r['category'] for r in audit['rows'])
    lines+=['','评论处理结果：']
    labels={'sent':'评论已确认成功','already_present':'已有规定评论并保留','manual_required':'未完成，需人工处理','needs_review':'发送结果待核实，不重复发','sending':'已有发送意图，跳过','verifying':'刷新核验待完成，跳过','video_not_confirmed':'视频未确认成功，跳过'}
    for job in jobs:
        row=by_key.get(job['key']);record=state[job['key']]
        if row:status=row['status'];error=row.get('error','')
        else:status=record.get('comment_status','not_started');error='本次尚未尝试或原记录受到保护'
        lines.append(job['account']+'/'+job['target']+' '+job['filename']+'：'+labels.get(status,status)+('；'+error.split('\n',1)[0] if error else ''))
    if note:lines+=['',note]
    stem='31号成功视频评论修复-20261102';folder=upload.ROOT/'logs'
    result=folder/(stem+'.json');summary=folder/(stem+'.txt')
    upload.save_json(result,dict(source=SOURCE,video_upload_started=False,retry_audit=audit,rows=rows,note=note));summary.write_text('\n'.join(lines),encoding='utf-8-sig')
    out=Path(output_dir) if output_dir and Path(output_dir).is_dir() else folder
    with zipfile.ZipFile(out/(stem+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        z.write(result,'results.json');z.write(summary,'summary.txt')
        for row in rows:
            for suffix in ['-lookup.json','.aria.txt','.png','-error.txt']:
                file=folder/('comment-'+row['key'][:12]+suffix)
                if file.is_file():z.write(file,file.name)
    if final:print('\n'.join(lines),flush=True);print('诊断记录：',out/(stem+'.zip'),flush=True)


def execute(output_dir=None):
    if upload.VERSION!='2.47' or comments.COMMENT_WORKFLOW_VERSION!='1.4-exact-post-lookup':raise ValueError('需先安装核心2.47及评论定位1.4')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('此次31号评论修复仅在北京时间11月2日执行')
    rows=[];gate=False;note='';attempted=set()
    with locked(),daily.keep_awake():
        value=source_manifest();audit=retry_audit();print('自动补发核验：',audit['message'],flush=True)
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{});ledger=upload.read_json(upload.ROOT/'logs/video_comments.json',{})
        selected=[]
        for job in value['payload']['jobs']:
            record=state.get(job['key'],{})
            key=hashlib.sha256((job['key']+'\0'+comments.text_hash(daily.COMMENT)).encode()).hexdigest()
            if record.get('status')=='published' and record.get('comment_status') not in PROTECTED and ledger.get(key,{}).get('status') not in PROTECTED:selected.append(job)
        reporter=lambda *_:write_report(value,rows,audit,output_dir)
        for job in selected[:3]:
            print('先验证一条实际评论：',job['account'],job['target'],job['filename'],flush=True);attempted.add(job['key'])
            daily.backfill(value,output_dir,only_keys={job['key']},rows=rows,already_locked=True,future_only=True,reporter=reporter)
            key=hashlib.sha256((job['key']+'\0'+comments.text_hash(daily.COMMENT)).encode()).hexdigest();proof=upload.read_json(upload.ROOT/'logs/video_comments.json',{}).get(key,{})
            if rows[-1]['status'] in {'sent','already_present'} and proof.get('verification')=='own_comment_seen_after_reload':
                gate=True;print('单条实际核验通过，继续其余已成功视频的评论。',flush=True);break
            if rows[-1]['status'] in {'sending','verifying','needs_review'} or proof.get('status') in {'sending','verifying','needs_review'}:
                note='首条发送结果尚未确认，已停止批量发送，未重复发。';break
        if gate:
            remaining={j['key'] for j in selected if j['key'] not in attempted}
            if remaining:daily.backfill(value,output_dir,only_keys=remaining,rows=rows,already_locked=True,future_only=True,reporter=reporter)
        elif selected and not note:note='尚未取得一条刷新后确认成功的实际评论，已停止继续批量尝试；请保留定位诊断。'
        elif not selected:note='没有可安全补评的成功视频；已有发送或待核实记录继续保留。'
        write_report(value,rows,audit,output_dir,final=True,note=note)
    return 0 if rows and all(r['status'] in {'sent','already_present'} for r in rows) and gate else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser(description='修复31号已成功视频的评论并核验自动补发日志；不上传任何视频')
    parser.add_argument('--output-dir',type=Path);args=parser.parse_args()
    try:raise SystemExit(execute(args.output_dir))
    except KeyboardInterrupt:print('已停止，保留评论发送意图，请勿直接重复发。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
