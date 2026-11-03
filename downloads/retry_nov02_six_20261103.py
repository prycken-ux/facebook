"""Nov-3 authorization: retry only the six reported Nov-2 before-Post failures once."""
import ast,copy,hashlib,re,ssl,sys,time,urllib.request,zipfile
from datetime import datetime,timezone
from pathlib import Path

if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

DATE='2026-11-03'
PREFIX='f6cc163c'
GRANT='retry-nov02-six-authorized-20261103'
SPEC={
 ('fb01','page01'):('4a96d3068021','11021店权利1.0.mp4'),
 ('fb03','personal'):('aec6e81aeb5e','11021店权利3.0.mp4'),
 ('fb04','personal'):('d3feb954c609','11021店权利4.0.mp4'),
 ('fb05','page01'):('27a09f06a816','11021店说话1.0.mp4'),
 ('fb06','page01'):('925f0d93df5c','11022店权利1.0.mp4'),
 ('fb10','page01'):('66d690b685fd','新脚本_20261101-181032.mp4'),
}
PROOF=('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at','today_first_retry_used','previous_before_post_attempt')


def load_source():
    paths=[p for p in (upload.ROOT/'logs').glob('frozen-material-2026-11-02-'+PREFIX+'*.json')
           if re.fullmatch(r'frozen-material-2026-11-02-[a-f0-9]{16}\.json',p.name)]
    if len(paths)!=1:raise ValueError('没有唯一的11月2日f6cc163c原清单，未改选最新素材')
    path=paths[0];value=upload.read_json(path,{});payload=value.get('payload',{});checksum=batch.digest(payload)
    if (value.get('sha256')!=checksum or not checksum.startswith(PREFIX) or not path.stem.endswith(checksum[:16])
            or payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-11-02'
            or payload.get('ai_label') is not False or payload.get('include_fb10_pages') is not True
            or set(payload.get('excluded_accounts',[]))!={'fb16','fb18','fb21'}
            or payload.get('comment_text')!=daily.COMMENT or len(payload.get('jobs',[]))!=30):
        raise ValueError('11月2日原30条清单校验失败，未选择其他日期或文件')
    report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if report.get('manifest')!=path.name:raise ValueError('原批次结果报告不匹配')
    jobs=[]
    for pair,(prefix,filename) in SPEC.items():
        found=[j for j in payload['jobs'] if (j.get('account'),j.get('target'))==pair
               and j.get('filename')==filename and re.fullmatch(r'[a-f0-9]{64}',str(j.get('key','')))
               and j['key'].startswith(prefix)]
        if len(found)!=1:raise ValueError('没有唯一的指定失败原视频：'+'/'.join(pair))
        job=found[0];rows=[r for r in report.get('rows',[]) if r.get('key')==job['key']]
        if len(rows)!=1 or rows[0].get('video_status')!='failed_before_post':
            raise ValueError('指定条目在原报告中不是发布前失败，未扩大发送范围：'+'/'.join(pair))
        jobs.append(copy.deepcopy(job))
    return path,value,jobs


def claims_document():
    path=upload.ROOT/'logs'/(GRANT+'-claims.json')
    claims=upload.read_json(path,{'grant':GRANT,'jobs':{}})
    if claims.get('grant')!=GRANT or not isinstance(claims.get('jobs'),dict):
        raise ValueError('本次补发账本异常，未重置发送机会')
    return path,claims


