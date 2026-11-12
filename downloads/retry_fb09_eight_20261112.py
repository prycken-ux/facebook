"""User-authorized second repair of exactly eight pre-Post failures; retain history."""
import contextlib
import copy
import re
import shutil
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

if __name__ == '__main__':
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import scheduled_priority_workflow as workflow
import publish_priority_batch as priority
import normal_chrome_batch as normal
import recovery_numeric_identity as identity
import page_reel_ai_compat as editor
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

DAY = '2026-11-12'
SOURCE_PREFIX = '22d011ce'
GRANT = 'fb09-eight-editor-retry-20261112-v1'
TARGETS = {
    'page02': ('1110-2.mp4', 'ee814413bb2e'),
    'page03': ('1110-3.mp4', '230c256babfa'),
    'page04': ('1110-4.mp4', '759cf2c33093'),
    'page05': ('1110(2)-2.mp4', '140f92e7c44f'),
    'page06': ('1110(2)-3.mp4', '98a17a182ed2'),
    'page07': ('1110(2)-4.mp4', 'bc41e64d05cd'),
    'page09': ('3.mp4', '8794fa6157be'),
    'page10': ('4.mp4', '5aafb27e5f46'),
}
PROOF = ('post_intent_at', 'permalink', 'success_message', 'confirmation_method', 'confirmed_at', 'published_at')


def has_post_proof(value):
    if isinstance(value, list):
        return any(has_post_proof(v) for v in value)
    if not isinstance(value, dict):
        return False
    return any(value.get(k) for k in PROOF) or any(has_post_proof(v) for v in value.values() if isinstance(v, (dict,list)))


def source():
    pointer = upload.read_json(upload.ROOT/'logs/nov11-identity-repair-on-20261112.json', {})
    name = pointer.get('manifest', '')
    if not re.fullmatch('frozen-material-' + DAY + '-' + SOURCE_PREFIX + r'[a-f0-9]{8}\.json', name):
        raise ValueError('没有找到刚才22d011ce这批确切结果，未挑选其他日期素材。')
    path = upload.ROOT/'logs'/name
    value = upload.read_json(path, {})
    workflow.validate(path, value)
    if pointer.get('sha256') != value['sha256'] or len(value['payload']['jobs']) != 11:
        raise ValueError('原11条补发清单指纹不一致。')
    jobs = []
    for target, (filename, prefix) in TARGETS.items():
        matches = [j for j in value['payload']['jobs'] if (j.get('account'),j.get('target')) == ('fb09',target)
                   and j.get('filename') == filename and j.get('key','').startswith(prefix)]
        if len(matches) != 1:
            raise ValueError('未找到唯一的原失败视频：fb09/' + target)
        jobs.append(copy.deepcopy(matches[0]))
    return path, value, jobs


def plan(source_path, original, jobs):
    pointer = upload.ROOT/'logs'/(GRANT+'.json')
    saved = upload.read_json(pointer, None)
    if saved:
        name = saved.get('manifest','')
        if not re.fullmatch('frozen-material-'+DAY+r'-[a-f0-9]{16}\.json', name):
            raise ValueError('本次补发续跑指针异常。')
        path = upload.ROOT/'logs'/name
        value = upload.read_json(path,{})
        if saved.get('sha256') != value.get('sha256'):
            raise ValueError('本次补发指纹不一致。')
    else:
        payload = dict(original['payload'], jobs=jobs, manual_retry_schema=GRANT,
                       manual_retry_source_sha256=original['sha256'], manual_retry_source_manifest=source_path.name,
                       start=datetime.now(timezone.utc).astimezone(batch.BJ).isoformat())
        checksum = batch.digest(payload)
        path = upload.ROOT/'logs'/('frozen-material-'+DAY+'-'+checksum[:16]+'.json')
        value = dict(original, payload=payload, sha256=checksum, issues=[], created_at=datetime.now(timezone.utc).isoformat())
    workflow.validate(path,value)
    if (value['payload'].get('manual_retry_schema') != GRANT or value['payload'].get('manual_retry_source_sha256') != original['sha256']
            or value['payload']['jobs'] != jobs):
        raise ValueError('本次补发范围与原8条失败视频不一致。')
    if not saved:
        upload.save_json(path,value)
        upload.save_json(pointer,dict(manifest=path.name,sha256=value['sha256']))
    return path,value


def claims(value):
    path = upload.ROOT/'logs'/(GRANT+'-claims.json')
    ledger = upload.read_json(path,dict(grant=GRANT,sha256=value['sha256'],jobs={}))
    if not isinstance(ledger,dict) or ledger.get('grant') != GRANT or ledger.get('sha256') != value['sha256'] or not isinstance(ledger.get('jobs'),dict):
        raise ValueError('本次明确补发记录异常，未重置重试次数。')
    return path,ledger


