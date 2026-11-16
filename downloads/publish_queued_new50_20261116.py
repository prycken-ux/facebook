"""Run the authorized real50 material queue after the first24 AI batch closes."""
import contextlib,copy,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parent))
import prepare_new50_queue_20261116 as prepared
import queued_new50_workflow as queued
import retry_queued_new50_beforepost as extra
import publish_unplanned_fortysix_nov14 as owners
import finish_first24_nov14_on_nov16 as browser
first=queued.first
owned=prepared.owned
stage=prepared.stage
workers=prepared.sibling('material_distribution_worker_check.py')
VERSION='1.0-queued-real-new50-with-actual-dates'


def today():return datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()


def first24_finished(root,queue):
    expected=queue['payload'].get('first24_stage_sha256')
    if not expected:return True
    pointer=first.upload.read_json(root/'logs/nov16-new-first24-ai-disclosure-on-publication.json',{})
    name=pointer.get('manifest','')
    if not re.fullmatch(r'frozen-material-\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json',name):return False
    path=root/'logs'/name;value=first.archive.checked_json(path)
    if value['sha256']!=pointer.get('sha256') or value['payload'].get('stage_sha256')!=expected or not value['payload'].get('jobs'):return False
    report=first.upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if report.get('manifest')!=path.name or not {j['key'] for j in value['payload']['jobs']}<={a['key'] for a in report.get('attempts',[])}:return False
    # Completion of this RUN, not fabricated success: failures/unknown receipts
    # remain recorded. The caller separately proves all publisher processes exit.
    return True


def validate_new_generation(path,value):
    owned.reservation();queued.validate_queue(path,value,value['payload']['date']);p=value['payload']
    intended=set(p.get('intended_accounts',[]))
    if (not intended or not intended<=owned.NEW or intended!=set(first.ALLOWED) or any(j['target']!='personal' or j['account'] not in intended for j in p['jobs'])
            or p.get('distributed_scope')!=first.SCOPE or value.get('scheduled_priority_runner')!=first.workflow.VERSION
            or value.get('browser_launch_mode')!=first.normal.NORMAL_CHROME_VERSION or value.get('local_file_input_mode')!=first.local.VERSION):raise ValueError('仅允许这次新50代次的已核验个人目标，不恢复旧删除账号。')


def initial_ready(controller,controller_path):
    ready=set();pending={}
    for account in sorted(owned.NEW):
        config=first.upload.read_json(first.upload.CONFIG,{})
        entries=[e for e in config['targets'] if (e.get('account'),e.get('target'))==(account,'personal')]
        if len(entries)==1 and first.batch.eligible(entries[0],True,date=today()):ready.add(account);continue
        print('核对新增账号：',account,'；自动读取本人名称和数字身份，不要求手填名称。',flush=True)
        try:
            entry,proof=owners.discover_background(account)
            with first.locked(),patch.object(first,'DAY',today()):owned.register_one(account,entry,proof)
            ready.add(account)
        except KeyboardInterrupt:raise
        except Exception as error:pending[account]=owners.guided.brief(error)['message'];print('此账号先保留：',account,pending[account],flush=True)
    controller['pending']=pending;first.upload.save_json(controller_path,controller)
    return ready


def bound_distribution(journal,material):
    def get(relative=None):
        if relative is not None and (first.upload.ROOT/relative).resolve()!=journal.resolve():raise ValueError('新50队列不选择其他素材批次。')
        value=first.archive.checked_json(journal);p=value['payload']
        if value['sha256']!=material['sha256'] or p.get('target_scope')!='reserved50':raise ValueError('新50正式素材分配变化。')
        rows=[r for r in p['assignments'] if r['account'] in first.ALLOWED]
        progress=first.upload.read_json(journal.with_name(journal.stem+'-progress.json'),{})
        if progress.get('sha256')!=value['sha256'] or not {r['account']+'/'+r['target'] for r in rows}<=set(progress.get('done',[])):raise ValueError('新增50账号素材尚未全部导入。')
        return journal,value,rows,set(progress.get('existing_video_records',[]))
    return get


