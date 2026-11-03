"""Read-only actual Reels-tab probe on the Page whose direct comment succeeded."""
import ast,hashlib,ssl,sys,time,urllib.request
from pathlib import Path
from urllib.parse import parse_qs,urlencode,urlparse,urlunparse,urljoin
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import safe_video_comments as comments
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

PAIR=('fb10','page02')
NAME='Drascreflo Chajundfro'
OWNER='https://www.facebook.com/profile.php?id=61595204068114'
KNOWN='https://www.facebook.com/reel/1500593451890233'


def safe_url(value):
    parsed=urlparse(value);query=parse_qs(parsed.query)
    return urlunparse((parsed.scheme,parsed.hostname or '',parsed.path,'',urlencode({k:query[k][0] for k in ('id','sk','locale') if query.get(k)}),''))


def probe_page(page,seconds=20):
    tabs=page.get_by_role('tab',name='Reels',exact=True)
    visible=[tabs.nth(i) for i in range(tabs.count()) if tabs.nth(i).is_visible()]
    if len(visible)!=1:raise ValueError('没有唯一的页面Reels标签，未改点全站Reels入口')
    tab=visible[0];href=tab.get_attribute('href')
    tab.click(timeout=10000)
    end=time.monotonic()+seconds;links=set();selected=False;scrolls=0
    while time.monotonic()<end:
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        current=page.get_by_role('tab',name='Reels',exact=True)
        selected=any(current.nth(i).is_visible() and current.nth(i).get_attribute('aria-selected')=='true' for i in range(current.count()))
        if selected:
            for item in page.locator('main a[href],[role="main"] a[href]').all():
                if item.is_visible():
                    link=comments.direct_link(urljoin('https://www.facebook.com/',item.get_attribute('href') or ''))
                    if link:links.add(link)
        if scrolls<4:page.mouse.wheel(0,600);scrolls+=1
        page.wait_for_timeout(max(1,min(400,int((end-time.monotonic())*1000))))
    return dict(tab_href=safe_url(href) if href and href.startswith('https://') else None,
        actual_url=safe_url(page.url),selected=selected,links=sorted(links),known_video_found=KNOWN in links)


def execute(seconds=20):
    from playwright.sync_api import sync_playwright
    with locked():
        entries=[e for e in upload.read_json(upload.CONFIG,{}).get('targets',[]) if (e.get('account'),e.get('target'))==PAIR]
        if len(entries)!=1 or upload.target_key(entries[0]['url'])!=upload.target_key(OWNER) or entries[0].get('name')!=NAME:raise ValueError('fb10/page02名称或主页编号不匹配')
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        if any(r.get('account')=='fb10' and r.get('status') in {'preparing','posting'} for r in state.values()):raise ValueError('fb10仍有提交中任务，未关闭窗口')
        entry=entries[0];close_selected_window('fb10')
        with sync_playwright() as playwright:
            context=upload.launch_context(playwright,entry)
            try:
                page=context.new_page();page.set_default_timeout(15000)
                page.goto(upload.english_url(OWNER),wait_until='domcontentloaded',timeout=30000);upload.ensure_identity(page,entry)
                print('只读检查实际Reels标签；不会发送评论或修改发布记录。',flush=True)
                result=probe_page(page,seconds)
            finally:context.close()
        upload.save_json(upload.ROOT/'logs/fb10-page02-actual-reels-probe.json',result)
        print('fb10/page02 实际入口：',result['actual_url'],flush=True)
        print('Reels标签已选中：',result['selected'],'；读到视频链接：',len(result['links']),flush=True)
        print('包含刚才已评论成功的视频：',result['known_video_found'],flush=True)
        for link in result['links']:print('视频链接：',link,flush=True)
        print('仅检查链接；没有发评论、补发视频或更改原任务状态。',flush=True)
        return result


def recover_locks(root):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    expected='2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3'
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            url=base+'d8c998c705801c948a230c0504fcb65653ae8086/downloads/recover_resume_new_batch.py'
            with urllib.request.urlopen(url,context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Lock helper checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));break
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    else:raise RuntimeError('锁核验组件下载失败，未启动检查')
    namespace={'__name__':'verified_lock_cleanup_library','__file__':'verified_lock_cleanup.py'}
    exec(compile(data,'verified-lock-cleanup','exec'),namespace);namespace['recover_locks'](root)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        root=Path(sys.argv[1]).resolve()
        if sys.platform!='win32' or upload.ROOT.resolve()!=root:raise ValueError('请在原Windows上传电脑运行')
        recover_locks(root);execute()
    except KeyboardInterrupt:print('只读检查已停止。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
