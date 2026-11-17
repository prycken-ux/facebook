"""Publish exact newly allocated78 real clips; manual recovery is last only."""
import contextlib,copy,hashlib,importlib.util,re,shutil,sys,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parent))
import eligible78_publication_workflow as queued
import retry_eligible78_prepost_20261117 as extra
import publish_all_distributed_nov13 as owned
import publish_unplanned_fortysix_nov14 as owners
import finish_first24_nov14_on_nov16 as browser
first=queued.first
VERSION='1.0-eligible78-real-video-comment-automatic-first-manual-last'
BLOCKED={f'fb{n:02d}' for n in (17,23,28,30,33,35,36,38,41,58,64,69,71,72,73,74)}
ALLOWED={f'fb{n:02d}' for n in range(1,75)}-BLOCKED
ACTIVE_NEW={a for a in ALLOWED if int(a[2:])>=25}
REQUEST='logs/eligible78-real-publication-request-20261117.json'
AVAILABILITY='publication_account_exclusions.json'
AUTH=queued.AUTH
ACCOUNT_FAILURE=re.compile(r'captcha|checkpoint|two[_ -]?(?:step|factor)|advanced protection|account.{0,32}(?:disabled|restricted|suspended)|log[ -]?in|sign[ -]?in|session expired|2fa|安全验证|验证码|登录|账号限制|身份不一致|本人不同|登录者|资料.*(?:占用|缺失)|profile.*busy',re.I)


def sibling(name):
    spec=importlib.util.spec_from_file_location('_eligible78_'+Path(name).stem,Path(__file__).resolve().with_name(name));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
