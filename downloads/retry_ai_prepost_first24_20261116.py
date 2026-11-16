"""One durable extra chance for the exact AI=True first24 batch, never after submission."""
import contextlib,copy,re,shutil,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    sys.path.insert(0,str(Path(__file__).resolve().parent))
import resume_nov13_two_waves_on_nov14 as resume
first=resume.first
DAY='2026-11-16'
GRANT='nov16-ai-first24-prepost-extra-once-v1'



class SessionNotReady(RuntimeError):pass


def require_day():
    if datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()!=DAY:raise ValueError('本指令仅用于11月16日处理已授权原批次的明确发布前失败视频。')


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
    raise ValueError('本AI补发模块仅由已核验的当批AI发布入口绑定原清单后运行。')


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
                       publication_preferences_sha256=first.batch.preferences.load(DAY)['sha256'],excluded_accounts=sorted(first.batch.excluded_accounts(DAY)),
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
    if not resume.bound_record(job,row) or row.get('uploader_version')!='2.47' or row.get('ai_label_requested') is not True:raise ValueError('原失败记录身份或AI标签开启记录异常。')
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
    print('仅补发所选原清单中明确发布前失败的视频；保留所有成功和已提交记录。原记录备份：',backup,flush=True)
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
                                         status='failed_before_post',ai_label_requested=True,uploader_version='2.47',repair_authorization=GRANT,repair_previous_attempt=original)
                        claims['jobs'][job['key']]=dict(phase='reserved',original=original,replacement=copy.deepcopy(replacement))
                        first.upload.save_json(claims_path,claims);state[job['key']]=replacement;first.upload.save_json(state_path,state)
                        print('补发原视频：',job['account'],job['target'],job['filename'],flush=True)
                        first.upload.run_entry(dict(entry,_authorized_comment_text=value['payload']['comment_text']),state,state_path,True,filename=job['filename'],expected_job_key=job['key'],
                                               ai_label_override=True,retry_before_post=True,preserve_old_review_for_exact_job=True,defer_comments=True)
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
    print('原清单补发阶段结束；仅本许可实际新成功的视频进入评论，已成功和待核实视频未重发。',flush=True)
    return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in final) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if first.upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已暂停，保留补发进度；重跑同一命令继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
