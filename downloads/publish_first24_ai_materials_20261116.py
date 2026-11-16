"""Publish exactly the newly imported Nov16 first24 footage with AI disclosure ON."""
import copy,importlib.util,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    sys.path.insert(0,str(Path(__file__).resolve().parent))
import ai_first24_workflow_20261116 as ai
import finish_first24_nov14_on_nov16 as browser
import retry_ai_prepost_first24_20261116 as extra
first=ai.first
DAY=ai.DAY
SCOPE=ai.SCOPE
POINTER='nov16-new-first24-ai-disclosure-on-publication.json'
PAUSED=set()
ALLOWED={f'fb{n:02d}' for n in range(1,25)}-PAUSED
EXPECTED=browser.staged.EXPECTED
VERSION='1.0-nov16-imported-first24-ai-on'
DISTRIBUTION=first.distribution


def sibling(name):
    spec=importlib.util.spec_from_file_location('_ai16_'+Path(name).stem,Path(__file__).resolve().with_name(name))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


stage=sibling('stage_next_materials_20261116_v2.py')
workers=sibling('material_distribution_worker_check.py')
BOOTSTRAP=re.compile(workers.BOOTSTRAP.pattern.replace('start_distribute_first24_materials_20261116','start_publish_first24_ai_20261116').replace('verified-first24-material-distribution','verified-ai-first24-publication'))


def require_day():
    if datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()!=DAY:raise ValueError('此入口仅用于11月16日已确认含AI的本批新素材；已提交记录保留。')


def allocation():
    root=first.upload.ROOT;stage.setup(root)
    pointer=first.upload.read_json(stage.safe_child(root,root/'material-staging/first24-pending-import.json'),{})
    if pointer.get('complete') is not True:raise ValueError('今天44条素材尚未正式分配完成；请等分配窗口显示“正式分配完成：44个目标”后再运行，未改动旧任务。')
    manifest=stage.safe_child(root,root/pointer.get('manifest',''))
    _,value=stage.validate_stage(root,manifest);p=value['payload'];d=p['distribution']['payload']
    receipt=first.upload.read_json(manifest.parent/'imported.json',{})
    pairs={(r['account'],r['target']) for r in d['assignments']}
    if (pointer.get('sha256')!=value['sha256'] or p.get('date')!=DAY or d.get('date')!=DAY or d.get('target_scope')!='existing24'
            or len(d['assignments'])!=44 or pairs!=EXPECTED or receipt.get('sha256')!=value['sha256']
            or receipt.get('distribution_sha256')!=p['distribution']['sha256']):raise ValueError('不是今天已正式导入的44条原分配素材，未选择旧批次或其他文件。')
    journal=stage.safe_child(root,root/'logs/material-distribution'/p['source_id']/(DAY+'.json'))
    material=first.archive.checked_json(journal)
    if material['sha256']!=p['distribution']['sha256']:raise ValueError('正式分配清单与暂存来源不符。')
    return manifest,value,journal,material


def assert_idle():
    with patch.object(workers,'BOOTSTRAP',BOOTSTRAP):active=workers.active_workers(first.upload.ROOT,Path(__file__).resolve())
    if active:raise RuntimeError('仍有旧发布、分配或登录检查任务，PID：'+','.join(str(r['pid']) for r in active)+'；请等原窗口结束后重跑本入口。未终止进程、未发布新视频。')


def scoped_launcher(factory,jobs,path,value):
    by_pair={(j['account'],j['target']):j for j in jobs}
    def launch(pw,entry):
        try:return factory(pw,entry)
        except Exception as error:
            # This factory only starts/checks the original Chrome session and
            # authorizes local input. No FB video has been selected yet. Persist
            # that specific failure so a later login fix can use the bounded
            # extra chance, instead of leaving an unresumable empty state row.
            job=by_pair.get((entry.get('account'),entry.get('target')))
            if job and first.upload.target_key(entry['url'])==first.upload.target_key(job['url']):
                state_path=first.upload.ROOT/'logs/publish_state.json';state=first.upload.read_json(state_path,{})
                report=first.upload.read_json(path.with_name(path.stem+'-results.json'),{})
                submitted=any(r.get('key')==job['key'] and r.get('video_status') in {'published','posting','needs_review','preparing'} for r in report.get('rows',[]))
                if job['key'] not in state and not submitted:
                    state[job['key']]=dict(account=job['account'],target=job['target'],url=job['url'],video=str(first.upload.inbox_for(entry)/job['filename']),
                        created=datetime.now(timezone.utc).isoformat(),status='failed_before_post',uploader_version='2.47',ai_label_requested=True,
                        failure_stage='open_target_profile',error=str(error) or type(error).__name__,source_frozen_manifest=path.name,source_frozen_sha256=value['sha256'],
                        before_media_launch_failure=True)
                    first.upload.save_json(state_path,state)
            raise
    return launch