stage=sibling('stage_eligible78_materials_v4.py')
workers=sibling('material_distribution_worker_check.py')
EXPECTED=stage.EXPECTED
EXCLUDED=first.batch.excluded_accounts
BOOTSTRAP=re.compile(workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_publish_eligible78_real_20261117').replace('verified-first24-material-distribution','verified-real-eligible78-publication'))


def today():return datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()
def exclusions(day=None):return (EXCLUDED(day)-ALLOWED)|BLOCKED


def active_reservation():
    value=first.upload.read_json(first.upload.ROOT/'additional_personal_accounts.json',{})
    batch=value.get('batches',{}).get(owned.BATCH_ID,{})
    if (value.get('schema')!='additional-personal-logins-v1' or batch.get('accounts')!=sorted(owned.NEW) or batch.get('count')!=50
            or any(value.get('slots',{}).get(a,{}).get('batch_id')!=owned.BATCH_ID for a in ACTIVE_NEW)):
        raise ValueError('可用新账号不是原预留代次，未恢复旧删除账号或猜测编号。')
    return value


def current_workers(root):
    with patch.object(workers,'BOOTSTRAP',BOOTSTRAP):return workers.active_workers(root,Path(__file__).resolve())


def allocation(root):
    stage.setup(root);pointer=first.upload.read_json(stage.safe_child(root,root/'material-staging/eligible78-pending-import.json'),{})
    if pointer and pointer.get('complete') is not True:
        print('原78目标分配还未收尾；先从上次选定的总目录续完原分配，再发布。不选择其他来源。',flush=True)
        distributor=sibling('distribute_eligible78_materials_20261117.py')
        with patch.object(distributor,'inspect_workers',side_effect=current_workers):distributor.execute(root)
        pointer=first.upload.read_json(root/'material-staging/eligible78-pending-import.json',{})
    if pointer.get('complete') is not True:raise ValueError('尚未找到78条新素材的原分配清单，请先运行78目标分配指令；未猜选旧素材。')
    manifest=stage.safe_child(root,root/pointer.get('manifest',''));_,source=stage.validate_stage(root,manifest);p=source['payload'];material=p['distribution'];rows=material['payload']['assignments']
    stage.check_scope(rows)
    if p['distribution']['payload'].get('target_scope')!='eligible78' or source['sha256']!=pointer.get('sha256'):raise ValueError('不是这次跳过16个账号的78条原分配清单。')
    journal=stage.safe_child(root,root/'logs/material-distribution'/p['source_id']/(p['date']+'-eligible78.json'))
    actual=first.archive.checked_json(journal);receipt=first.upload.read_json(manifest.parent/'imported.json',{});progress=first.upload.read_json(journal.with_name(journal.stem+'-progress.json'),{})
    if (actual!=material or receipt.get('sha256')!=source['sha256'] or receipt.get('distribution_sha256')!=material['sha256']
            or progress.get('sha256')!=material['sha256'] or progress.get('complete') is not True
            or set(progress.get('done',[]))!={a+'/'+t for a,t in EXPECTED}):raise ValueError('78条素材尚未全部正式导入或分配指纹发生变化。')
    return manifest,source,journal,material


def request(root,source,journal,material):
    path=stage.safe_child(root,root/REQUEST);saved=first.upload.read_json(path,None)
    content=first.batch.preferences.content_policy(source['payload']['date'],saved.get('payload',{}).get('content_sha256') if saved else None)
    if not content or content['payload']['caption']!=first.batch.preferences.EVERYDAY_CAPTION or content['payload']['comment']!=first.batch.preferences.EVERYDAY_COMMENT:raise ValueError('原文案或评论版本缺失或变化，未自行改写。')
    if saved is None:
        p=dict(schema='eligible78-real-publication-request-v1',authorization=AUTH,stage_sha256=source['sha256'],distribution_sha256=material['sha256'],
               distribution_manifest=first.archive.relative(journal),material_date=source['payload']['date'],content_sha256=content['sha256'],
               ai_label=False,real_footage_confirmed=True,excluded_accounts=sorted(BLOCKED),targets=[list(p) for p in sorted(EXPECTED)],created_at=datetime.now(timezone.utc).isoformat())
        saved=dict(payload=p,sha256=first.batch.digest(p));first.upload.save_json(path,saved)
    p=saved.get('payload',{})
    if (saved.get('sha256')!=first.batch.digest(p) or p.get('schema')!='eligible78-real-publication-request-v1' or p.get('authorization')!=AUTH
            or p.get('stage_sha256')!=source['sha256'] or p.get('distribution_sha256')!=material['sha256'] or p.get('distribution_manifest')!=first.archive.relative(journal)
            or p.get('material_date')!=source['payload']['date'] or p.get('content_sha256')!=content['sha256'] or p.get('ai_label') is not False
            or p.get('real_footage_confirmed') is not True or p.get('excluded_accounts')!=sorted(BLOCKED) or p.get('targets')!=[list(p) for p in sorted(EXPECTED)]):raise ValueError('本次78条素材、标签、排除名单或正文评论授权变化。')
    return saved


def save_availability(root):
    path=stage.safe_child(root,root/AVAILABILITY);p=dict(schema='publication-account-exclusions-v1',effective_from='2026-11-17',excluded_accounts=sorted(BLOCKED),
        reason='user-confirmed-problem-accounts-and-fb23-paused',automatic_first=True,manual_last=True)
    desired=dict(payload=p,sha256=first.batch.digest(p))
    if first.upload.read_json(path,None)==desired:return
    if path.exists():
        backup=root/'backups'/('eligible78-availability-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True);shutil.copy2(path,backup/path.name)
    first.upload.save_json(path,desired)


def registered_ready(material,controller):
    config=first.upload.read_json(first.upload.CONFIG,{})
    ready=set()
    for row in material['payload']['assignments']:
        pair=row['account'],row['target'];entries=[e for e in config.get('targets',[]) if (e.get('account'),e.get('target'))==pair]
        if len(entries)==1 and first.batch.eligible(entries[0],True,date=today()):ready.add(pair)
        else:controller['pending'][pair[0]]='未取得唯一已核验目标；自动可用目标先发布，本目标留到最后检查。'
    for account in {a for a,t in ready}:
        if {(r['account'],r['target']) for r in material['payload']['assignments'] if r['account']==account}<=ready:controller['pending'].pop(account,None)
    return ready


def auto_register_pending(material,controller,control_path):
    config=first.upload.read_json(first.upload.CONFIG,{})
    for account in sorted(ACTIVE_NEW):
        entries=[e for e in config.get('targets',[]) if (e.get('account'),e.get('target'))==(account,'personal')]
        if len(entries)==1 and first.batch.eligible(entries[0],True,date=today()):continue
        try:
            print('自动检查待接入账号：',account,'；失败先跳过，不弹手动窗口。',flush=True)
            entry,proof=owners.discover_background(account)
            with first.locked(),patch.object(first,'DAY',today()):owned.register_one(account,entry,proof)
            controller['pending'].pop(account,None)
        except KeyboardInterrupt:raise
        except Exception as error:controller['pending'][account]=str(error).split('\n',1)[0] or type(error).__name__;print('先跳过：',account,controller['pending'][account],flush=True)
        first.upload.save_json(control_path,controller)


def bound_distribution(journal,material,pairs):
    def get(relative=None):
        if relative is not None and (first.upload.ROOT/relative).resolve()!=journal.resolve():raise ValueError('不选择其他素材分配批次。')
        current=first.archive.checked_json(journal)
        if current['sha256']!=material['sha256']:raise ValueError('原分配清单变化。')
        rows=[r for r in current['payload']['assignments'] if (r['account'],r['target']) in pairs]
        return journal,current,rows,set(first.upload.read_json(journal.with_name(journal.stem+'-progress.json'),{}).get('existing_video_records',[]))
    return get


def workflow_validate(path,value):
    queued.validate_queue(path,value,value['payload']['date']);p=value['payload']
    if (set(p.get('intended_accounts',[]))!=set(first.ALLOWED) or any(j['account'] in BLOCKED or (j['account'],j['target']) not in EXPECTED for j in p['jobs'])
            or p.get('distributed_scope')!=first.SCOPE or value.get('scheduled_priority_runner')!=first.workflow.VERSION
            or value.get('browser_launch_mode')!=first.normal.NORMAL_CHROME_VERSION or value.get('local_file_input_mode')!=first.local.VERSION):raise ValueError('78目标批次范围或后台发布模式异常。')


@contextlib.contextmanager
def wave_context(req,source,journal,material,wave,controller):
    pairs={tuple(p) for p in wave['pairs']};accounts={a for a,t in pairs};grant='eligible78-real-extra-'+req['sha256'][:12]+'-'+first.batch.digest(sorted(pairs))[:12]
    native=first.normal.launcher_for_jobs
    def launcher(jobs,date=None):
        factory=native(jobs,date=date)
        def launch(pw,entry):
            if (entry['account'],entry['target']) not in pairs:raise ValueError('浏览器目标不属于本批次。')
            if entry['account'] in controller.get('manual_skipped',[]):raise extra.SessionNotReady('用户本轮暂跳过此账号，未选择或发布视频。')
            if controller['modes'].get(entry['account'])=='foreground_minimized':
                with owners.guided.minimized_chrome(entry):return factory(pw,entry)
            return factory(pw,entry)
        return launch
    with patch.object(first,'DAY',wave['date']),patch.object(first,'MATERIAL_DAY',req['payload']['material_date']),patch.object(first,'ALLOWED',accounts), \
         patch.object(first,'SCOPE',wave['scope']),patch.object(first,'POINTER',wave['pointer']),patch.object(first,'distribution',side_effect=bound_distribution(journal,material,pairs)), \
         patch.object(first.workflow,'validate',side_effect=workflow_validate),patch.object(first.archive,'today_files',side_effect=browser.staged.protect_other_materials), \
         patch.object(first.normal.background,'mode',return_value='background'),patch.object(first.normal,'launcher_for_jobs',side_effect=launcher),patch.object(queued,'TARGET_PAIRS',pairs), \
         queued.installed(source['sha256'],req['payload']['material_date'],req['payload']['content_sha256'],req['sha256'],wave['scope'],wave['date'],grant):yield grant


def covered(controller):
    return {(j['account'],j['target']) for wave in controller['waves'] for j in first.archive.checked_json(first.upload.ROOT/'logs'/wave['manifest'])['payload']['jobs']}


def recover_waves(req,source,journal,material,controller,control_path):
    known={w['manifest'] for w in controller['waves']}
    for path in sorted((first.upload.ROOT/'logs').glob('frozen-material-*-*.json')):
        raw=first.upload.read_json(path,{});p=raw.get('payload',{});scope=p.get('distributed_scope','')
        if path.name in known or p.get('queue_id')!=req['sha256'] or not scope.startswith('eligible78-real-'+req['sha256'][:12]+'-'):continue
        pairs={tuple(p) for p in p.get('authorized_target_pairs',[])};tag=first.batch.digest(sorted(pairs))[:12]
        if not pairs or not pairs<=EXPECTED or scope!='eligible78-real-'+req['sha256'][:12]+'-'+tag:raise ValueError('中断留下的原发布范围异常。')
        wave=dict(pairs=[list(p) for p in sorted(pairs)],date=p['date'],scope=scope,pointer='eligible78-'+req['sha256'][:12]+'-'+tag+'.json',manifest=path.name,sha256=raw['sha256'])
        with wave_context(req,source,journal,material,wave,controller):first.validate(path,raw,material)
        controller['waves'].append(wave);known.add(path.name)
    first.upload.save_json(control_path,controller)


def add_wave(ready,req,source,journal,material,controller,control_path):
    pairs=ready-covered(controller)
    if not pairs:return
    tag=first.batch.digest(sorted(pairs))[:12];wave=dict(pairs=[list(p) for p in sorted(pairs)],date=today(),scope='eligible78-real-'+req['sha256'][:12]+'-'+tag,pointer='eligible78-'+req['sha256'][:12]+'-'+tag+'.json')
    try:
        with wave_context(req,source,journal,material,wave,controller),first.locked():path,value=first.freeze()
    except ValueError as error:
        if not str(error).startswith('没有可发布的今天新素材'):raise
        print('这些目标没有可新建的发布任务，保留成功及已提交记录：',str(error),flush=True)
        for a,t in pairs:controller['pending'][a]=str(error)
        first.upload.save_json(control_path,controller);return
    wave.update(manifest=path.name,sha256=value['sha256']);controller['waves'].append(wave);first.upload.save_json(control_path,controller)


def media_launcher(factory,jobs,path,value,deferred):
    by_pair={(j['account'],j['target']):j for j in jobs}
    def launch(pw,entry):
        context=None
        try:
            if entry['account'] in deferred:raise extra.SessionNotReady('该账号登录或安全验证本轮尚未就绪，先跳过：'+deferred[entry['account']])
            context=factory(pw,entry);page=context.pages[-1] if context.pages else context.new_page()
            extra.wait_session(page);first.upload.ensure_identity(page,entry);return context
        except Exception as error:
            if context is not None:context.close()
            message=str(error) or type(error).__name__
            if ACCOUNT_FAILURE.search(message):deferred.setdefault(entry['account'],message)
            job=by_pair.get((entry.get('account'),entry.get('target')))
            if job:
                state_path=first.upload.ROOT/'logs/publish_state.json';state=first.upload.read_json(state_path,{})
                report=first.upload.read_json(path.with_name(path.stem+'-results.json'),{})
                submitted=any(r.get('key')==job['key'] and r.get('video_status') in {'published','posting','needs_review','preparing'} for r in report.get('rows',[]))
                if job['key'] not in state and not submitted:
                    state[job['key']]=dict(account=job['account'],target=job['target'],url=job['url'],video=str(first.upload.inbox_for(entry)/job['filename']),status='failed_before_post',
                        uploader_version='2.47',ai_label_requested=False,created=datetime.now(timezone.utc).isoformat(),error=message,failure_stage='open_target_profile',before_media_launch_failure=True,
                        source_frozen_manifest=path.name,source_frozen_sha256=value['sha256']);first.upload.save_json(state_path,state)
            raise
        except BaseException:
            if context is not None:context.close()
            raise
    return launch


def run_phase(phase,req,source,journal,material,wave,controller,deferred):
    with wave_context(req,source,journal,material,wave,controller) as grant:
        path=first.upload.ROOT/'logs'/wave['manifest'];value=first.archive.checked_json(path)
        if value['sha256']!=wave['sha256']:raise ValueError('原发布清单指纹变化。')
        first.validate(path,value,material);jobs=value['payload']['jobs'];pages={(j['account'],j['target']) for j in jobs if j['target']!='personal'};personal=first.personals.ensure_personal;finder=first.priority.actual.make_finder
        def bounded_finder(*args,**kwargs):kwargs.update(interactive=False,total_timeout_ms=60000);return finder(*args,**kwargs)
        with first.priority.daily.keep_awake(),first.personals.scoped(first.ALLOWED),first.numeric.scoped(pages),first.editor.installed(), \
             patch.object(first.numeric,'ensure',side_effect=browser.staged.page_identity),patch.object(first.personals,'ensure_personal',side_effect=lambda page,entry:extra.ensure_background_identity(personal,page,entry)), \
             patch.object(first.upload,'launch_context',media_launcher(first.normal.launcher_for_jobs(jobs,date=wave['date']),jobs,path,value,deferred)), \
             patch.object(first.priority.actual,'make_finder',side_effect=bounded_finder),first.capture.installed(path,value):
            if phase=='videos':
                with first.locked():first.recover_own(path,value)
                if datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):print('等待新素材及统一文案写入稳定，约一分钟后自动开始。',flush=True)
                while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
                first.batch.run(path,defer_comments=True,resume=True)
            elif phase=='retry':first.priority.retry.run(path)
            elif phase=='reconcile':
                with first.locked():first.reconcile(path,value)
            elif phase=='comments':
                rows=[]
                with patch.object(first.priority.daily,'find_published',first.priority.actual.make_finder(jobs,True,interactive=False)):
                    first.priority.daily.backfill(value,None,only_keys={j['key'] for j in jobs},rows=rows,future_only=True,reconcile_pending=True,reporter=lambda *_:first.priority.comment_report(path,value,rows))
            elif phase=='comment_retry':first.priority.comment_retry.run(path,reporter=lambda m,r,o:first.priority.comment_report(path,value,r))
            elif phase=='extra':
                pointer=first.upload.read_json(first.upload.ROOT/'logs'/(grant+'.json'),{});saved=first.upload.read_json(first.upload.ROOT/'logs'/pointer.get('manifest','missing'),{}) if pointer else {}
                check=extra.checked
                def check_allowed(job,state,claims,grant_value):
                    if job['account'] in controller.get('manual_skipped',[]):return None,'用户本轮先不发此账号，保留原记录'
                    return check(job,state,claims,grant_value)
                with patch.object(extra,'checked',side_effect=check_allowed),patch.object(extra,'DAY',saved.get('payload',{}).get('date') or today()),patch.object(extra,'GRANT',grant), \
                     patch.object(extra,'require_day',side_effect=lambda:request(first.upload.ROOT,source,journal,material)), \
                     patch.object(extra,'source',return_value=(copy.deepcopy(jobs),[dict(manifest=path.name,sha256=value['sha256'])],value['payload'])):extra.execute()
            else:raise ValueError('未知发布阶段。')


def report(req,material,controller,control_path):
    state=first.upload.read_json(first.upload.ROOT/'logs/publish_state.json',{});jobs={};issues={}
    for wave in controller['waves']:
        value=first.archive.checked_json(first.upload.ROOT/'logs'/wave['manifest']);jobs.update({(j['account'],j['target']):j for j in value['payload']['jobs']})
        issues.update({(r['account'],r['target']):r.get('reason','') for r in value.get('issues',[])})
    rows=[]
    for assignment in material['payload']['assignments']:
        pair=assignment['account'],assignment['target'];job=jobs.get(pair);record=state.get(job['key'],{}) if job else {}
        rows.append(dict(account=pair[0],target=pair[1],filename=assignment['files'][-1]['destination_name'],key=job['key'] if job else None,video_status=record.get('status','not_started'),
                         comment_status=record.get('comment_status','not_started'),reason=record.get('error') or record.get('comment_error') or issues.get(pair) or controller['pending'].get(pair[0],'')))
    controller.update(rows=rows,complete=all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows),updated_at=datetime.now(timezone.utc).isoformat())
    first.upload.save_json(control_path,controller)
    print('本批78目标：视频成功',sum(r['video_status']=='published' for r in rows),'；发布前失败',sum(r['video_status']=='failed_before_post' for r in rows),
          '；待核实',sum(r['video_status'] in {'preparing','posting','needs_review'} for r in rows),'；未开始',sum(r['video_status']=='not_started' for r in rows),'；评论成功',sum(r['comment_status'] in {'sent','already_present'} for r in rows),flush=True)
    lines=['78目标实拍视频及评论：AI关闭，自动可用先处理，人工事项留到最后。','停发账号：'+','.join(sorted(BLOCKED))]
    for row in rows:
        line=row['account']+'/'+row['target']+' 视频='+row['video_status']+' 评论='+row['comment_status']+(' 原因='+row['reason'] if row['reason'] else '')
        lines.append(line);print(line,flush=True)
    output=control_path.with_suffix('.txt');output.write_text('\n'.join(lines),encoding='utf-8-sig');print('完整视频及评论清单：',output,flush=True)
    return rows