def validate(job,state):
    pair=job['account'],job['target'];prefix,filename=SPEC[pair]
    if not job['key'].startswith(prefix) or job['filename']!=filename:raise ValueError('任务不在指定六条范围')
    old=state.get(job['key'])
    if (not isinstance(old,dict) or (old.get('account'),old.get('target'))!=pair
            or upload.target_key(old.get('url',''))!=upload.target_key(job['url'])
            or str(old.get('video','')).replace('\\','/').split('/')[-1]!=filename):
        raise ValueError('当前记录与原视频不一致，未把缺失记录当成新任务')
    if old.get('status')=='published':return None,'already_published'
    if old.get('status')!='failed_before_post' or any(old.get(k) for k in PROOF):
        raise ValueError('已有提交/成功线索、待核实或已重试，保留不重发')
    if old.get('uploader_version')!='2.47' or old.get('ai_label_requested') is not False:
        raise ValueError('原发布版本或AI设置不满足本次原素材补发条件')
    if any(r.get('account')==job['account'] and r.get('status') in {'preparing','posting'} for r in state.values()):
        raise ValueError('同账号另有准备或提交中的任务，未关闭其窗口或改动旧记录')
    automatic=upload.read_json(upload.ROOT/'logs/automatic_before_post_retry_claims.json',{'schema':'automatic-before-post-retry-claims-v1','jobs':{}})
    if automatic.get('schema')!='automatic-before-post-retry-claims-v1' or not isinstance(automatic.get('jobs'),dict):
        raise ValueError('自动补发账本异常，不能排除已有重试')
    if job['key'] in automatic['jobs']:raise ValueError('此视频已有自动补发机会记录，未另外追加重试')
    entry=batch.validate_job(job)
    selected=upload.named_job(entry,state,filename,retry_before_post=True)
    if not selected or selected[0]!=job['key'] or selected[3]!=job['caption_text']:
        raise ValueError('原视频或原文案缺失/变化，未选择其他文件')
    return entry,'ready'


