"""Normal Chrome sessions bound to one frozen batch, preserving local proxy/extensions."""
import re,subprocess,time
from pathlib import Path
import fb_upload as upload
from add_fb_accounts import find_chrome
from chrome_profile_guard import require_profile_free
from diagnose_personal_identity import close_selected_window
import local_file_input as local_files
import browser_background_mode as background

NORMAL_CHROME_VERSION='1.0-batch-scoped-local-cdp'
LOCAL_FILE_INPUT_COMPATIBILITY=local_files.VERSION
BATCH_DATE_VERSION=local_files.BATCH_DATE_VERSION


def endpoint(path):
    if path.is_symlink():raise ValueError('本机浏览器连接文件是链接，未接管')
    rows=path.read_text(encoding='ascii').splitlines()
    if len(rows)!=2 or not rows[0].isdecimal() or not 1024<=int(rows[0])<=65535 or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]+',rows[1]):
        raise ValueError('本机浏览器连接信息不合法')
    return 'ws://127.0.0.1:'+rows[0]+rows[1]


class NormalContext:
    def __init__(self,browser,context,account):self._browser=browser;self._context=context;self._account=account;self._closed=False
    def __getattr__(self,name):return getattr(self._context,name)
    def close(self):
        if self._closed:return
        self._closed=True
        try:
            try:self._browser.new_browser_cdp_session().send('Browser.close')
            except Exception:pass  # The expected connection-close event may race the reply.
            try:self._browser.close()
            except Exception:pass
        finally:
            local_files.release(self._context)
            close_selected_window(self._account)  # Graceful exact-profile close; never kill.


def launch_normal(playwright,entry):
    upload.validate_entry(entry)
    run_mode=background.mode(upload.ROOT)
    account=entry['account']
    if not re.fullmatch(r'fb(?:0[1-9]|[1-9][0-9]+)',account):raise ValueError('账号编号不合法')
    profile=upload.ROOT/'profiles'/account
    if not profile.is_dir() or profile.is_symlink():raise ValueError(account+'原浏览器资料缺失或为链接')
    require_profile_free(profile,account)
    port_file=profile/'DevToolsActivePort'
    if port_file.is_symlink():raise ValueError('本机连接文件异常')
    port_file.unlink(missing_ok=True)
    selfcheck=entry.get('_local_file_selfcheck') is True
    args=[str(find_chrome()),'--user-data-dir='+str(profile),'--profile-directory=Default',
          '--no-first-run','--no-default-browser-check','--remote-debugging-address=127.0.0.1',
          '--remote-debugging-port=0',*background.arguments(run_mode),'about:blank' if selfcheck else upload.english_url(entry['url'])]
    print('使用原资料启动'+('无窗口后台Chrome' if run_mode=='background' else '普通Chrome')+'：',account,entry['target'],'；沿用原资料和代理设置。',flush=True)
    process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    wrapper=None
    try:
        end=time.monotonic()+30
        while not port_file.is_file():
            if process.poll() is not None:raise RuntimeError('普通Chrome在建立本机连接前退出，尚未上传')
            if time.monotonic()>=end:raise RuntimeError('普通Chrome本机连接尚未就绪，尚未上传')
            time.sleep(.2)
        try:address=endpoint(port_file)
        except (OSError,ValueError):
            time.sleep(.3);address=endpoint(port_file)
        try:browser=playwright.chromium.connect_over_cdp(address,timeout=20000)
        except Exception:raise RuntimeError(account+'普通Chrome本机控制连接失败，尚未上传') from None
        if len(browser.contexts)!=1:
            browser.close();raise RuntimeError(account+'本机浏览器上下文不唯一，尚未上传')
        context=browser.contexts[0];wrapper=NormalContext(browser,context,account)
        context.add_cookies([dict(name='locale',value='en_US',domain='.facebook.com',path='/',secure=True)])
        if selfcheck:
            print('本机原视频选取自检：只打开本地测试页，不访问或提交Facebook。',flush=True)
            return wrapper
        page=context.pages[-1] if context.pages else context.new_page()
        for attempt in range(3):
            try:
                page.goto(upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000)
                upload.checkpoint(page);upload.require_no_advanced_protection(page);break
            except Exception as error:
                if attempt==2 or not any(code in str(error) for code in ('ERR_PROXY_CONNECTION_FAILED','ERR_TUNNEL_CONNECTION_FAILED','ERR_CONNECTION_CLOSED','ERR_CONNECTION_RESET')):raise
                print('普通Chrome的原连接仍在就绪，仅重新打开主页核验，不选择视频。',flush=True)
                page.wait_for_timeout(2000)
        print('普通Chrome已打开目标主页：',account,entry['target'],'；继续身份核验。',flush=True)
        return wrapper
    except BaseException:
        if wrapper is not None:wrapper.close()
        else:close_selected_window(account)
        raise


def launcher_for_jobs(jobs,date=None):
    owners={}
    for job in jobs:
        pair=job['account'],job['target'];owner=upload.target_key(job['url'])
        if pair in owners and owners[pair]!=owner:raise ValueError('本批同一目标存在不同主页')
        owners[pair]=owner
    def launch(playwright,entry):
        pair=entry.get('account'),entry.get('target')
        if pair not in owners or upload.target_key(entry.get('url',''))!=owners[pair]:
            raise ValueError('普通Chrome启动目标不属于今天原清单')
        context=launch_normal(playwright,entry)
        try:local_files.authorize(context._context,entry,jobs,date=date)
        except BaseException:context.close();raise
        return context
    return launch