def checked(job, state, ledger):
    row = state.get(job['key'])
    if (not isinstance(row,dict) or (row.get('account'),row.get('target')) != ('fb09',job['target'])
            or upload.target_key(row.get('url','')) != upload.target_key(job['url'])
            or str(row.get('video','')).replace('\\','/').rsplit('/',1)[-1] != job['filename']):
        raise ValueError('当前记录与原失败视频不一致。')
    if row.get('status') == 'published':
        return None,'published'
    if job['key'] in ledger['jobs']:
        return None,'attempted'
    if row.get('status') != 'failed_before_post' or has_post_proof(row):
        raise ValueError('已有提交、成功或待核实线索，保留不重发。')
    if row.get('uploader_version') != '2.47' or row.get('ai_label_requested') is not False:
        raise ValueError('原任务核心版本或实拍设置不一致。')
    if any(r.get('account')=='fb09' and r.get('status') in {'preparing','posting'} for r in state.values()):
        raise ValueError('fb09仍有进行中任务，未关闭窗口。')
    entry = batch.validate_job(job,date=DAY)
    # An explicit new user instruction grants one extra attempt. The original
    # persisted record (including today_first_retry_used) stays intact and is
    # subsequently nested by the core under previous_before_post_attempt.
    view = dict(state)
    view[job['key']] = dict(row,today_first_retry_used=False)
    selected = upload.named_job(entry,view,job['filename'],retry_before_post=True)
    if not selected or selected[0] != job['key'] or selected[3] != job['caption_text']:
        raise ValueError('原视频或原正文变化，未用其他内容代替。')
    return dict(entry,enabled=True,auto_switch_personal=True,ai_label=False),'ready'


def preflight_error(page, job):
    folder = upload.ROOT/'logs'/(GRANT+'-'+job['target']+'-preflight')
    folder.mkdir(parents=True,exist_ok=True)
    stage = getattr(page,'_fb_upload_stage','unknown')
    (folder/'error.txt').write_text('stage='+str(stage)+'\n'+traceback.format_exc(),encoding='utf-8')
    try:
        upload.checkpoint(page)
        page.screenshot(path=str(folder/'editor.png'))
    except Exception:
        pass
    output = shutil.make_archive(str(folder),'zip',folder)
    print('发布前验证未通过：',job['target'],'阶段：',stage,'；诊断：',output,flush=True)


def one(job, entry, value, path, ledger_path, ledger):
    from playwright.sync_api import sync_playwright
    state_path = upload.ROOT/'logs/publish_state.json'
    close_selected_window('fb09')
    launcher = normal.launcher_for_jobs(value['payload']['jobs'],date=DAY)
    with sync_playwright() as pw:
        context = launcher(pw,entry)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(30000)
            print('先验证原视频能进入发布就绪状态，尚未点击Post：',job['target'],job['filename'],flush=True)
            try:
                prepared = upload.prepare_reel(page,entry,upload.inbox_for(entry)/job['filename'],job['caption_text'])
            except BaseException:
                preflight_error(page,job)
                raise
            upload.recheck_publish_identity(page,entry,prepared[1])
            state = upload.read_json(state_path,{})
            if checked(job,state,ledger)[1] != 'ready':
                raise ValueError('编辑器验证期间原任务状态变化，未提交。')
            original = copy.deepcopy(state[job['key']])
            ledger['jobs'][job['key']] = dict(phase='consumed',source_job=copy.deepcopy(job),original_record=original,
                                             reserved_at=datetime.now(timezone.utc).isoformat())
            upload.save_json(ledger_path,ledger)
            original_named = upload.named_job
            def granted(candidate,current,filename,retry_before_post=False):
                if ((candidate['account'],candidate['target'],filename) != ('fb09',job['target'],job['filename'])
                        or not retry_before_post or current.get(job['key']) != original):
                    raise ValueError('明确补发许可与原任务不一致。')
                view = dict(current)
                view[job['key']] = dict(original,today_first_retry_used=False)
                return original_named(candidate,view,filename,retry_before_post=True)
            used = False
            def prepared_once(candidate_page,candidate,video,text,**kwargs):
                nonlocal used
                if used or candidate_page != page or video != upload.inbox_for(entry)/job['filename'] or text != job['caption_text'] or candidate['url'] != entry['url']:
                    raise ValueError('已就绪编辑器与本次确切原视频不一致。')
                used = True
                return prepared
            entry = dict(entry,_authorized_comment_text=value['payload']['comment_text'])
            # Reuse this verified editor. A second Playwright event loop, a
            # second file selection, or a second Post are never started here.
            with patch.object(upload,'launch_context',return_value=context), patch.object(upload,'prepare_reel',side_effect=prepared_once), \
                 patch.object(upload,'named_job',side_effect=granted), patch('playwright.sync_api.sync_playwright',return_value=contextlib.nullcontext(pw)):
                upload.run_entry(entry,state,state_path,True,filename=job['filename'],expected_job_key=job['key'],
                                 preserve_old_review_for_exact_job=True,retry_before_post=True,defer_comments=True,ai_label_override=False)
        finally:
            context.close()


