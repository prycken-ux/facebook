"""Read-only exact post proof on Reels/video tabs when a profile feed will not load."""
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import fb_upload as upload
import published_video_lookup as lookup
import safe_video_comments as comments
from published_post_ui import TimelineProofs

def surfaces(url):
    parsed = urlparse(upload.english_url(url))
    result = [urlunparse(parsed)]
    for tab in ('reels', 'videos'):
        if parsed.path == '/profile.php':
            query = parse_qs(parsed.query)
            query['sk'] = [tab]
            result.append(urlunparse(parsed._replace(query=urlencode(query, doseq=True))))
        else:
            result.append(urlunparse(parsed._replace(path=parsed.path.rstrip('/') + '/' + tab + '/')))
    return result


def standalone_videos(payload, owner, caption, start, end):
    """A Reel-grid Video must carry all its own proof; never borrow a caption."""
    found = set()
    def walk(node):
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            if node.get('__typename') in {'Video', 'Reel'}:
                actor = node.get('owner') or node.get('video_owner')
                message = node.get('message', node.get('description', ''))
                if isinstance(message, dict):
                    message = message.get('text', '')
                try:
                    created = float(node.get('creation_time', node.get('publish_time', 0)))
                except (TypeError, ValueError):
                    created = 0
                vid = str(node.get('id', ''))
                if (isinstance(actor, dict) and str(actor.get('id', '')) == owner
                        and vid.isdecimal() and comments.normalized(message) == comments.normalized(caption)
                        and start <= created < end and node.get('is_published') is True
                        and not node.get('is_pending') and not node.get('is_draft')):
                    links = {'https://www.facebook.com/reel/' + vid}
                    links.update(link for field in ('permalink_url', 'url')
                                 if (link := comments.direct_link(node.get(field, ''))))
                    if len(links) == 1:
                        found.update(links)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)
    walk(payload)
    return found


def find_on_tabs(page, context, entry, caption, start, end, surface_seconds=15, known_links=()):
    observer = lookup.Lookup(context, entry, caption, start, end)
    extra = set()
    ui = set()
    notes = []
    uncertain = False
    def receive(response):
        try:
            parsed = urlparse(response.url)
            if parsed.hostname in {'facebook.com', 'www.facebook.com'} and parsed.path.rstrip('/') == '/api/graphql':
                for payload in lookup.payloads(response.text()):
                    extra.update(standalone_videos(payload, observer.owner, caption, start, end))
        except Exception:
            pass
    context.on('response', receive)
    try:
        for index, url in enumerate(surfaces(entry['url'])[1:], 1):
            print('评论目标备用定位：栏目', index, '/ 2（Reels、视频），只读核验。', flush=True)
            timeline = TimelineProofs(entry, observer.owner, caption, start, end)
            deadline = time.monotonic() + surface_seconds
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=min(15000, max(1, int(surface_seconds * 1000))))
                scrolls = 0
                while time.monotonic() < deadline:
                    upload.checkpoint(page)
                    upload.require_no_advanced_protection(page)
                    for raw in page.locator('script[type="application/json"]').all_text_contents():
                        observer.add(raw)
                        for payload in lookup.payloads(raw):
                            extra.update(standalone_videos(payload, observer.owner, caption, start, end))
                    timeline.poll(page, deadline)
                    if not timeline.unresolved:
                        ui.update(timeline.links)
                    if len(observer.links | extra | ui | set(known_links)) > 1:
                        raise ValueError('发现多个匹配视频，不能确认哪条属于本任务')
                    if scrolls < 4:
                        page.mouse.wheel(0, 650)
                        scrolls += 1
                    page.wait_for_timeout(max(1, min(400, int((deadline-time.monotonic())*1000))))
            except ValueError:
                raise
            except Exception as error:
                notes.append('栏目' + str(index) + '：' + (str(error) or type(error).__name__).split('\n')[0][:180])
            else:
                notes.append('栏目' + str(index) + '：加载中帖子' + str(timeline.stats['loading'])
                             + '，匹配完整文案' + str(timeline.stats['exact_captions']))
            uncertain |= bool(timeline.unresolved)
        links = observer.links | extra | (set() if uncertain else ui)
        if len(links | set(known_links)) > 1:
            raise ValueError('主页与备用栏目的视频证据冲突，未选择评论目标')
        if uncertain and not (observer.links | extra):
            notes.append('仍有同文案帖子缺少可核实的时间或完整展开内容')
        if len(links) > 1:
            raise ValueError('发现多个匹配视频，未猜选结果')
        return (next(iter(links)) if links else None), notes
    finally:
        context.remove_listener('response', receive)
        observer.close()


