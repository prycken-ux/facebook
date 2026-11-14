"""One explicit additional attempt of exactly fifteen Nov13 pre-Post failures."""
import contextlib,copy,re,shutil,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import resume_nov13_two_waves_on_nov14 as resume
first=resume.first
DAY='2026-11-14'
GRANT='nov13-fifteen-prepost-explicit-retry-on-nov14-v1'
SPEC={('fb09', 'page01'): ('2026-06-01_7646361870961528078.mp4', '084964c6b4a1'),
 ('fb09', 'page02'): ('2026-06-04_7647476224364793102.mp4', '74a6d158a221'),
 ('fb09', 'page03'): ('2026-06-05_7647849639332302093.mp4', '8fb13eb496d2'),
 ('fb09', 'page04'): ('2026-06-08_7648964755184553229.mp4', '12a9e2b79e13'),
 ('fb09', 'page05'): ('2026-06-09_7649207590668324110.mp4', 'c5e310489c02'),
 ('fb09', 'page06'): ('2026-06-09_7649343819267280141.mp4', 'b0353a0d65bd'),
 ('fb09', 'page07'): ('2026-06-10_7649702042637798670.mp4', 'be2028b7eb97'),
 ('fb09', 'page08'): ('2026-06-11_7650073284159065357.mp4', '070cb72f5a37'),
 ('fb09', 'page09'): ('2026-06-12_7650445357196774669.mp4', '84a46d702321'),
 ('fb09', 'page10'): ('2026-06-13_7650681507262041358.mp4', 'dd6ec366b234'),
 ('fb09', 'personal'): ('2026-05-29_7645254896639282445.mp4', 'e6fd6109ada1'),
 ('fb17', 'personal'): ('2026-06-24_7654892438909111565.mp4', '97a8dc41f936'),
 ('fb37', 'personal'): ('2026-07-03_7658104458777316622.mp4', 'f1ddae2409a9'),
 ('fb38', 'personal'): ('2026-07-03_7658234008794434829.mp4', '0ea0c138295c'),
 ('fb55', 'personal'): ('2026-07-10_7660834462267133197.mp4', 'f500f19c0ede')}


class SessionNotReady(RuntimeError):pass


def require_day():
    if datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()!=DAY:raise ValueError('本指令仅用于11月14日补发指定15条11月13日发布前失败原视频。')


def wait_session(page,timeout_ms=15000):
    deadline=time.monotonic()+timeout_ms/1000
    announced=False
    while True:
        first.upload.checkpoint(page);first.upload.require_no_advanced_protection(page)
        try:people={c['value'] for c in page.context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and c.get('value')}
        except Exception:raise SessionNotReady('无法读取本机登录会话；未选择视频。') from None
        if len(people)>1 or (people and not next(iter(people)).isdecimal()):raise SessionNotReady('登录者身份不唯一或无效；未选择视频。')
        if len(people)==1:return first.numeric.picker.login_marker(page)
        if time.monotonic()>=deadline:raise SessionNotReady('等待15秒后仍缺少唯一登录者；保留原失败记录，请在该编号原登录窗口确认登录。')
        if not announced:print('等待本机已保存登录会话加载，最多15秒；不会跳过身份核验。',flush=True);announced=True
        page.wait_for_timeout(200)


def ensure_background_identity(previous,page,entry):
    if entry.get('type')=='personal':
        try:first.upload.personal_actor_fingerprint(page,entry)
        except first.upload.PageActorActive:
            marker=first.numeric.picker.login_marker(page)
            first.numeric.picker.switch_personal_from_picker(page,entry,timeout_ms=15000)
            if first.numeric.picker.login_marker(page)!=marker:raise RuntimeError('切回本人期间登录者变化，未选择视频。')
    return previous(page,entry)


