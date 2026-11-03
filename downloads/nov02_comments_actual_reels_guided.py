"""Nov-2 comments: actual Reels links, strict direct-video proof, manual selection fallback."""
import ast,hashlib,re,ssl,sys,time,urllib.request
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import parse_qs,urljoin,urlparse
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import safe_video_comments as comments
import published_video_lookup as lookup
import daily_publish_and_comments as daily
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

KNOWN='https://www.facebook.com/reel/1500593451890233'
SCAN=r'''()=>{const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const read=s=>[...document.querySelectorAll(s)].filter(visible).map(e=>e.href);
 return {main:read('main a[href],[role="main"] a[href]'),all:read('a[href]')}}'''


def stamp(value):
    try:
        if isinstance(value,(int,float)) or str(value).replace('.','',1).isdigit():
            result=float(value);return result/1000 if result>1e12 else result
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed.timestamp() if parsed.tzinfo else 0
    except (ValueError,TypeError,OverflowError):return 0


def text(value):return value.get('text','') if isinstance(value,dict) else value if isinstance(value,str) else ''


class Evidence:
    def __init__(self,owner,caption,start,end,link):
        self.owner=owner;self.caption=comments.normalized(caption);self.start=start;self.end=end;self.link=link
        self.vid=urlparse(link).path.rstrip('/').split('/')[-1]
        self.matched=False;self.blocked=False;self.published=False;self.owner_seen=False;self.caption_seen=False;self.time_seen=False;self.nodes=0
    def add(self,payload):
        if self.caption and self.link in lookup.story_videos(payload,self.owner,self.caption,self.start,self.end):
            self.matched=True;self.owner_seen=True;self.caption_seen=True;self.time_seen=True
        def walk(node,blocked=False):
            if isinstance(node,list):
                for child in node:walk(child,blocked)
            elif isinstance(node,dict):
                bad=node.get('is_published') is False or bool(node.get('is_pending')) or bool(node.get('is_draft'))
                inherited=blocked or (node.get('__typename')=='Story' and bad)
                if node.get('__typename') in {'Video','Reel'} and str(node.get('id',''))==self.vid:
                    self.nodes+=1;story=node.get('creation_story',{})
                    if not isinstance(story,dict):story={}
                    story_bad=story.get('is_published') is False or bool(story.get('is_pending')) or bool(story.get('is_draft'))
                    if inherited or bad or story_bad:self.blocked=True
                    owners={str(v['id']) for field in ('owner','video_owner','owning_profile') if isinstance((v:=node.get(field)),dict) and v.get('id')}
                    actors={str(v['id']) for v in story.get('actors',[]) if isinstance(v,dict) and v.get('id')}
                    if owners and owners!={self.owner}:self.blocked=True
                    if actors and actors!={self.owner}:self.blocked=True
                    owned=owners=={self.owner} or not owners and actors=={self.owner}
                    caption=bool(self.caption) and any(comments.normalized(text(v))==self.caption for v in (node.get('message'),node.get('description'),story.get('message')))
                    timed=any(self.start<=stamp(v)<self.end for area in (node,story) for v in (area.get('creation_time'),area.get('publish_time'),area.get('created_time')))
                    for field in ('permalink_url','url'):
                        canonical=comments.direct_link(node.get(field,''))
                        if canonical and canonical!=self.link:self.blocked=True
                    self.owner_seen|=owned;self.caption_seen|=caption;self.time_seen|=timed
                    self.published|=node.get('is_published') is True
                    self.matched|=owned and caption and timed
                for child in node.values():
                    if isinstance(child,(dict,list)):walk(child,inherited)
        walk(payload)
    def diagnostic(self):return dict(video=self.link,nodes=self.nodes,owner=self.owner_seen,caption=self.caption_seen,time=self.time_seen,matched=self.matched,blocked=self.blocked,explicit_published=self.published)


def require_target_author(page,entry):
    comments.require_video_author(page,entry,timeout_ms=3000)
    owners={upload.target_key(entry['url'])}
    if entry.get('type')=='personal':
        owners.update('id:'+c['value'] for c in page.context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and str(c.get('value','')).isdecimal())
    anchors=page.get_by_role('link',name=re.compile(r'^'+re.escape(entry['name'])+r'(?:, see owner profile)?$',re.I))
    for i in range(anchors.count()):
        anchor=anchors.nth(i)
        if not anchor.is_visible() or not anchor.evaluate('''e=>!e.closest('[role="article"][aria-label^="Comment by " i],nav,[role="navigation"]')'''):continue
        try:
            if upload.target_key(urljoin('https://www.facebook.com/',anchor.get_attribute('href') or '')) in owners:return
        except ValueError:pass
    raise ValueError('未看到视频作者的有效主页链接；不使用评论里的作者链接作为视频作者证据')


