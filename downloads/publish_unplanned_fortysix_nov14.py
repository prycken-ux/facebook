"""Publish only the original forty-six previously unplanned personal targets."""
import contextlib,copy,sys,time,uuid
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import diagnose_login_and_resume_fifteen_nov14 as guided
resume=guided.base.resume
first=resume.first
original=resume.original
DAY='2026-11-14'
NAME_POLICY='1.0-verified-owner-local-label'
EXISTING_FOUR={'fb37','fb38','fb55','fb60'}
REQUESTED=original.NEW-EXISTING_FOUR
REPORT='nov14-original-unplanned46-registration.json'
SUMMARY='nov14-original-unplanned46-results.json'
VIDEO_RUN=original.RUN


def known_owner(account):
    rows=first.upload.read_json(first.upload.CONFIG,{}).get('targets',[])+first.upload.read_json(first.upload.ROOT/'account_registry.json',{}).get('accounts',[])
    extra=original.reservation();rows=rows+[extra['slots'][account].get('mapping',{})]
    owners=set()
    for row in rows:
        if row.get('account')==account and row.get('target','personal')=='personal' and row.get('url'):
            owner=first.upload.target_key(row['url'])
            if not owner.startswith('id:'):raise guided.LoginIssue('owner_unverified','此编号已有未规范化的身份映射，保留待检查，不自动改绑。')
            owners.add(owner)
    if len(owners)>1:raise guided.LoginIssue('conflicting_login','此编号保存了冲突身份，保留待本人检查。')
    return next(iter(owners)) if owners else None


def identify_current(page,account,expected=None):
    # Login identifiers are compared in memory, never exported in diagnostics.
    guided.base.wait_session(page)
    people={c['value'] for c in page.context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and c.get('value')}
    if len(people)!=1 or not next(iter(people)).isdecimal():raise guided.LoginIssue('conflicting_login','该编号登录身份不唯一或无效。')
    owner=next(iter(people));key='id:'+owner
    if expected and expected!=key:raise guided.LoginIssue('wrong_owner','当前登录者与该编号已保存的本人不同，未换号或覆盖。')
    entry=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',name='Current personal owner',url='https://www.facebook.com/profile.php?id='+owner,auto_switch_personal=True)
    first.upload.personal_actor_fingerprint(page,entry)
    first.upload.navigate_profile(page,entry['url'])
    proof=first.personals.ensure_personal(page,entry)
    name=None;deadline=time.monotonic()+3
    while True:
        name=original.registration.automatic_name(page,account,entry,proof)
        if name or time.monotonic()>=deadline:break
        page.wait_for_timeout(200)
    source='observed_or_same_owner_cached_name'
    if not name:
        # Cosmetic local display information is not ownership evidence. The
        # numeric owner and /me checks above remain mandatory before registering.
        name=account+' [verified ID '+owner+']';source='verified_id_local_label'
        print('界面名称暂未取得，使用本地已核验身份标签，不修改Facebook名称：',name,flush=True)
    entry['name']=name;proof.update(name=name,checked_at=datetime.now(timezone.utc).isoformat(),display_name_source=source)
    if first.personals.stable_actor(page,entry,proof['recovery_login_marker'])!=proof['session_marker']:raise guided.LoginIssue('wrong_owner','核验期间身份变化，未登记或发布。')
    return entry,proof


def discover_background(account,expected=None):
    from playwright.sync_api import sync_playwright
    probe=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',name='Current personal owner',url='https://www.facebook.com/me',auto_switch_personal=True)
    expected=expected or known_owner(account)
    context=None
    with sync_playwright() as pw:
        try:
            context,page=guided.open_for_check(pw,probe,'background')
            if page._manual_check_navigation_issue:raise guided.LoginIssue(page._manual_check_navigation_issue['code'],page._manual_check_navigation_issue['message'])
            return identify_current(page,account,expected)
        finally:
            if context is not None:context.close()