@contextlib.contextmanager
def wave_context(queue,source,journal,material,wave,modes):
    stamp=wave['date'];accounts=set(wave['accounts']);grant='new50-real-extra-'+queue['sha256'][:12]+'-'+first.batch.digest(sorted(accounts))[:12]
    launcher=first.normal.launcher_for_jobs
    def launch_jobs(jobs,date=None):
        native=launcher(jobs,date=date)
        def launch(pw,entry):
            if entry['account'] not in accounts:raise ValueError('不属于新增账号本批清单。')
            if modes.get(entry['account'])=='foreground_minimized':
                with owners.guided.minimized_chrome(entry):return native(pw,entry)
            return native(pw,entry)
        return launch
    with patch.object(first,'DAY',stamp),patch.object(first,'MATERIAL_DAY',queue['payload']['material_date']),patch.object(first,'ALLOWED',accounts), \
         patch.object(first,'SCOPE',wave['scope']),patch.object(first,'POINTER',wave['pointer']),patch.object(first,'distribution',side_effect=bound_distribution(journal,material)), \
         patch.object(first.workflow,'validate',side_effect=validate_new_generation),patch.object(first.archive,'today_files',side_effect=browser.staged.protect_other_materials), \
         patch.object(first.normal.background,'mode',return_value='background'),patch.object(first.normal,'launcher_for_jobs',side_effect=launch_jobs), \
         queued.installed(source['sha256'],queue['payload']['material_date'],queue['payload']['content_sha256'],queue['sha256'],wave['scope'],stamp,grant):
        yield grant


def make_wave(accounts,queue,source,journal,material,controller,controller_path):
    tag=first.batch.digest(sorted(accounts))[:12]
    wave=dict(accounts=sorted(accounts),scope='queued-new50-real-'+queue['sha256'][:12]+'-'+tag,pointer='queued-new50-'+queue['sha256'][:12]+'-'+tag+'.json',date=today())
    with wave_context(queue,source,journal,material,wave,controller['modes']),first.locked():
        path,value=first.freeze()
    wave.update(manifest=path.name,sha256=value['sha256']);controller['waves'].append(wave);first.upload.save_json(controller_path,controller)
    return wave


def covered_accounts(controller):
    return {j['account'] for w in controller['waves'] for j in first.archive.checked_json(first.upload.ROOT/'logs'/w['manifest'])['payload']['jobs']}


def media_launcher(factory,jobs,path,value):
    by_pair={(j['account'],j['target']):j for j in jobs}
    def launch(pw,entry):
        context=None
        try:
            context=factory(pw,entry);page=context.pages[-1] if context.pages else context.new_page()
            browser.repair.wait_session(page);first.upload.ensure_identity(page,entry)
            return context
        except Exception as error:
            if context is not None:context.close()
            job=by_pair.get((entry.get('account'),entry.get('target')))
            if job and first.upload.target_key(entry['url'])==first.upload.target_key(job['url']):
                state_path=first.upload.ROOT/'logs/publish_state.json';state=first.upload.read_json(state_path,{})
                report=first.upload.read_json(path.with_name(path.stem+'-results.json'),{})
                submitted=any(r.get('key')==job['key'] and r.get('video_status') in {'published','posting','needs_review','preparing'} for r in report.get('rows',[]))
                if job['key'] not in state and not submitted:
                    state[job['key']]=dict(account=job['account'],target=job['target'],url=job['url'],video=str(first.upload.inbox_for(entry)/job['filename']),
                        status='failed_before_post',uploader_version='2.47',ai_label_requested=False,created=datetime.now(timezone.utc).isoformat(),
                        error=str(error) or type(error).__name__,failure_stage='open_target_profile',before_media_launch_failure=True,
                        source_frozen_manifest=path.name,source_frozen_sha256=value['sha256'])
                    first.upload.save_json(state_path,state)
            raise
        except BaseException:
            if context is not None:context.close()
            raise
    return launch