def inspect_video(page,context,entry,caption,start,end,link,seconds=7):
    owner=upload.target_key(entry['url'])
    if not owner.startswith('id:'):return False,dict(video=link,error='自动核对需要原配置的数字主页编号')
    evidence=Evidence(owner[3:],caption,start,end,link)
    def receive(response):
        try:
            parsed=urlparse(response.url)
            if parsed.hostname in {'facebook.com','www.facebook.com'} and parsed.path.rstrip('/')=='/api/graphql':
                for payload in lookup.payloads(response.text()):evidence.add(payload)
        except Exception:pass
    context.on('response',receive)
    try:
        page.goto(upload.english_url(link),wait_until='domcontentloaded',timeout=20000)
        deadline=time.monotonic()+seconds;since=None
        while time.monotonic()<deadline:
            upload.checkpoint(page);upload.require_no_advanced_protection(page)
            if comments.direct_link(page.url)!=link:raise ValueError('视频页跳转到其他视频')
            for raw in page.locator('script[type="application/json"]').all_text_contents():
                for payload in lookup.payloads(raw):evidence.add(payload)
            if evidence.blocked:break
            if evidence.matched:
                if since is None:since=time.monotonic()
                if time.monotonic()-since>=1:break
            page.wait_for_timeout(200)
        visible_video=any(page.locator('video').nth(i).is_visible() for i in range(page.locator('video').count()))
        editor=page.get_by_role('form',name='Reels',exact=True)
        has_editor=any(editor.nth(i).is_visible() for i in range(editor.count()))
        valid=evidence.matched and not evidence.blocked and (visible_video or evidence.published) and not has_editor
        if valid:require_target_author(page,entry)
        return bool(valid),dict(evidence.diagnostic(),visible_video=visible_video,editor=has_editor)
    except Exception as error:return False,dict(evidence.diagnostic(),error=(str(error) or type(error).__name__).split('\n',1)[0][:300])
    finally:context.remove_listener('response',receive)


def open_actual_reels(page):
    tabs=page.get_by_role('tab',name='Reels',exact=True)
    visible=[tabs.nth(i) for i in range(tabs.count()) if tabs.nth(i).is_visible()]
    if len(visible)!=1:raise ValueError('没有唯一可见的本主页Reels标签')
    visible[0].click(timeout=10000)


def collect_links(page,seconds=8):
    open_actual_reels(page);end=time.monotonic()+seconds;links=set();scrolls=0
    while time.monotonic()<end:
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        scan=page.evaluate(SCAN)
        for value in scan['main'] or scan['all']:
            link=comments.direct_link(value)
            if link:links.add(link)
        if scrolls<3:page.mouse.wheel(0,600);scrolls+=1
        page.wait_for_timeout(350)
    return sorted(links)


def validate_selected(page,entry,raw):
    parsed=urlparse(raw)
    if parsed.scheme!='https' or parsed.hostname not in {'facebook.com','www.facebook.com','m.facebook.com','web.facebook.com','fb.watch'} or parsed.username or parsed.password or parsed.port:
        raise ValueError('请使用Facebook具体视频的https网址')
    normalized=parsed._replace(netloc='www.facebook.com').geturl() if parsed.hostname in {'m.facebook.com','web.facebook.com'} else raw
    canonical=comments.direct_link(normalized)
    if not canonical and not (parsed.hostname=='fb.watch' or re.fullmatch(r'/share/[rv]/[A-Za-z0-9]+/?',parsed.path)):
        raise ValueError('这不是具体视频链接；请打开视频或复制视频分享链接')
    page.goto(upload.english_url(canonical or raw),wait_until='domcontentloaded',timeout=30000)
    end=time.monotonic()+15
    while time.monotonic()<end:
        upload.checkpoint(page);upload.require_no_advanced_protection(page)
        link=comments.direct_link(page.url)
        if link:
            require_target_author(page,entry);return link
        page.wait_for_timeout(250)
    raise ValueError('分享链接未跳转到具体视频，请复制打开后的视频地址')


def manual_choice(page,context,entry,job,baseline):
    print('\n需要你选定这一条原视频：',entry['account'],entry['target'],job['filename'],flush=True)
    print('在浏览器打开对应视频后回到此窗口按回车；也可直接粘贴视频网址。S跳过本条，Q结束。选择后程序自动评论并刷新核验。',flush=True)
    while True:
        raw=input('视频网址/回车读取/S/Q：').strip()
        if raw.upper()=='Q':raise KeyboardInterrupt
        if raw.upper()=='S':raise RuntimeError('用户跳过本条，尚未发送评论')
        if not raw:
            links=set()
            for candidate in context.pages:
                if candidate is page or candidate not in baseline:
                    try:
                        if not candidate.is_closed() and (link:=comments.direct_link(candidate.url)):links.add(link)
                    except Exception:pass
            if len(links)!=1:
                print('未读到唯一视频地址，请先点开正确视频，或直接粘贴该视频网址。',flush=True);continue
            raw=next(iter(links))
        try:return validate_selected(page,entry,raw),'user_supplied_exact_job_link'
        except Exception as error:print('未发送评论：',str(error).split('\n',1)[0],flush=True)