def discover_manual(account):
    from playwright.sync_api import sync_playwright
    expected=known_owner(account)
    probe=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',name='Current personal owner',url='https://www.facebook.com/me',auto_switch_personal=True)
    while True:
        context=None
        try:
            with sync_playwright() as pw:
                try:
                    context,page=guided.open_for_check(pw,probe,'foreground')
                    while True:
                        try:entry,proof=identify_current(page,account,expected);break
                        except KeyboardInterrupt:raise
                        except Exception as error:
                            print('需要本人处理：',account,guided.brief(error)['message'],flush=True)
                            print('只完成登录或安全验证、检查原代理，并切回本人个人主页；不要手动上传或发布。',flush=True)
                            answer=guided.prompt('处理完成回到PowerShell按回车核验；R重新打开本人入口，S跳过此账号，Q暂停：')
                            if answer=='S':return None
                            if answer=='R':
                                try:page.goto(first.upload.english_url(probe['url']),wait_until='domcontentloaded',timeout=30000)
                                except Exception:pass
                finally:
                    if context is not None:context.close()
            break
        except KeyboardInterrupt:raise
        except Exception as error:
            print('该编号检查窗口未就绪：',account,guided.brief(error)['message'],flush=True)
            if guided.prompt('请关闭该编号重复打开的窗口后回车重试；S跳过，Q暂停：')=='S':return None
    while True:
        try:
            verified,background_proof=discover_background(account,first.upload.target_key(entry['url']))
            return verified,background_proof,'background'
        except KeyboardInterrupt:raise
        except Exception as error:
            issue=guided.brief(error)
            if issue['code'] in {'wrong_owner','conflicting_login'}:
                print('后台出现冲突身份，本账号保留待检查：',account,issue['message'],flush=True);return None
            print('前台本人核验已通过，但后台仍未通过：',account,issue['message'],flush=True)
            answer=guided.prompt('F仅此账号本轮用最小化普通Chrome发布；R再检查后台；S跳过；Q暂停：')
            if answer=='F':return entry,proof,'foreground_minimized'
            if answer=='S':return None


def focused_summary(first_path,control,issues,material):
    paths=[first_path]+[first.upload.ROOT/'logs'/r['manifest'] for r in control['waves']]
    state=first.upload.read_json(first.upload.ROOT/'logs/publish_state.json',{});rows={}
    for path in paths:
        value=first.archive.checked_json(path)
        for job in value['payload']['jobs']:
            if job['account'] not in REQUESTED:continue
            record=state.get(job['key'],{})
            rows[job['account']]=dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],video_status=record.get('status','not_started'),comment_status=record.get('comment_status','not_started'),reason=record.get('comment_error','') if record.get('status')=='published' else record.get('error',''))
    counts=Counter(r['video_status'] for r in rows.values());missing=sorted(REQUESTED-set(rows))
    print('本次原46账号累计：视频成功',counts['published'],'；发布前失败',counts['failed_before_post'],'；待核实',sum(counts[k] for k in ('needs_review','posting','preparing')),'；未开始',counts['not_started'],'；尚未接入',len(missing),'；评论确认成功',sum(r['comment_status'] in {'sent','already_present'} for r in rows.values()),flush=True)
    for row in rows.values():print('本次目标：',row['account'],row['video_status'],'；评论：',row['comment_status'],flush=True)
    for issue in issues:print('本次仍需处理：',issue['account'],issue['reason'],flush=True)
    result=dict(date=DAY,source_material_date=resume.SOURCE_DAY,requested_accounts=sorted(REQUESTED),rows=list(rows.values()),unplanned_accounts=missing,issues=issues)
    first.upload.save_json(first.upload.ROOT/'logs'/SUMMARY,result)
    return not missing and not issues and all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows.values())