def source():
    _,parent,material_path,material,_,_=resume.source()
    pointer=first.upload.read_json(first.upload.ROOT/'logs'/resume.FIRST_POINTER,{})
    controller=first.upload.read_json(first.upload.ROOT/'logs'/resume.CONTROL,{})
    p=controller.get('payload',{})
    if (controller.get('sha256')!=first.batch.digest(p) or p.get('date')!=DAY
            or p.get('distribution_sha256')!=material['sha256'] or p.get('distribution_manifest')!=first.archive.relative(material_path)
            or not isinstance(controller.get('waves'),list)):raise ValueError('没有有效的11月14日跨日续跑控制记录。')
    rows=[dict(manifest=pointer.get('manifest'),sha256=pointer.get('sha256'),first=True)]+[dict(w,first=False) for w in controller['waves']]
    jobs={};bindings=[];template=None
    for saved in rows:
        name=saved.get('manifest','')
        if not isinstance(name,str) or not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json',name):raise ValueError('原续跑清单名称异常。')
        path=first.upload.ROOT/'logs'/name;value=first.archive.checked_json(path);payload=value['payload']
        first.priority.validate(path,value,DAY)
        if (saved.get('sha256')!=value['sha256'] or payload.get('distribution_sha256')!=material['sha256']
                or payload.get('distribution_manifest')!=first.archive.relative(material_path)
                or payload.get('resume_source_date')!=resume.SOURCE_DAY
                or payload.get('resume_source_first_sha256')!=parent['sha256']):raise ValueError('原续跑清单与11月13日原素材不一致。')
        if saved['first']:
            if payload.get('distributed_scope')!=resume.FIRST_SCOPE:raise ValueError('原第一批范围不符。')
        else:
            resume.original.reservation()
            intended=set(payload.get('intended_accounts',[]))
            if not intended or not intended<=resume.original.NEW or payload.get('distributed_scope')!=resume.SECOND_SCOPE+'-'+first.batch.digest(sorted(intended))[:12]:raise ValueError('原第二批新账号来源异常。')
        if template and any(payload.get(k)!=template.get(k) for k in ('publication_content_sha256','comment_text')):raise ValueError('两批原文案不一致。')
        template=payload;bindings.append(dict(manifest=name,sha256=value['sha256']))
        for job in payload['jobs']:
            pair=job['account'],job['target']
            if pair not in SPEC:continue
            filename,prefix=SPEC[pair]
            if job['filename']!=filename or not job['key'].startswith(prefix):raise ValueError('账号、文件名或任务指纹与日志中15条失败视频不一致。')
            assignments=[r for r in material['payload']['assignments'] if (r.get('account'),r.get('target'))==pair]
            if len(assignments)!=1:raise ValueError('原分配目标不唯一。')
            file=assignments[0]['files'][-1]
            if (file.get('destination_name'),file.get('sha256'),file.get('size'))!=(job['filename'],job['video_sha256'],job['video_size']):raise ValueError('补发不是原分配视频。')
            if pair in jobs and jobs[pair]!=job:raise ValueError('同一目标有多个原任务。')
            jobs[pair]=copy.deepcopy(job)
    if set(jobs)!=set(SPEC):raise ValueError('15条原失败视频未能全部唯一匹配，未猜选其他素材。')
    return sorted(jobs.values(),key=lambda j:(j['account'],j['target']!='personal',j['target'])),bindings,template


def prepare():
    jobs,bindings,template=source();pointer=first.upload.ROOT/'logs'/(GRANT+'.json')
    def validate(path,value):
        first.priority.validate(path,value,DAY);p=value['payload']
        if (p.get('explicit_prepost_grant')!=GRANT or p.get('jobs')!=jobs or p.get('source_bindings')!=bindings
                or p.get('comment_text')!=template['comment_text'] or p.get('publication_content_sha256')!=template['publication_content_sha256']
                or not isinstance(p.get('authorized_state_sha256'),dict)):raise ValueError('本次补发清单来源或范围变化。')
    saved=first.upload.read_json(pointer,None)
    if saved:
        name=saved.get('manifest','')
        if not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json',name):raise ValueError('补发指针异常。')
        path=first.upload.ROOT/'logs'/name;value=first.archive.checked_json(path);validate(path,value)
        if saved.get('sha256')!=value['sha256']:raise ValueError('补发指针指纹异常。')
        return path,value
    orphan=[]
    for path in (first.upload.ROOT/'logs').glob('frozen-material-'+DAY+'-*.json'):
        value=first.upload.read_json(path,{})
        if value.get('payload',{}).get('explicit_prepost_grant')==GRANT:validate(path,value);orphan.append((path,value))
    if len(orphan)>1:raise ValueError('同一补发许可存在多个清单。')
    if orphan:path,value=orphan[0]
    else:
        now=datetime.now(timezone.utc);state=first.upload.read_json(first.upload.ROOT/'logs/publish_state.json',{})
        payload=copy.deepcopy(template)
        payload.update(date=DAY,start=now.isoformat(),requested_start=now.isoformat(),jobs=jobs,explicit_prepost_grant=GRANT,
                       source_bindings=bindings,authorized_state_sha256={j['key']:first.batch.digest(state.get(j['key'])) for j in jobs})
        for field in ('distributed_scope','intended_accounts','old_material_files'):payload.pop(field,None)
        value=dict(payload=payload,sha256=first.batch.digest(payload),created_at=now.isoformat(),issues=[],workflow='future-video-comments-v1',
                   auto_retry_policy=first.priority.retry.POLICY,comment_timing=first.priority.TIMING,priority_workflow=first.priority.PRIORITY_WORKFLOW_VERSION,report_format='text')
        path=first.upload.ROOT/'logs'/('frozen-material-'+DAY+'-'+value['sha256'][:16]+'.json');validate(path,value);first.upload.save_json(path,value)
    first.upload.save_json(pointer,dict(manifest=path.name,sha256=value['sha256']));return path,value