def make_finder(jobs,automatic):
    by_pair={(j['account'],j['target']):j for j in jobs}
    def find(page,context,entry,caption,start,end,timeout_ms=45000,diagnostic_path=None):
        job=by_pair[(entry['account'],entry['target'])];baseline=set(context.pages);proofs=[];matches=[];candidates=[]
        if automatic:
            try:
                candidates=collect_links(page)
                print('从实际Reels入口取得候选视频：',len(candidates),'条；按作者、原文案和时间核对。',flush=True)
                if len(candidates)>12:raise ValueError('候选超过12条，改由你选定，未猜选最新视频')
                for i,link in enumerate(candidates,1):
                    child=context.new_page()
                    try:valid,proof=inspect_video(child,context,entry,caption,start,end,link)
                    finally:child.close()
                    proofs.append(proof);print('只读核对候选',i,'/',len(candidates),'：',valid,flush=True)
                    if valid:matches.append(link)
                if len(matches)==1:
                    page.goto(upload.english_url(matches[0]),wait_until='domcontentloaded',timeout=30000)
                    require_target_author(page,entry)
                    return matches[0],'verified_owner_caption_time'
                print('未取得唯一的完整自动匹配证据，改为你选定视频。',flush=True)
            except Exception as error:print('自动定位未完成：',str(error).split('\n',1)[0],flush=True)
            finally:
                if diagnostic_path:upload.save_json(diagnostic_path,dict(candidates=candidates,matches=matches,proofs=proofs))
        else:
            try:open_actual_reels(page)
            except Exception:pass
        return manual_choice(page,context,entry,job,baseline)
    return find


def download_verified(commit,name,expected):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(base+commit+'/downloads/'+name,context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Script checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));return data
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    raise RuntimeError('校验下载失败，未启动补评论')


def execute():
    from playwright.sync_api import sync_playwright
    if datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()!='2026-11-03':raise ValueError('本指令仅限北京时间11月3日处理11月2日原批次评论')
    base_code=download_verified('9c1108e79f24dfcacd34d1e5cea39e7ec5e53d85','backfill_nov02_published_comments_20261103.py','4fccb2aa3f5249ec18c2fb5a9d953c4763c4d0007e097bc532f2b16d03ec92ec')
    recovery=download_verified('d8c998c705801c948a230c0504fcb65653ae8086','recover_resume_new_batch.py','2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3')
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(recovery,'verified-lock-library','exec'),namespace);namespace['recover_locks'](upload.ROOT)
    base={'__name__':'verified_nov02_comments_library'};exec(compile(base_code,'verified-nov02-comments-library','exec'),base)
    with locked():
        source,value,jobs=base['load_source']();state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        golden=next(j for j in jobs if (j['account'],j['target'])==('fb10','page02'));row=state[golden['key']];entry=daily.configured(golden)
        automatic=False
        try:
            if any(r.get('account')=='fb10' and r.get('status') in {'preparing','posting'} for r in state.values()):raise ValueError('fb10仍有准备/提交中的任务，未关闭窗口；其他账号可继续')
            since=datetime.fromisoformat(row['created']).timestamp()-5
            until=datetime.fromisoformat(row.get('confirmed_batch_lookup_cutoff') or row.get('published_at') or row.get('archived_at') or row['post_intent_at']).timestamp()+60
            close_selected_window('fb10')
            with sync_playwright() as playwright:
                context=upload.launch_context(playwright,entry)
                try:
                    page=context.new_page();page.goto(upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000);upload.ensure_identity(page,entry)
                    child=context.new_page();automatic,diagnostic=inspect_video(child,context,entry,golden['caption_text'],since,until,KNOWN)
                finally:context.close()
        except Exception as error:
            diagnostic=dict(video=KNOWN,error=(str(error) or type(error).__name__).split('\n',1)[0][:300])
            print('只读匹配自检未完成：',diagnostic['error'],'；改为你选定视频。',flush=True)
        upload.save_json(upload.ROOT/'logs/nov02-known-video-matching-proof.json',diagnostic)
        print('已知成功视频的自动文案/时间核对：',automatic,'；只读核对，没有重复评论。',flush=True)
        if not automatic:print('已成功那条评论保持成功；此False仅表示缺少完整自动匹配证据。改为你选定视频、程序自动评论，无需逐条把链接发到聊天。',flush=True)
    original=daily.find_published;daily.find_published=make_finder(jobs,automatic)
    try:return base['execute']()
    finally:daily.find_published=original


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if sys.platform!='win32' or upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原Windows上传电脑运行')
        raise SystemExit(execute())
    except KeyboardInterrupt:print('已结束，成功评论和待核实发送记录均保留；重跑会跳过这些记录。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