def execute(ai_content_confirmed):
    if ai_content_confirmed is not True:raise ValueError('本批尚未确认含AI生成或显著修改的画面，未发布。')
    require_day();first.workflow.require_versions();_,source,journal,material=allocation()
    assert_idle();browser.staged.lock_recovery.recover_locks(first.upload.ROOT)
    def bound(relative=None):
        if relative is not None and (first.upload.ROOT/relative).resolve()!=journal.resolve():raise ValueError('AI批次只接受今天刚才分配的原清单。')
        result=DISTRIBUTION(first.archive.relative(journal))
        if result[1]['sha256']!=material['sha256']:raise ValueError('AI批次原分配内容发生变化。')
        return result
    print('本批新素材含AI生成或显著修改画面：AI标签开启。fb17已恢复，本批44个目标全部执行，沿用原正文、原评论。',flush=True)
    print('先发布新视频，再安全补发发布前失败、只读核验结果，最后评论及一次安全补评；已提交视频或评论均先核实，不重复提交。',flush=True)
    with patch.object(first,'DAY',DAY),patch.object(first,'MATERIAL_DAY',DAY),patch.object(first,'SCOPE',SCOPE),patch.object(first,'POINTER',POINTER), \
         patch.object(first,'ALLOWED',ALLOWED),patch.object(first,'distribution',side_effect=bound), \
         patch.object(first.archive,'today_files',side_effect=browser.staged.protect_other_materials), \
         patch.object(browser,'require_day',side_effect=require_day),ai.installed(source['sha256']),browser.browser_fixes():
        with first.locked():path,value=first.freeze();first.recover_own(path,value)
        jobs=value['payload']['jobs'];pages={(j['account'],j['target']) for j in jobs if j['target']!='personal'};ensure=first.numeric.ensure
        for issue in value['issues']:print('本目标暂未进入新批次：',issue,flush=True)
        with first.priority.daily.keep_awake(),first.personals.scoped(ALLOWED),first.numeric.scoped(pages),first.editor.installed(), \
             patch.object(first.numeric,'ensure',side_effect=lambda page,entry:ensure(page,entry,interactive=False)), \
             patch.object(first.upload,'launch_context',scoped_launcher(first.normal.launcher_for_jobs(jobs,date=DAY),jobs,path,value)),first.capture.installed(path,value):
            if datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):
                print('正在等待新素材及统一文案写入稳定，约一分钟后自动开始，请保持窗口打开。',flush=True)
            while datetime.now(timezone.utc)<datetime.fromisoformat(value['payload']['start']):time.sleep(1)
            first.batch.run(path,defer_comments=True,resume=True)
            first.priority.retry.run(path)
            with first.locked():first.reconcile(path,value)
            comments=[]
            with patch.object(first.priority.daily,'find_published',first.priority.actual.make_finder(jobs,True,interactive=False)):
                first.priority.daily.backfill(value,None,only_keys={j['key'] for j in jobs},rows=comments,future_only=True,reconcile_pending=True,reporter=lambda *_:first.priority.comment_report(path,value,comments))
            first.priority.comment_retry.run(path,reporter=lambda m,r,o:first.priority.comment_report(path,value,r))
        # One durable additional chance for any remaining proven pre-Post failure.
        # The AI validator requires this exact primary manifest as the sole source.
        with patch.object(extra,'source',return_value=(copy.deepcopy(jobs),[dict(manifest=path.name,sha256=value['sha256'])],value['payload'])):
            extra.execute()
        report=first.upload.read_json(path.with_name(path.stem+'-results.json'),{})
        final=first.batch.results(path,value,report.get('attempts',[]),None,final=True)
    print('本批44个目标（含fb17）的AI视频及评论处理结束；旧批次记录和fb25–fb74均保留。',flush=True)
    return 0 if not value['issues'] and all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in final) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if first.upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传电脑目录运行。')
        raise SystemExit(execute(True))  # The user explicitly confirmed this batch contains AI.
    except KeyboardInterrupt:print('已暂停并保留进度；同日重跑此AI入口继续，已提交视频和评论不重复发送。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