def checked(job,state,claims,value):
    row=state.get(job['key']);claim=claims['jobs'].get(job['key'])
    if not isinstance(row,dict) or row.get('status')!='failed_before_post' or resume.has_submission(row):return None,'已有成功、提交线索或结果不明，保留不重发'
    if claim:
        if claim.get('phase')=='consumed':return None,'此原视频已使用本次补发机会'
        if row not in (claim.get('original'),claim.get('replacement')):return None,'许可后任务已有变化，保留'
    elif (first.batch.digest(row)!=value['payload']['authorized_state_sha256'].get(job['key'])
          or row.get('repair_authorization')==GRANT):return None,'授权后原记录变化，或许可记录缺失，保留'
    if not resume.bound_record(job,row) or row.get('uploader_version')!='2.47' or row.get('ai_label_requested') is not False:raise ValueError('原失败记录身份或实拍标记异常。')
    if not claim and (row.get('source_frozen_manifest'),row.get('source_frozen_sha256')) not in {(p['manifest'],p['sha256']) for p in value['payload']['source_bindings']}:raise ValueError('失败记录不是原跨日续跑清单的任务。')
    if any(r.get('account')==job['account'] and r.get('status') in {'preparing','posting'} for r in state.values()):raise ValueError('该账号仍有进行中任务，未关闭浏览器。')
    entry=first.batch.validate_job(job,date=DAY);video=first.upload.inbox_for(entry)/job['filename']
    if first.archive.info(video)!=dict(size=job['video_size'],sha256=job['video_sha256']):raise ValueError('原视频指纹变化，未替换其他素材。')
    selected=first.upload.named_job(entry,{k:v for k,v in state.items() if k!=job['key']},job['filename'])
    if not selected or selected[0]!=job['key'] or selected[3]!=job['caption_text']:raise ValueError('原视频或文案不一致。')
    return dict(entry,enabled=True,auto_switch_personal=True),'ready'


def execute():
    require_day()
    with patch.object(first,'DAY',DAY):return execute_current_day()


