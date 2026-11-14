"""Human-assisted same-profile login diagnosis, then the existing fifteen-job grant."""
import contextlib,copy,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import retry_nov13_prepost_fifteen_on_nov14 as base
first=base.first
RETRY=base.execute
DAY='2026-11-14'
ACCOUNTS=('fb09','fb17','fb37','fb38','fb55')
REPORT='nov14-fifteen-manual-session-diagnostics.json'


class LoginIssue(RuntimeError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def brief(error):
    # Do not persist URL query strings or browser/cookie diagnostics from a
    # lower-level exception. The console may show a bounded generic reason.
    if isinstance(error,LoginIssue):return dict(ok=False,code=error.code,message=str(error))
    value=str(error)
    if 'net::ERR_' in value:
        import re
        code=re.search(r'net::ERR_[A-Z_]+',value)
        return dict(ok=False,code='network_error',message=code.group(0) if code else '网络连接失败')
    if 'Chrome 资料仍被占用' in value:return dict(ok=False,code='profile_busy',message='该编号原Chrome资料仍被占用，请关闭该编号已有窗口后重试。')
    if '登录或安全验证' in value:return dict(ok=False,code='login_or_checkpoint',message='需要本人完成登录或安全验证。')
    if isinstance(error,base.SessionNotReady):
        if '不唯一' in value or '无效' in value:return dict(ok=False,code='conflicting_login',message='后台登录身份冲突或无效，保留待本人检查。')
        return dict(ok=False,code='session_missing',message='未读取到唯一有效登录会话。')
    if isinstance(error,first.upload.PageActorActive):return dict(ok=False,code='page_actor',message='请在当前窗口切回登录者自己的个人主页。')
    return dict(ok=False,code='identity_or_page_unverified',message='主页或身份尚未完成核验，请检查网络、本人主页和当前登录身份。')


def configured_personal(account,jobs):
    candidates=[j for j in jobs if (j['account'],j['target'])==(account,'personal')]
    entries=[e for e in first.upload.read_json(first.upload.CONFIG,{}).get('targets',[]) if (e.get('account'),e.get('target'))==(account,'personal')]
    if len(candidates)!=1 or len(entries)!=1 or first.batch.digest(entries[0])!=candidates[0]['entry_sha256']:
        raise LoginIssue('config_changed','原个人主页登记已变化，未猜选或替换账号。')
    return dict(entries[0],enabled=True,auto_switch_personal=True)


def verify_session(page,entry):
    first.upload.checkpoint(page);first.upload.require_no_advanced_protection(page)
    people={c['value'] for c in page.context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and c.get('value')}
    if not people:raise LoginIssue('session_missing','当前窗口没有有效登录会话，请在原账号窗口登录。')
    if len(people)!=1 or not next(iter(people)).isdecimal():raise LoginIssue('conflicting_login','登录会话不唯一或无效，不能继续补发。')
    expected=first.upload.target_key(entry['url'])
    if expected.startswith('id:') and people!={expected[3:]}:raise LoginIssue('wrong_owner','当前登录者与该编号原登记身份不同；请登录原账号，不会改绑新身份。')
    first.upload.personal_actor_fingerprint(page,entry)
    try:current=first.upload.target_key(page.url)
    except ValueError:current=None
    if current!=expected:first.upload.navigate_profile(page,entry['url'])
    first.upload.checkpoint(page)
    if expected.startswith('id:'):proof=first.personals.ensure_personal(page,entry)
    else:proof=first.upload.ensure_personal_identity(page,entry)
    # A proof is kept in memory only; never export a cookie or login marker.
    first.upload.personal_actor_fingerprint(page,entry)
    return dict(ok=True,code='verified_owner',message='已核实原登记本人身份。')


def open_for_check(pw,entry,mode):
    # Start blank so /login or /checkpoint does not close the very window in
    # which the owner must complete the official login/verification flow.
    with patch.object(first.normal.background,'mode',return_value=mode):
        context=first.normal.launch_normal(pw,dict(entry,_local_file_selfcheck=True))
    page=context.pages[-1] if context.pages else context.new_page()
    page._manual_check_navigation_issue=None
    try:page.goto(first.upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000)
    except Exception as error:
        page._manual_check_navigation_issue=brief(error)
        print('主页暂未完整打开；检查窗口保留，供本人检查网络/代理或重新加载。',brief(error)['message'],flush=True)
    return context,page


def probe_background(entry):
    from playwright.sync_api import sync_playwright
    context=None
    try:
        with sync_playwright() as pw:
            try:
                context,page=open_for_check(pw,entry,'background')
                if page._manual_check_navigation_issue:return page._manual_check_navigation_issue
                base.wait_session(page)
                return verify_session(page,entry)
            finally:
                if context is not None:context.close()
    except KeyboardInterrupt:raise
    except Exception as error:return brief(error)


def prompt(message):
    try:answer=input(message).strip().upper()
    except EOFError:raise RuntimeError('本步骤需要原PowerShell窗口输入，请直接运行完整新指令；不要使用关闭标准输入的旧后台入口。') from None
    if answer=='Q':raise KeyboardInterrupt
    return answer


def manual_foreground(entry):
    from playwright.sync_api import sync_playwright
    while True:
        context=None
        try:
            with sync_playwright() as pw:
                try:
                    context,page=open_for_check(pw,entry,'foreground')
                    while True:
                        try:return verify_session(page,entry)
                        except KeyboardInterrupt:raise
                        except Exception as error:
                            result=brief(error)
                            print('需要本人处理：',entry['account'],result['message'],flush=True)
                            print('请只完成登录/验证、检查该账号原代理连接，并切回自己的个人主页；不要手动选择视频或点击发布。',flush=True)
                            answer=prompt('处理完成后回到本PowerShell按回车核验；R重新打开原主页，S跳过此账号，Q暂停：')
                            if answer=='S':return dict(ok=False,code='user_skip',message='本人选择暂跳过此账号。')
                            if answer=='R':
                                try:page.goto(first.upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000)
                                except Exception:pass
                finally:
                    if context is not None:context.close()
        except KeyboardInterrupt:raise
        except Exception as error:
            print('此账号检查窗口尚未就绪：',entry['account'],brief(error)['message'],flush=True)
            answer=prompt('请关闭此编号重复打开的Chrome窗口后回车重试；S跳过，Q暂停：')
            if answer=='S':return dict(ok=False,code='user_skip',message='本人选择暂跳过此账号。')


def diagnose_account(entry):
    row=dict(account=entry['account'],expected_target=entry['url'],checked_at=datetime.now(timezone.utc).isoformat())
    print('检查编号及原登记本人：',entry['account'],entry['name'],entry['url'],flush=True)
    print('先只读检查后台登录：',entry['account'],'；本步骤不上传视频或发送评论。',flush=True)
    row['background_before']=probe_background(entry)
    if row['background_before']['ok']:
        row.update(mode='background',conclusion='本轮后台已核验原本人身份，无需手动登录。');return row
    print('后台检查结果：',row['background_before']['message'],'现在打开该编号原Chrome供本人处理。',flush=True)
    row['foreground']=manual_foreground(entry)
    if not row['foreground']['ok']:
        row.update(mode=None,conclusion='本人跳过，保留所有视频原记录。');return row
    while True:
        row['background_after']=probe_background(entry)
        if row['background_after']['ok']:
            row.update(mode='background',conclusion='前台处理后，后台已通过同一原身份核验。');return row
        print('同一份资料在前台已核实本人，但本轮后台仍未通过：',row['background_after']['message'],flush=True)
        print('这说明后台与前台结果有差异，不能直接断定账号未登录；原代理/扩展及后台兼容性仍需检查。',flush=True)
        if row['background_after']['code'] in {'wrong_owner','conflicting_login'}:
            row.update(mode=None,conclusion='后台出现冲突身份，保留待检查，不自动改绑或继续。');return row
        answer=prompt('F仅此账号用最小化普通Chrome补发；R再检查后台；S跳过此账号；Q暂停：')
        if answer=='F':
            row.update(mode='foreground_minimized',conclusion='本人选择仅此账号在本轮使用最小化普通Chrome补发。');return row
        if answer=='S':row.update(mode=None,conclusion='本人选择暂不补发此账号。');return row


@contextlib.contextmanager
def minimized_chrome(entry):
    arguments=first.normal.background.arguments;popen=first.normal.subprocess.Popen
    profile_flag='--user-data-dir='+str(first.upload.ROOT/'profiles'/entry['account'])
    def flags(mode):return [*arguments(mode),'--start-minimized'] if mode=='foreground' else arguments(mode)
    def launch(args,*positional,**kwargs):
        if sys.platform=='win32' and isinstance(args,(list,tuple)) and profile_flag in args:
            info=first.normal.subprocess.STARTUPINFO();info.dwFlags|=first.normal.subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=7  # SW_SHOWMINNOACTIVE
            kwargs['startupinfo']=info
        return popen(args,*positional,**kwargs)
    with patch.object(first.normal.background,'mode',return_value='foreground'),patch.object(first.normal.background,'arguments',side_effect=flags), \
         patch.object(first.normal.subprocess,'Popen',side_effect=launch):yield


def execute():
    base.require_day();first.workflow.require_versions()
    with first.locked():
        path,value=base.prepare();jobs=value['payload']['jobs'];state=first.upload.read_json(first.upload.ROOT/'logs/publish_state.json',{})
        claims_path=first.upload.ROOT/'logs'/(base.GRANT+'-claims.json')
        claims=first.upload.read_json(claims_path,dict(grant=base.GRANT,sha256=value['sha256'],jobs={}))
        if claims.get('grant')!=base.GRANT or claims.get('sha256')!=value['sha256'] or not isinstance(claims.get('jobs'),dict):raise ValueError('原补发许可账本异常。')
        ready=set()
        for job in jobs:
            try:
                if base.checked(job,state,claims,value)[1]=='ready':ready.add(job['account'])
            except Exception:print('该目标的原文件或配置需检查，先保留：',job['account'],job['target'],flush=True)
        approved={};report=first.upload.read_json(first.upload.ROOT/'logs'/REPORT,dict(schema='manual-session-diagnostics-v1',runs=[]))
        if report.get('schema')!='manual-session-diagnostics-v1' or not isinstance(report.get('runs'),list):raise ValueError('手动诊断记录异常。')
        current=dict(id=uuid.uuid4().hex,created_at=datetime.now(timezone.utc).isoformat(),source_manifest=path.name,rows=[])
        report['runs'].append(current)
        print('只检查需要补发的原资料：fb09、fb17、fb37、fb38、fb55；只在需要本人处理时打开窗口。不会记录密码或Cookie内容。',flush=True)
        try:
            for account in ACCOUNTS:
                if account not in ready:continue
                base.require_day()
                try:row=diagnose_account(configured_personal(account,jobs))
                except KeyboardInterrupt:raise
                except Exception as error:row=dict(account=account,mode=None,conclusion='此账号诊断未完成，保留原视频。',issue=brief(error))
                current['rows'].append(row)
                if row.get('mode'):approved[account]=row['mode']
                first.upload.save_json(first.upload.ROOT/'logs'/REPORT,report)
        finally:first.upload.save_json(first.upload.ROOT/'logs'/REPORT,report)
    launcher=first.normal.launcher_for_jobs
    def controlled_launcher(selected,date=None):
        original=launcher(selected,date=date)
        def launch(pw,entry):
            mode=approved.get(entry['account'])
            if not mode:raise base.SessionNotReady('此账号未完成本轮本人身份检查或本人选择跳过，保留原视频。')
            if mode=='foreground_minimized':
                with minimized_chrome(entry):return original(pw,entry)
            return original(pw,entry)
        return launch
    print('登录检查结束，开始沿用原许可补发；已成功和待核实的不重复上传。诊断记录：',first.upload.ROOT/'logs'/REPORT,flush=True)
    with patch.object(first.normal,'launcher_for_jobs',side_effect=controlled_launcher):return RETRY()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if first.upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已暂停，保留全部登录资料、诊断和补发进度；重跑同一新指令继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