def execute():
    resume.require_run_day();first.workflow.require_versions()
    with first.locked():
        _,parent,material_path,material,_,_=resume.source();original.reservation()
        assigned={(r['account'],r['target']) for r in material['payload']['assignments']}
        if not {(a,'personal') for a in REQUESTED}<=assigned:raise ValueError('原11月13日分配清单缺少这46个目标，未选择新素材。')
        report_path=first.upload.ROOT/'logs'/REPORT
        report=first.upload.read_json(report_path,dict(schema='nov14-unplanned46-registration-v1',distribution_sha256=material['sha256'],accounts={}))
        if report.get('schema')!='nov14-unplanned46-registration-v1' or report.get('distribution_sha256')!=material['sha256'] or not isinstance(report.get('accounts'),dict):raise ValueError('本次46账号接入进度异常。')
    pending={};modes={};ran=set();stage='automatic'
    def register(account,entry,proof,mode):
        with patch.object(first,'DAY',DAY):original.register_one(account,entry,proof)
        report['accounts'][account]=dict(url=entry['url'],name=entry['name'],display_name_source=proof.get('display_name_source','observed_or_same_owner_cached_name'),mode=mode,checked_at=proof['checked_at'],status='registered')
        modes[account]=mode;first.upload.save_json(report_path,report)
    def ready_requested():
        ready=set();issues=[]
        for index,account in enumerate(sorted(REQUESTED),1):
            entries=[e for e in first.upload.read_json(first.upload.CONFIG,{}).get('targets',[]) if (e.get('account'),e.get('target'))==(account,'personal')]
            if len(entries)==1 and first.batch.eligible(entries[0],True,date=DAY):
                ready.add(account);saved=report['accounts'].get(account,{})
                if saved.get('url')==entries[0]['url'] and saved.get('mode') in {'background','foreground_minimized'}:modes[account]=saved['mode']
                else:modes[account]='background'
                continue
            if stage!='automatic':
                issues.append(dict(account=account,reason=pending.get(account,'尚未完成本人登录与登记')));continue
            print('自动接入原46账号：',index,'/46',account,'；名称不再阻止已核验ID登记。',flush=True)
            try:
                entry,proof=discover_background(account);register(account,entry,proof,'background');ready.add(account)
            except KeyboardInterrupt:raise
            except Exception as error:
                issue=guided.brief(error);pending[account]=issue['message'];issues.append(dict(account=account,reason=issue['message']))
                report['accounts'][account]=dict(status='needs_manual',issue=issue);first.upload.save_json(report_path,report)
                print('该账号先保留，先处理其他自动可用账号：',account,issue['message'],flush=True)
        return ready,issues
    def run_requested(real):
        accounts=set(first.ALLOWED)
        if not accounts&REQUESTED:
            print('本次保留范围外已有批次，不执行其视频或评论：',first.WAVE_DESCRIPTION,flush=True)
            return 3
        if not accounts<=REQUESTED:raise ValueError('本批混入这46个之外的账号，未扩大发布范围。')
        pointer=first.upload.read_json(first.upload.ROOT/'logs'/first.POINTER,{})
        token=pointer.get('sha256')
        if token and token in ran:return 3
        result=VIDEO_RUN(real)
        pointer=first.upload.read_json(first.upload.ROOT/'logs'/first.POINTER,{})
        if pointer.get('sha256'):ran.add(pointer['sha256'])
        return result
    launcher=first.normal.launcher_for_jobs
    def launch_requested(jobs,date=None):
        native=launcher(jobs,date=date)
        def launch(pw,entry):
            if entry['account'] not in REQUESTED:raise ValueError('不属于本次46账号，未打开浏览器。')
            if modes.get(entry['account'])=='foreground_minimized':
                with guided.minimized_chrome(entry):return native(pw,entry)
            with patch.object(first.normal.background,'mode',return_value='background'):return native(pw,entry)
        return launch
    print('仅处理原46个未进入清单的账号：fb25–fb74，排除fb37、fb38、fb55、fb60。先发布自动可核验的，再处理需要本人协助的账号。',flush=True)
    print('沿用11月13日原分配视频、已确认实拍标签、原正文和评论；不扫描今天新文件、不重发老账号。',flush=True)
    with patch.object(original,'ready_new',side_effect=ready_requested),patch.object(original,'RUN',side_effect=run_requested), \
         patch.object(original,'summary',side_effect=focused_summary),patch.object(first.normal,'launcher_for_jobs',side_effect=launch_requested):
        result=resume.execute()
        if pending:
            print('自动可用账号的本轮视频和评论已处理。剩余',len(pending),'个需要本人检查登录/网络；无需手动填写名称。',flush=True)
            answer=guided.prompt('回车依次打开待处理账号并继续发布；S本轮保留这些账号并结束；Q暂停：')
            if answer=='S':return result
            with first.locked():
                for account in sorted(pending.copy()):
                    resume.require_run_day()
                    try:
                        found=discover_manual(account)
                        if found is None:continue
                        entry,proof,mode=found;register(account,entry,proof,mode);pending.pop(account,None)
                    except KeyboardInterrupt:raise
                    except Exception as error:
                        pending[account]=guided.brief(error)['message'];print('该账号保留，继续其他待处理账号：',account,pending[account],flush=True)
            stage='after_manual';result=resume.execute()
    print('本次46账号结果保存在：',first.upload.ROOT/'logs'/SUMMARY,flush=True)
    return result


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if first.upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已暂停，保留接入、发布和评论进度；重跑同一指令继续本批46个原目标。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
