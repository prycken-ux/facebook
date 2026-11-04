"""Pause fb02 historical tasks and publish only its exact Nov-3 2.mp4 once."""
import ast,copy,hashlib,re,shutil,ssl,sys,urllib.request,uuid
from datetime import datetime,timezone
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

PREFIX='aa7a3134'
GRANT='fb02-nov03-publish-after-historical-pause-20261104'
PROOF=('post_intent_at','permalink','success_message','confirmation_method','confirmed_at','published_at')


def source():
    paths=[p for p in (upload.ROOT/'logs').glob('frozen-material-2026-11-03-'+PREFIX+'*.json')
           if re.fullmatch(r'frozen-material-2026-11-03-[a-f0-9]{16}\.json',p.name)]
    if len(paths)!=1:raise ValueError('没有唯一的11月3日aa7a3134原清单')
    path=paths[0];value=upload.read_json(path,{});payload=value.get('payload',{});jobs=payload.get('jobs',[]);checksum=batch.digest(payload)
    if (value.get('sha256')!=checksum or not checksum.startswith(PREFIX) or not path.stem.endswith(checksum[:16])
            or payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-11-03'
            or payload.get('ai_label') is not False or payload.get('include_fb10_pages') is not True
            or set(payload.get('excluded_accounts',[]))!={'fb16','fb18','fb21'} or payload.get('comment_text')!=daily.COMMENT
            or len(jobs)!=30 or {(j.get('account'),j.get('target')) for j in jobs}!=daily.EXPECTED_PAIRS
            or len({j.get('key') for j in jobs})!=30 or any(not re.fullmatch(r'[a-f0-9]{64}',str(j.get('key',''))) for j in jobs)
            or value.get('report_format')!='text'):raise ValueError('11月3日原30条清单校验失败')
    found=[j for j in jobs if (j['account'],j['target'],j['filename'])==('fb02','page01','2.mp4')]
    if len(found)!=1:raise ValueError('没有唯一的fb02/page01原2.mp4')
    report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if report.get('manifest')!=path.name or not isinstance(report.get('attempts'),list):raise ValueError('原批次结果不匹配')
    return path,value,copy.deepcopy(found[0])


def check_current(job,state):
    row=state.get(job['key'])
    if row is None:return 'not_started'
    if ((row.get('account'),row.get('target'))!=('fb02','page01') or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
            or str(row.get('video','')).replace('\\','/').split('/')[-1]!='2.mp4'):raise ValueError('昨天2.mp4的任务记录不一致')
    if row.get('status')=='published':return 'published'
    if row.get('status')!='failed_before_post' or any(row.get(k) for k in PROOF):
        raise ValueError('昨天2.mp4已有提交或成功线索，不能重复发布；保留当前结果待核实')
    if row.get('today_first_retry_used') or row.get('previous_before_post_attempt'):
        raise ValueError('昨天2.mp4已有重试记录，未额外重置机会')
    return 'failed_before_post'


def pause_history(state,current_key):
    updated=copy.deepcopy(state);changes=[];now=datetime.now(timezone.utc).isoformat()
    for key,row in updated.items():
        if key==current_key or row.get('account')!='fb02' or row.get('status') not in {'preparing','posting','needs_review','failed_before_post'}:continue
        raw=row.get('created') or row.get('post_intent_at')
        try:
            created=datetime.fromisoformat(raw)
            if created.tzinfo is None:raise ValueError
        except (TypeError,ValueError):raise ValueError('fb02有无法确定日期的旧任务，保留记录，未发布')
        if created.astimezone(batch.BJ).date().isoformat()>='2026-11-03':
            if row['status'] in {'preparing','posting'}:raise ValueError('fb02另有11月3日或之后的进行中任务，未作为历史任务暂停')
            continue
        before=copy.deepcopy(row)
        row.update(status='paused',paused_previous_status=row['status'],paused_at=now,pause_authorization=GRANT,
                   pause_reason='用户要求暂停fb02历史旧任务，保留旧发布结果线索，仅处理11月3日2.mp4')
        changes.append(dict(key=key,prior_record=before))
    return updated,changes


def media(job,state):
    entry=batch.validate_job(job)
    selected=upload.named_job(entry,state,'2.mp4',retry_before_post=state.get(job['key'],{}).get('status')=='failed_before_post')
    if not selected or selected[0]!=job['key'] or selected[3]!=job['caption_text']:
        raise ValueError('原2.mp4指纹或原文案不匹配，未选择其他素材')
    return dict(entry,enabled=True,auto_switch_personal=True,_authorized_comment_text=daily.COMMENT)


def preflight(entry):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        context=upload.launch_context(playwright,entry)
        try:
            page=context.new_page();upload.navigate_profile(page,entry['url']);upload.require_no_advanced_protection(page)
            upload.ensure_identity(page,entry)
        finally:context.close()