def manual_existing(entry):
    from playwright.sync_api import sync_playwright
    context=None
    with sync_playwright() as pw:
        try:
            context,page=owners.guided.open_for_check(pw,entry,'foreground')
            while True:
                try:extra.wait_session(page);first.upload.ensure_identity(page,entry);return 'foreground_minimized'
                except KeyboardInterrupt:raise
                except Exception as error:
                    print('最后人工检查：',entry['account'],entry['target'],str(error).split('\n',1)[0],flush=True)
                    answer=owners.guided.prompt('只处理登录/验证或网络，不要手动上传；完成后回车核验，R重开目标，S先不发此账号，Q暂停：')
                    if answer=='S':return None
                    if answer=='R':
                        try:page.goto(first.upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000)
                        except Exception:pass
        finally:
            if context is not None:context.close()


def execute(root,real_footage_confirmed=True):
    if real_footage_confirmed is not True:raise ValueError('本批尚未明确确认实拍及AI关闭。')
    root=Path(root).resolve()
    if root!=first.upload.ROOT.resolve():raise ValueError('请在原上传目录运行。')
    first.workflow.require_versions()
    live=current_workers(root)
    if live:raise ValueError('仍有发布、分配或登录检查任务，PID：'+','.join(str(r['pid']) for r in live)+'；请等原任务结束后重跑本入口，未终止进程或上传视频。')
    browser.staged.lock_recovery.recover_locks(root)
    with patch.object(first.batch,'excluded_accounts',side_effect=exclusions),patch.object(owned,'reservation',side_effect=active_reservation):
        _,source,journal,material=allocation(root)
        with first.locked():req=request(root,source,journal,material);save_availability(root)
        path=root/'logs'/('eligible78-real-publication-'+req['sha256'][:16]+'.json');controller=first.upload.read_json(path,dict(request_sha256=req['sha256'],waves=[],modes={},pending={}))
        if controller.get('request_sha256')!=req['sha256'] or not isinstance(controller.get('waves'),list):raise ValueError('78目标原发布进度校验失败。')
        recover_waves(req,source,journal,material,controller,path)
        deferred={};print('本次78目标：AI关闭；先自动发布全部可用视频，再安全补发和评论，最后才提示人工检查。fb23及另外15个问题账号均停发。',flush=True)
        ready=registered_ready(material,controller);add_wave(ready,req,source,journal,material,controller,path)
        for wave in controller['waves']:run_phase('videos',req,source,journal,material,wave,controller,deferred)
        before=len(controller['waves']);auto_register_pending(material,controller,path);ready=registered_ready(material,controller);add_wave(ready,req,source,journal,material,controller,path)
        for wave in controller['waves'][before:]:run_phase('videos',req,source,journal,material,wave,controller,deferred)
        for phase in ('retry','reconcile','comments','comment_retry'):
            for wave in controller['waves']:run_phase(phase,req,source,journal,material,wave,controller,deferred)
        rows=report(req,material,controller,path);pending=[r for r in rows if r['video_status']!='published' or r['comment_status'] not in {'sent','already_present'}]
        if not pending:return 0
        print('自动发布及安全补发/补评已全部处理完。以下账号留到最后人工检查：',','.join(sorted({r['account'] for r in pending})),flush=True)
        answer=owners.guided.prompt('回车集中检查这些账号并继续；S保留问题账号本轮先不发并结束，Q暂停：')
        if answer=='S':return 3
        controller['manual_skipped']=[]
        config=first.upload.read_json(first.upload.CONFIG,{})
        pages={(a,t) for a,t in EXPECTED if t!='personal'}
        with first.personals.scoped(ALLOWED),first.numeric.scoped(pages),patch.object(first.numeric,'ensure',side_effect=browser.staged.page_identity):
            for account in sorted({r['account'] for r in pending}):
                try:
                    entries=[e for e in config.get('targets',[]) if e.get('account')==account and (e.get('account'),e.get('target')) in EXPECTED]
                    eligible=[e for e in entries if first.batch.eligible(e,True,date=today())]
                    if account in ACTIVE_NEW and not eligible:
                        found=owners.discover_manual(account)
                        if found is None:controller['manual_skipped'].append(account);continue
                        entry,proof,mode=found
                        with first.locked(),patch.object(first,'DAY',today()):owned.register_one(account,entry,proof)
                    else:
                        pairs={(r['account'],r['target']) for r in pending};entry=next((e for e in eligible if (e['account'],e['target']) in pairs),None)
                        if entry is None:controller['pending'][account]='没有可核对的原登记目标，未猜测身份';controller['manual_skipped'].append(account);continue
                        mode=manual_existing(entry)
                        if mode is None:controller['manual_skipped'].append(account);continue
                    controller['modes'][account]=mode;controller['pending'].pop(account,None);deferred.pop(account,None);first.upload.save_json(path,controller)
                except KeyboardInterrupt:raise
                except Exception as error:
                    controller['manual_skipped'].append(account);controller['pending'][account]=str(error).split('\n',1)[0] or type(error).__name__;print('保留待处理，继续下一账号：',account,controller['pending'][account],flush=True)
        ready=registered_ready(material,controller);add_wave(ready,req,source,journal,material,controller,path)
        for phase in ('videos','retry','extra','reconcile','comments','comment_retry'):
            for wave in controller['waves']:run_phase(phase,req,source,journal,material,wave,controller,deferred)
        report(req,material,controller,path);return 0 if controller['complete'] else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的新PowerShell窗口运行。')
        raise SystemExit(execute(Path(sys.argv[1]),True))
    except KeyboardInterrupt:print('已暂停，视频/评论及补发进度均保留；重跑同一入口继续，不重复已提交内容。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
