"""Use normal Chrome startup for the existing exact fb02 Nov-3 publication grant."""
import ast,hashlib,re,ssl,subprocess,sys,time,urllib.request
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
from add_fb_accounts import find_chrome
from chrome_profile_guard import require_profile_free
from diagnose_personal_identity import close_selected_window

COMMIT='04acb09d2c3e0baa329c3cccaa8a8f418cbca534'
EXPECTED='43820e78f21962696a7b93461f1efcfe333f24dde79026727e40601e52bc037f'


def endpoint(path):
    if path.is_symlink():raise ValueError('本机浏览器连接文件是链接，未接管')
    rows=path.read_text(encoding='ascii').splitlines()
    if len(rows)!=2 or not rows[0].isdecimal() or not 1024<=int(rows[0])<=65535 or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]+',rows[1]):
        raise ValueError('本机浏览器连接信息不合法')
    return 'ws://127.0.0.1:'+rows[0]+rows[1]


class NormalContext:
    def __init__(self,browser,context):self._browser=browser;self._context=context;self._closed=False
    def __getattr__(self,name):return getattr(self._context,name)
    def close(self):
        if self._closed:return
        self._closed=True
        try:
            try:self._browser.new_browser_cdp_session().send('Browser.close')
            except Exception:pass  # The expected connection-close event may race the reply.
            try:self._browser.close()
            except Exception:pass
        finally:close_selected_window('fb02')  # Graceful exact-profile close; never kill.


def launch_normal(playwright,entry):
    if (entry.get('account'),entry.get('target'))!=('fb02','page01'):raise ValueError('普通Chrome接管仅限本次fb02/page01')
    profile=upload.ROOT/'profiles/fb02'
    if not profile.is_dir() or profile.is_symlink():raise ValueError('fb02原浏览器资料缺失或为链接')
    require_profile_free(profile,'fb02')
    port_file=profile/'DevToolsActivePort'
    if port_file.is_symlink():raise ValueError('本机连接文件异常')
    port_file.unlink(missing_ok=True)
    args=[str(find_chrome()),'--user-data-dir='+str(profile),'--profile-directory=Default',
          '--no-first-run','--no-default-browser-check','--remote-debugging-address=127.0.0.1',
          '--remote-debugging-port=0','--new-window',upload.english_url(entry['url'])]
    print('使用fb02原资料启动普通Chrome，保留原扩展和代理；仅通过本机连接接管。',flush=True)
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
        except Exception:raise RuntimeError('fb02普通Chrome本机控制连接失败，尚未上传') from None
        if len(browser.contexts)!=1:
            browser.close();raise RuntimeError('fb02本机浏览器上下文不唯一，尚未上传')
        context=browser.contexts[0];wrapper=NormalContext(browser,context)
        context.add_cookies([dict(name='locale',value='en_US',domain='.facebook.com',path='/',secure=True)])
        page=context.pages[-1] if context.pages else context.new_page()
        for attempt in range(3):
            try:
                page.goto(upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000)
                upload.checkpoint(page);upload.require_no_advanced_protection(page);break
            except Exception as error:
                if attempt==2 or not any(code in str(error) for code in ('ERR_PROXY_CONNECTION_FAILED','ERR_TUNNEL_CONNECTION_FAILED','ERR_CONNECTION_CLOSED','ERR_CONNECTION_RESET')):raise
                print('普通Chrome的原连接仍在就绪，仅重新打开主页核验，不选择视频。',flush=True)
                page.wait_for_timeout(2000)
        print('普通Chrome已打开fb02主页；继续原身份和视频校验。',flush=True)
        return wrapper
    except BaseException:
        if wrapper is not None:wrapper.close()
        else:close_selected_window('fb02')
        raise


def download_base():
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    for prefix in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(prefix+COMMIT+'/downloads/publish_fb02_nov03_20261104.py',context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=EXPECTED:raise ValueError('Base checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));return data
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    raise RuntimeError('原单条发布程序校验下载失败，未启动')


def execute():
    data=download_base();namespace={'__name__':'verified_fb02_single_video_library'}
    exec(compile(data,'verified-fb02-existing-single-video-grant','exec'),namespace)
    namespace['recover_locks']()
    original=upload.launch_context
    def selected(playwright,entry):
        if (entry.get('account'),entry.get('target'))!=('fb02','page01'):raise ValueError('本次仅允许fb02/page01')
        return launch_normal(playwright,entry)
    upload.launch_context=selected
    try:return namespace['execute']()
    finally:upload.launch_context=original


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if sys.platform!='win32' or upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原Windows上传电脑运行')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止；原发布意图和旧任务暂停状态保留。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