def run_wave(queue,source,journal,material,wave,modes,retry_explicit=False):
    with wave_context(queue,source,journal,material,wave,modes) as grant:
        path=first.upload.ROOT/'logs'/wave['manifest'];value=first.archive.checked_json(path)
        if value['sha256']!=wave['sha256']:raise ValueError('新增账号冻结波次变化。')
        first.validate(path,value,material)
        for issue in value.get('issues',[]):print('本目标保留待处理：',issue,flush=True)
        with first.locked():first.recover_own(path,value)
        jobs=value['payload']['jobs'];pages=set();ensure=first.personals.ensure_personal
        with first.priority.daily.keep_awake(),first.personals.scoped(set(wave['accounts'])),first.editor.installed(), \
             patch.object(first.personals,'ensure_personal',side_effect=lambda page,entry:browser.repair.ensure_background_identity(ensure,page,entry)), \
             patch.object(first.upload,'launch_context',media_launcher(first.normal.launcher_for_jobs(jobs,date=wave['date']),jobs,path,value)),first.capture.installed(path,value):
            print('新增账号实拍队列：素材日期',queue['payload']['material_date'],'；当前实际执行日期',today(),'；AI标签关闭。',flush=True)
            if datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):print('等待素材及统一文案写入稳定，约一分钟后自动开始。',flush=True)
            while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
            first.batch.run(path,defer_comments=True,resume=True)
            first.priority.retry.run(path)
            with first.locked():first.reconcile(path,value)
            comment_rows=[]
            with patch.object(first.priority.daily,'find_published',first.priority.actual.make_finder(jobs,True,interactive=False)):
                first.priority.daily.backfill(value,None,only_keys={j['key'] for j in jobs},rows=comment_rows,future_only=True,reconcile_pending=True,reporter=lambda *_:first.priority.comment_report(path,value,comment_rows))
            first.priority.comment_retry.run(path,reporter=lambda m,r,o:first.priority.comment_report(path,value,r))
        if retry_explicit:
            pointer=first.upload.read_json(first.upload.ROOT/'logs'/(grant+'.json'),{})
            saved=first.upload.read_json(first.upload.ROOT/'logs'/pointer.get('manifest','missing'),{}) if pointer else {}
            grant_stamp=saved.get('payload',{}).get('date') or today()
            def authorized():prepared.checked_queue(first.upload.ROOT)
            with patch.object(extra,'DAY',grant_stamp),patch.object(extra,'GRANT',grant),patch.object(extra,'require_day',side_effect=authorized), \
                 patch.object(extra,'source',return_value=(copy.deepcopy(jobs),[dict(manifest=path.name,sha256=value['sha256'])],value['payload'])):
                extra.execute()
        report=first.upload.read_json(path.with_name(path.stem+'-results.json'),{})
        return first.batch.results(path,value,report.get('attempts',[]),None,final=True)


def summary(queue,source,controller,controller_path):
    state=first.upload.read_json(first.upload.ROOT/'logs/publish_state.json',{});jobs={};issues={}
    for wave in controller['waves']:
        value=first.archive.checked_json(first.upload.ROOT/'logs'/wave['manifest']);jobs.update({j['account']:j for j in value['payload']['jobs']});issues.update({i['account']:i.get('reason','') for i in value.get('issues',[])})
    rows=[]
    for assignment in source['payload']['distribution']['payload']['assignments']:
        account=assignment['account'];job=jobs.get(account);record=state.get(job['key'],{}) if job else {}
        rows.append(dict(account=account,target='personal',filename=assignment['files'][-1]['destination_name'],key=job['key'] if job else None,
                         video_status=record.get('status','not_onboarded' if not job else 'not_started'),comment_status=record.get('comment_status','not_started'),reason=record.get('error') or issues.get(account) or controller.get('pending',{}).get(account,'')))
    controller.update(rows=rows,complete=all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows),updated_at=datetime.now(timezone.utc).isoformat())
    first.upload.save_json(controller_path,controller)
    print('新增50账号结果：成功',sum(r['video_status']=='published' for r in rows),'；发布前失败',sum(r['video_status']=='failed_before_post' for r in rows),'；待核实',sum(r['video_status'] in {'needs_review','preparing','posting'} for r in rows),'；未接入/未开始',sum(r['video_status'] in {'not_onboarded','not_started'} for r in rows),'；评论确认成功',sum(r['comment_status'] in {'sent','already_present'} for r in rows),flush=True)
    for row in rows:print(row['account'],row['video_status'],'；评论',row['comment_status'],flush=True)
    print('新50队列结果：',controller_path,flush=True)
    return rows