def execute():
    if sys.platform != 'win32' or datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat() != DAY:
        raise ValueError('请在原Windows电脑于北京时间11月12日补发这8条原视频。')
    workflow.require_versions()
    if identity.VERSION != '1.0-numeric-actor-with-guided-picker':
        raise ValueError('数字身份修复模块未安装。')
    with locked(), priority.daily.keep_awake(), identity.scoped({('fb09',t) for t in TARGETS}), editor.installed():
        source_path,original,jobs = source()
        path,value = plan(source_path,original,jobs)
        ledger_path,ledger = claims(value)
        report_path = path.with_name(path.stem+'-results.json')
        report = upload.read_json(report_path,dict(manifest=path.name,attempts=[]))
        if report.get('manifest') != path.name or not isinstance(report.get('attempts'),list):
            raise ValueError('本次结果记录异常，未覆盖。')
        attempts = report['attempts']
        backup = upload.ROOT/'backups'/(GRANT+'-'+uuid.uuid4().hex[:10])
        backup.mkdir(parents=True)
        for file in (upload.ROOT/'logs/publish_state.json',source_path,source_path.with_name(source_path.stem+'-results.json')):
            shutil.copy2(file,backup/file.name)
        print('仅补发fb09/page02–07、page09、page10这8条。成功视频、fb16待核实及4个跳过账号保留。',flush=True)
        print('原状态及原清单备份：',backup,flush=True)
        gate_passed = bool(ledger['jobs'])
        try:
            for job in jobs:
                attempt = dict(key=job['key'],account='fb09',target=job['target'],action='manual_required',started_at=datetime.now(timezone.utc).isoformat())
                try:
                    state = upload.read_json(upload.ROOT/'logs/publish_state.json',{})
                    entry,status = checked(job,state,ledger)
                    if status != 'ready':
                        print('保留已有结果，不重发：',job['target'],status,flush=True)
                        continue
                    print('上次失败阶段：',job['target'],state[job['key']].get('failure_stage','未记录'),flush=True)
                    one(job,entry,value,path,ledger_path,ledger)
                    gate_passed = True
                    attempt['action'] = 'finished'
                except KeyboardInterrupt:
                    attempt.update(action='interrupted',error='用户中断，保留全部记录。')
                    raise
                except Exception as error:
                    attempt['error'] = str(error) or type(error).__name__
                    print('此条保留结果：',job['target'],attempt['error'].split('\n',1)[0],flush=True)
                    if job['key'] in ledger['jobs']:
                        gate_passed = True
                    if not gate_passed:
                        print('第一条尚未通过编辑器验证，本轮停止后续视频；未消耗其他视频的补发许可。',flush=True)
                        break
                finally:
                    attempts.append(attempt)
                    batch.results(path,value,attempts,None)
            original_launch = upload.launch_context
            upload.launch_context = normal.launcher_for_jobs(jobs,date=DAY)
            finder = priority.daily.find_published
            priority.daily.find_published = priority.actual.make_finder(jobs,True)
            rows = []
            try:
                priority.daily.backfill(value,None,only_keys={j['key'] for j in jobs},rows=rows,already_locked=True,future_only=True,
                                        reporter=lambda *_:priority.comment_report(path,value,rows))
                # This entire phase already holds the original global locks;
                # reuse them rather than acquiring the same mutex a second time.
                with patch.object(priority.comment_retry,'locked',side_effect=contextlib.nullcontext):
                    priority.comment_retry.run(path,reporter=lambda m,r,o:priority.comment_report(path,value,r))
            finally:
                upload.launch_context = original_launch
                priority.daily.find_published = finder
        finally:
            rows = batch.results(path,value,attempts,None,final=True)
    return 0 if all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows) else 3


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if upload.ROOT.resolve() != Path(sys.argv[1]).resolve():
            raise ValueError('请使用原上传目录。')
        raise SystemExit(execute())
    except KeyboardInterrupt:
        print('已停止，提交记录及本次补发许可保留；重跑不会重复提交。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',str(error) or type(error).__name__,flush=True)
        raise SystemExit(1)