def execute_current_day():
    require_day();first.workflow.require_versions();state_path=first.upload.ROOT/'logs/publish_state.json'
    with first.locked():
        path,value=prepare();jobs=value['payload']['jobs'];claims_path=first.upload.ROOT/'logs'/(GRANT+'-claims.json')
        claims=first.upload.read_json(claims_path,dict(grant=GRANT,sha256=value['sha256'],jobs={}))
        if claims.get('grant')!=GRANT or claims.get('sha256')!=value['sha256'] or not isinstance(claims.get('jobs'),dict):raise ValueError('补发许可账本异常。')
        report_path=path.with_name(path.stem+'-results.json');report=first.upload.read_json(report_path,dict(manifest=path.name,attempts=[]))
        if report.get('manifest')!=path.name or not isinstance(report.get('attempts'),list):raise ValueError('补发报告异常。')
        if report['attempts'] and not claims_path.exists():raise ValueError('已有执行报告但许可账本缺失，未重新发放机会。')
        first.recover_own(path,value)
        report=first.upload.read_json(report_path,report)
        current=first.upload.read_json(state_path,{})
        for job in jobs:
            claim=claims['jobs'].get(job['key']);row=current.get(job['key'],{})
            if (claim and claim.get('phase')!='consumed' and row not in (claim.get('original'),claim.get('replacement'))
                    and row.get('source_frozen_manifest')==path.name and row.get('source_frozen_sha256')==value['sha256'] and resume.bound_record(job,row)):
                claim['phase']='consumed'
        attempts=report['attempts'];backup=first.upload.ROOT/'backups'/(GRANT+'-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
        for file in (state_path,claims_path,path):
            if file.is_file():shutil.copy2(file,backup/file.name)
        first.upload.save_json(claims_path,claims)
    print('仅补发指定15条明确发布前失败原视频；成功和18条旧待核实视频保持原样。原记录备份：',backup,flush=True)
    print('使用无窗口后台Chrome；新补发成功的视频按原文案评论。登录/安全验证不会绕过。',flush=True)
    launcher=first.normal.launcher_for_jobs(jobs,date=DAY)
    def ready_launcher(pw,entry):
        context=launcher(pw,entry)
        try:wait_session(context.pages[0] if context.pages else context.new_page());return context
        except BaseException:context.close();raise
    pages={(j['account'],j['target']) for j in jobs if j['target']!='personal'};numeric_ensure=first.numeric.ensure;blocked=set()
    with first.priority.daily.keep_awake(),first.personals.scoped({j['account'] for j in jobs}),first.numeric.scoped(pages),first.editor.installed(), \
         patch.object(first.numeric,'ensure',side_effect=lambda page,entry:numeric_ensure(page,entry,interactive=False)), \
         patch.object(first.upload,'launch_context',side_effect=ready_launcher),patch.object(first.normal.background,'mode',return_value='background'),first.capture.installed(path,value):
        previous_identity=first.upload.ensure_identity
        with patch.object(first.upload,'ensure_identity',side_effect=lambda page,entry:ensure_background_identity(previous_identity,page,entry)):
            for job in jobs:
                require_day();replacement=None;attempt=dict(key=job['key'],account=job['account'],target=job['target'],started_at=datetime.now(timezone.utc).isoformat())
                with first.locked():
                    try:
                        state=first.upload.read_json(state_path,{});entry,status=checked(job,state,claims,value)
                        if status!='ready':attempt.update(action='existing_record',error=status);continue
                        if job['account'] in blocked:raise SessionNotReady('此编号本轮登录会话尚未就绪，保留其余目标，不重复打开同一资料。')
                        first.close_selected_window(entry['account'])
                        if first.upload.read_json(state_path,{})!=state:raise ValueError('关闭窗口期间进度变化，未覆盖。')
                        original=copy.deepcopy(claims['jobs'].get(job['key'],{}).get('original',state[job['key']]))
                        replacement=dict(account=job['account'],target=job['target'],url=job['url'],video=str(first.upload.inbox_for(entry)/job['filename']),
                                         status='failed_before_post',ai_label_requested=False,uploader_version='2.47',repair_authorization=GRANT,repair_previous_attempt=original)
                        claims['jobs'][job['key']]=dict(phase='reserved',original=original,replacement=copy.deepcopy(replacement))
                        first.upload.save_json(claims_path,claims);state[job['key']]=replacement;first.upload.save_json(state_path,state)
                        print('补发原视频：',job['account'],job['target'],job['filename'],flush=True)
                        first.upload.run_entry(dict(entry,_authorized_comment_text=value['payload']['comment_text']),state,state_path,True,filename=job['filename'],expected_job_key=job['key'],
                                               ai_label_override=False,retry_before_post=True,preserve_old_review_for_exact_job=True,defer_comments=True)
                        attempt['action']='finished'
                    except KeyboardInterrupt:attempt.update(action='interrupted',error='已暂停，保留记录');raise
                    except Exception as error:
                        if isinstance(error,SessionNotReady) or '登录或安全验证' in str(error):blocked.add(job['account'])
                        attempt.update(action='manual_required',error=str(error) or type(error).__name__)
                        print('此目标保留结果，继续其他指定视频：',job['account'],job['target'],attempt['error'].split('\n',1)[0],flush=True)
                    finally:
                        if replacement is not None:
                            current=first.upload.read_json(state_path,{})
                            if current.get(job['key'])==replacement:
                                current[job['key']]=copy.deepcopy(claims['jobs'][job['key']]['original']);first.upload.save_json(state_path,current)
                                claims['jobs'][job['key']]['phase']='not_started'
                            else:claims['jobs'][job['key']]['phase']='consumed'
                            first.upload.save_json(claims_path,claims)
                        attempts.append(attempt);first.batch.results(path,value,attempts,None)
            # Read-only reconciliation is limited to this grant's new attempts.
            with first.locked():first.reconcile(path,value)
            owned={j['key'] for j in jobs if claims['jobs'].get(j['key'],{}).get('phase')=='consumed'}
            rows=[]
            if owned:
                with patch.object(first.priority.daily,'find_published',first.priority.actual.make_finder(jobs,True,interactive=False)):
                    first.priority.daily.backfill(value,None,only_keys=owned,rows=rows,future_only=True,reconcile_pending=True,reporter=lambda *_:first.priority.comment_report(path,value,rows))
                candidates=first.priority.comment_retry.candidates
                def owned_candidates(candidate,*args):
                    view=copy.deepcopy(candidate);view['payload']['jobs']=[j for j in candidate['payload']['jobs'] if j['key'] in owned]
                    return candidates(view,*args)
                with patch.object(first.priority.comment_retry,'candidates',side_effect=owned_candidates):
                    first.priority.comment_retry.run(path,reporter=lambda m,r,o:first.priority.comment_report(path,value,r))
    final=first.batch.results(path,value,attempts,None,final=True)
    print('本次仅处理日志指定15条发布前失败原视频及其新评论；46个未接入目标和18条旧待核实视频未重发。',flush=True)
    return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in final) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if first.upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已暂停，保留补发进度；重跑同一命令继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