def execute(root):
    root=Path(root).resolve();_,queue,manifest,source=prepared.checked_queue(root);first.workflow.require_versions()
    if workers.active_workers(root,Path(__file__).resolve()) or not first24_finished(root,queue):return 75
    browser.staged.lock_recovery.recover_locks(root)
    with patch.object(stage,'active_workers',side_effect=lambda _:workers.active_workers(root,Path(__file__).resolve())):stage.import_stage(root,manifest)
    day=queue['payload']['material_date'];journal=root/'logs/material-distribution'/source['payload']['source_id']/(day+'-reserved50.json');material=first.archive.checked_json(journal)
    controller_path=root/'logs'/('new50-real-queue-'+queue['sha256'][:16]+'.json')
    controller=first.upload.read_json(controller_path,dict(queue_sha256=queue['sha256'],waves=[],modes={},pending={}))
    if controller.get('queue_sha256')!=queue['sha256'] or not isinstance(controller.get('waves'),list):raise ValueError('新增50队列执行记录不符。')
    ready=initial_ready(controller,controller_path);covered=covered_accounts(controller)
    if ready-covered:make_wave(ready-covered,queue,source,journal,material,controller,controller_path)
    for wave in controller['waves']:run_wave(queue,source,journal,material,wave,controller['modes'])
    rows=summary(queue,source,controller,controller_path)
    pending={r['account'] for r in rows if r['video_status']!='published' or r['comment_status'] not in {'sent','already_present'}}
    if pending:
        print('其余账号已处理；以下编号仍需检查登录、网络、视频结果或评论。已提交的只核实，不重复上传：',','.join(sorted(pending)),flush=True)
        answer=owners.guided.prompt('回车依次检查并继续；S保留待处理并结束，Q暂停：')
        if answer=='S':return 3
        if answer!='S':
            for account in sorted(pending):
                try:
                    found=owners.discover_manual(account)
                    if found is None:continue
                    entry,proof,mode=found
                    config=first.upload.read_json(first.upload.CONFIG,{})
                    existing=[e for e in config['targets'] if (e.get('account'),e.get('target'))==(account,'personal')]
                    if len(existing)!=1 or not first.batch.eligible(existing[0],True,date=today()):
                        with first.locked(),patch.object(first,'DAY',today()):owned.register_one(account,entry,proof)
                    elif first.upload.target_key(existing[0]['url'])!=first.upload.target_key(entry['url']):raise ValueError('原登记本人不同，未换号。')
                    controller['modes'][account]=mode;controller['pending'].pop(account,None);ready.add(account);first.upload.save_json(controller_path,controller)
                except KeyboardInterrupt:raise
                except Exception as error:controller['pending'][account]=owners.guided.brief(error)['message']
            covered=covered_accounts(controller)
            if ready-covered:make_wave(ready-covered,queue,source,journal,material,controller,controller_path)
    for wave in controller['waves']:run_wave(queue,source,journal,material,wave,controller['modes'],retry_explicit=True)
    summary(queue,source,controller,controller_path)
    return 0 if controller['complete'] else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行。')
        raise SystemExit(execute(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停新50队列，保留接入、视频、评论及补发进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