def reserve(job,path,value,state):
    entry,action=validate(job,state)
    if action=='already_published':return None,action
    ledger,claims=claims_document()
    if job['key'] in claims['jobs']:raise ValueError('本次补发机会已使用，未重复启动')
    claim=dict(account=job['account'],target=job['target'],filename=job['filename'],source_manifest=path.name,
        source_sha256=value['sha256'],reserved_at=datetime.now(timezone.utc).isoformat(),original_record=copy.deepcopy(state[job['key']]))
    backup=upload.ROOT/'backups'/(GRANT+'-'+job['key'][:12]+'-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True);upload.save_json(backup/'publish_state.json',state)
    upload.save_json(backup/'authorization.json',claim)
    claims['jobs'][job['key']]=claim;upload.save_json(ledger,claims)  # Before browser operations.
    return entry,action


def preflight(entry):
    """Fresh browser, original network, known identity switch; no file selection."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        context=upload.launch_context(playwright,entry)
        try:
            page=context.new_page();page.set_default_timeout(15000)
            for attempt in range(2):
                try:
                    upload.navigate_profile(page,entry['url']);break
                except Exception as error:
                    upload.checkpoint(page)
                    if attempt or not any(x in str(error) for x in ('ERR_PROXY_CONNECTION_FAILED','ERR_TUNNEL_CONNECTION_FAILED')):raise
                    print('原网络/代理连接失败，2秒后仅重试打开主页一次；尚未上传。',flush=True);page.wait_for_timeout(2000)
            upload.require_no_advanced_protection(page)
            upload.ensure_identity(page,entry)
        finally:context.close()


def report(jobs,attempts,path,final=False):
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{});rows=[]
    labels={'published':'发布成功','failed_before_post':'仍未发布','needs_review':'已提交待核实','posting':'已提交待核实','preparing':'准备中待核实','not_started':'尚未开始'}
    lines=['11月2日六条发布前失败补发结果（11月3日授权）','']
    for job in jobs:
        row=state.get(job['key'],{});attempt=attempts.get(job['key'],{})
        item=dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],
            video_status=row.get('status','not_started'),comment_status=row.get('comment_status','not_started'),
            action=attempt.get('action','not_started'),error=attempt.get('error',''))
        rows.append(item)
        line=job['account']+'/'+job['target']+' '+job['filename']+'：'+labels.get(item['video_status'],item['video_status'])
        if item['action']=='already_published':line+='（本次未重发，原记录已成功）'
        elif item['action']=='reserved':line+='（正在检查环境，尚未开始补发）'
        elif item['action']=='not_started':line+='（本次尚未处理）'
        elif item['action']=='preflight_failed':line+='（环境核验失败，尚未选择视频）'
        if item['error']:line+='；'+item['error'].split('\n',1)[0]
        lines.append(line)
    lines+=['','本次成功视频的评论：']
    for row in rows:
        if row['video_status']=='published':lines.append(row['account']+'/'+row['target']+'：'+row['comment_status'])
    lines+=['','仅处理指定六条；fb07已由用户确认成功，不重发。其余待核实任务、fb02尚未开始、31号旧素材及今天新素材未被补发。']
    folder=upload.ROOT/'logs';result=folder/(GRANT+'-results.json');summary=folder/(GRANT+'-results.txt')
    upload.save_json(result,dict(grant=GRANT,source_manifest=path.name,rows=rows,attempts=attempts));summary.write_text('\n'.join(lines),encoding='utf-8-sig')
    if final:
        with zipfile.ZipFile(folder/(GRANT+'-results.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
            archive.write(result,'results.json');archive.write(summary,'summary.txt')
        print('\n'.join(lines),flush=True)
    return rows


def execute():
    if upload.VERSION!='2.47':raise ValueError('此六条补发配套当前上传核心2.47，未自动升级或降级')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('此六条补发仅限北京时间2026年11月3日执行')
    attempts={};success=[];state_path=upload.ROOT/'logs/publish_state.json'
    with locked(),daily.keep_awake():
        path,value,jobs=load_source()
        for job in jobs:
            attempt=attempts[job['key']]={'action':'not_started'}
            try:
                state=upload.read_json(state_path,{})
                entry,action=reserve(job,path,value,state)
                if action=='already_published':attempt['action']=action;continue
                attempt['action']='reserved';report(jobs,attempts,path)
                print('\n补发前核对原素材、网络及身份：',job['account'],job['target'],job['filename'],flush=True)
                close_selected_window(entry['account'])
                runtime=dict(entry,enabled=True,auto_switch_personal=True,_authorized_comment_text=daily.COMMENT)
                preflight(runtime)
                if upload.read_json(state_path,{})!=state:raise ValueError('环境核验期间发布记录变化，未补发')
                validate(job,state)
                attempt['action']='attempted'
                upload.run_entry(runtime,state,state_path,True,filename=job['filename'],ai_label_override=False,
                    expected_job_key=job['key'],preserve_old_review_for_exact_job=True,defer_comments=True,retry_before_post=True)
                if upload.read_json(state_path,{}).get(job['key'],{}).get('status')=='published':success.append(job)
            except KeyboardInterrupt:raise
            except Exception as error:
                if attempt['action']=='reserved':attempt['action']='preflight_failed'
                elif attempt['action']=='not_started':attempt['action']='skipped'
                attempt['error']=(str(error) or type(error).__name__)[:2000]
                print('此条保留记录，继续下一条：',attempt['error'].split('\n',1)[0],flush=True)
            finally:report(jobs,attempts,path)
        if success:
            payload=dict(date=DATE,jobs=success);manifest=dict(payload=payload,sha256=batch.digest(payload))
            daily.backfill(manifest,None,only_keys={j['key'] for j in success},future_only=True,already_locked=True,
                reporter=lambda *_:report(jobs,attempts,path))
        rows=report(jobs,attempts,path,final=True)
    return 0 if all(r['video_status']=='published' for r in rows) else 3


def recover_locks(root):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    sha='2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3';commit='d8c998c705801c948a230c0504fcb65653ae8086'
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(base+commit+'/downloads/recover_resume_new_batch.py',context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Lock helper checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));break
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    else:raise RuntimeError('锁核验组件下载失败，未启动补发')
    namespace={'__name__':'verified_lock_cleanup_library','__file__':'verified_lock_cleanup.py'}
    exec(compile(data,'verified-lock-cleanup','exec'),namespace);namespace['recover_locks'](root)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        root=Path(sys.argv[1]).resolve()
        if sys.platform!='win32' or upload.ROOT.resolve()!=root:raise ValueError('请在原Windows上传目录运行')
        if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('此补发指令仅限北京时间11月3日')
        recover_locks(root)
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止，保留补发机会及发布记录，不要清空记录后重复发。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