def refresh(path,value,attempt=None):
    prior=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if prior.get('manifest')!=path.name or not isinstance(prior.get('attempts'),list):raise ValueError('原结果报告变化，未覆盖')
    attempts=prior['attempts']
    if attempt is not None:attempts=attempts+[attempt]
    return batch.results(path,value,attempts,None,final=False)


def execute():
    if upload.VERSION!='2.47':raise ValueError('配套发布核心需为2.47')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!='2026-11-04':raise ValueError('本指令仅限北京时间11月4日处理11月3日原2.mp4')
    state_path=upload.ROOT/'logs/publish_state.json';claim_path=upload.ROOT/'logs'/(GRANT+'-claim.json')
    with locked(),daily.keep_awake():
        path,value,job=source();state=upload.read_json(state_path,{})
        action=check_current(job,state);planned,pauses=pause_history(state,job['key'])
        claim=upload.read_json(claim_path,None)
        if claim is not None and (claim.get('grant')!=GRANT or claim.get('key')!=job['key'] or claim.get('source_sha256')!=value['sha256']):raise ValueError('本次单条发布账本异常')
        if action!='published' and claim is not None and not (claim.get('phase') in {'reserved','not_started'} and job['key'] not in state):
            raise ValueError('本次单条发布机会已使用，保留结果，不再次点击Post')
        if action!='published':entry=media(job,state)
        close_selected_window('fb02')
        if upload.read_json(state_path,{})!=state:raise ValueError('关闭窗口期间发布记录变化，未覆盖')
        backup=upload.ROOT/'backups'/(GRANT+'-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        upload.save_json(backup/'publish_state.json',state)
        for document in (path,path.with_name(path.stem+'-results.json')):shutil.copy2(document,backup/document.name)
        upload.save_json(backup/'pause-audit.json',dict(grant=GRANT,source_manifest=path.name,changes=pauses))
        if pauses:upload.save_json(state_path,planned)
        state=planned
        print('已暂停fb02历史任务：',len(pauses),'条；旧Post意图和原状态保留在记录及备份中。',flush=True)
        if action=='published':refresh(path,value);print('昨天fb02/page01 2.mp4已成功，未重复发布。',flush=True);return 0
        print('核对fb02原网络及主页身份；只准备11月3日原2.mp4。',flush=True)
        preflight(entry)
        if upload.read_json(state_path,{})!=state:raise ValueError('身份核验期间记录变化，未发布')
        media(job,state)
        claim=dict(grant=GRANT,key=job['key'],source_sha256=value['sha256'],source_manifest=path.name,
                   phase='reserved',reserved_at=datetime.now(timezone.utc).isoformat(),original_record=copy.deepcopy(state.get(job['key'])))
        upload.save_json(claim_path,claim)
        attempt=dict(account='fb02',target='page01',key=job['key'],started_at=datetime.now(timezone.utc).isoformat(),
                     action='manual_required',attempt_phase=GRANT)
        try:
            print('现在仅发布：fb02/page01 2.mp4；原文案，实拍，AI标签关闭。',flush=True)
            upload.run_entry(entry,state,state_path,True,filename='2.mp4',ai_label_override=False,
                             expected_job_key=job['key'],preserve_old_review_for_exact_job=True,defer_comments=True,
                             retry_before_post=action=='failed_before_post')
            attempt['action']='finished'
        except BaseException as error:
            attempt['error']=(str(error) or type(error).__name__)[:2000];raise
        finally:
            current=upload.read_json(state_path,{})
            claim.update(phase='consumed' if job['key'] in current else 'not_started',result_status=current.get(job['key'],{}).get('status','not_started'))
            upload.save_json(claim_path,claim);refresh(path,value,attempt)
        current=upload.read_json(state_path,{}).get(job['key'],{})
        print('本次结果：fb02/page01 2.mp4：',current.get('status','not_started'),'；评论留待后续处理。',flush=True)
        return 0 if current.get('status')=='published' else 3


def recover_locks():
    if not any((upload.ROOT/'logs'/name).exists() for name in ('batch.lock','upload.lock')):return
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    expected='2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3'
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(base+'d8c998c705801c948a230c0504fcb65653ae8086/downloads/recover_resume_new_batch.py',context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Lock helper checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));break
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    else:raise RuntimeError('锁核验组件下载失败，未启动发布')
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(data,'verified-lock-library','exec'),namespace);namespace['recover_locks'](upload.ROOT)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if sys.platform!='win32' or upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原Windows上传电脑运行')
        recover_locks();raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止；旧任务保持暂停，已有Post意图保留，不要清空记录重发。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
