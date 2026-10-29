"""Local Windows uploader based on the user's recorded Page and personal flows."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "upload_config.json"
VERSION = "2.39"
SUCCESS_PATTERN = (
    r"^(?:Your reel (?:is(?: now)?|has been|was) (?:successfully )?"
    r"(?:published|shared|posted)(?: successfully)?|"
    r"Reel (?:published|shared|posted)(?: successfully)?|"
    r"(?:你的|您的)?(?:Reel|短视频)(?:已成功发布|已发布))"
    r"[.!。！]?(?:\s*You can also share to Stories, groups and other places[.!]?)?$"
)

# Install before Post so a short-lived success message cannot disappear before
# the click returns. Ignore old notification cards and unchanged existing text.
RECEIPT_WATCH_JS = r"""pattern => {
    for(const node of document.querySelectorAll('[data-local-current-publication-receipt]'))node.removeAttribute('data-local-current-publication-receipt');
    if (window.__fbUploadWatch && window.__fbUploadWatch.observer) {
        window.__fbUploadWatch.observer.disconnect();
    }
    const rx = new RegExp(pattern, 'i');
    const seen = new WeakMap();
    const watch = {armed: false, message: null, observer: null, receiptLinks: [], receiptArea: null};
    window.__fbUploadWatch = watch;
    const norm = t => (t || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
    function isHistory(el) {
        const historyLabel = /^(Mark as (?:read|unread)|Manage .+ notification)/i;
        for (let p = el; p; p = p.parentElement) {
            const label = p.getAttribute('aria-label') || '';
            if (historyLabel.test(label)) return true;
        }
        // A wrapper can contain exactly the same text as its notification card.
        for (const child of el.querySelectorAll('[aria-label]')) {
            if (historyLabel.test(child.getAttribute('aria-label') || '')) return true;
        }
        return false;
    }
    function inspect(el) {
        if (!el || el.nodeType !== 1) return;
        const text = norm(el.textContent);
        if (text.length > 240 || !rx.test(text)) return;
        const previous = seen.get(el);
        seen.set(el, text);
        if (!watch.armed || text === previous || isHistory(el)) return;
        const receiptArea = el.closest('[role="alert"], [role="status"], [role="dialog"], [aria-live="polite"], [aria-live="assertive"]');
        const heading = el.matches('h1, h2, h3, h4, h5, h6, [role="heading"]');
        if (!(receiptArea || heading) || !el.getClientRects().length) return;
        watch.message = text;
        watch.receiptArea = el.closest('[role="alert"], [role="status"], [role="dialog"], [aria-live]');
        if(watch.receiptArea && (watch.receiptArea===document.body || watch.receiptArea.textContent.length>2000))watch.receiptArea=null;
        if(watch.receiptArea)watch.receiptArea.setAttribute('data-local-current-publication-receipt','true');
    }
    function scan(root) {
        if (!root) return;
        if (root.nodeType === 3) root = root.parentElement;
        if (!root || root.nodeType !== 1) return;
        inspect(root);
        for (const el of root.querySelectorAll('*')) inspect(el);
    }
    scan(document.body);
    watch.observer = new MutationObserver(changes => {
        for (const change of changes) {
            if (change.type === 'characterData') scan(change.target.parentElement);
            for (const node of change.addedNodes) scan(node);
        }
        if(watch.armed && watch.message && watch.receiptArea && watch.receiptArea.isConnected){
          for(const link of watch.receiptArea.querySelectorAll('a[href]')){
            if(/^(?:View|See) (?:your )?reel$/i.test(norm(link.innerText || link.getAttribute('aria-label')))){
              const value=link.href;if(!watch.receiptLinks.includes(value))watch.receiptLinks.push(value);
            }
          }
        }
    });
    watch.observer.observe(document.body, {childList: true, subtree: true, characterData: true});
}"""


def install_receipt_watch(page):
    page.evaluate(RECEIPT_WATCH_JS, SUCCESS_PATTERN)


class ReceiptNeedsReview(RuntimeError):
    """Post was clicked, but no fresh success receipt could be established."""


UPLOAD_ACTIVITY_JS = r"""button => {
    if (!button.getClientRects().length) return {active:false};
    const area=button.closest('[role="dialog"], [role="form"], main') || document.body;
    const rx=/^(Uploading(?:\s+(?:video|reel))?\s*(\d{1,3})\s*%|Posting(?:\.{3}|…)?|Processing(?:\s+(?:video|reel))?(?:\.{3}|…)?)$/i;
    for (const element of area.querySelectorAll('div,span,[role="status"],[role="progressbar"],progress')) {
        const style=getComputedStyle(element);
        if (!element.getClientRects().length || style.visibility==='hidden' || style.display==='none') continue;
        const text=(element.innerText || element.getAttribute('aria-valuetext') || '').replace(/\s+/g,' ').trim();
        const match=rx.exec(text);
        if(match && (match[2]===undefined || Number(match[2])<=100)) return {active:true,label:text};
    }
    return {active:false};
}"""


def visible_upload_activity(page, button):
    from playwright.sync_api import Error as BrowserError
    try:
        result=button.evaluate(UPLOAD_ACTIVITY_JS,timeout=5000)
    except BrowserError:
        checkpoint(page)
        return None
    if (isinstance(result,dict) and result.get('active') is True
            and isinstance(result.get('label'),str)):
        return result['label']
    return None


def wait_for_receipt(page, button, timeout_ms=180000, poll_ms=15000,
                     completion_grace_ms=0, started_at=None):
    """One wall-clock budget for both the fresh receipt and composer dismissal.

    completion_grace_ms is retained for older callers but never extends the cap.
    Uploading/Posting activity does not reset the budget or trigger another Post.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    if timeout_ms<=0 or poll_ms<=0 or completion_grace_ms<0:
        raise ValueError('发布等待参数无效')
    started = time.monotonic() if started_at is None else started_at
    deadline = started + min(timeout_ms, 180000) / 1000
    message = None
    while True:
        checkpoint(page)
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            raise ReceiptNeedsReview('已达到本条发布等待上限（最多 3 分钟）；结果待核实，继续下一个，不自动重发。')
        chunk = max(1, min(poll_ms, remaining_ms))
        try:
            if message is None:
                page.wait_for_function("() => Boolean(window.__fbUploadWatch && window.__fbUploadWatch.message)", timeout=chunk)
                message = page.evaluate("() => window.__fbUploadWatch.message")
                if not isinstance(message, str) or not re.fullmatch(SUCCESS_PATTERN, message, re.I):
                    raise RuntimeError("没有收到本次发布的有效成功提示。")
            # The composer shares the same deadline; success text alone is insufficient.
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                continue
            button.wait_for(state="hidden", timeout=max(1, min(poll_ms, remaining_ms)))
            checkpoint(page)
            return message
        except PlaywrightTimeoutError:
            elapsed = int(time.monotonic() - started)
            print('发布结果仍待确认：已等待', elapsed,
                  '秒；最多 180 秒，到时转待核实并继续下一条，不重复点击 Post。', flush=True)


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def display_status(logs):
    # State files are replaced atomically by writers. Reading a snapshot does
    # not need to acquire, modify, or remove the publication lock.
    state = read_json(logs / "publish_state.json", {})
    if not state:
        print("暂无发布记录。")
    for key, row in state.items():
        print(key[:12], row["account"], row["target"], row["status"], Path(row["video"]).name)
    lock = logs / "upload.lock"
    try:
        value = lock.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return 0
    except (UnicodeError, OSError):
        value = ""
    if value.isdecimal():
        print("锁文件仍存在，锁内进程编号 PID：", int(value))
    else:
        print("锁文件仍存在，暂时无法读取进程编号。")
    print("本次仅查看记录，未删除锁，也未上传或发布。请先确认原任务是否还在运行。")
    return 0


def normalize_video_permalink(url):
    if not url or not re.fullmatch(
        r"https://(?:www\.)?facebook\.com/(?:reel/[0-9]+|[0-9]+/videos/[0-9]+)/?", url
    ):
        raise ValueError("请提供本人核对后的 Facebook /reel/数字 或 /数字/videos/数字 直接视频链接。")
    return url.rstrip("/")


def record_manual_post(entry, state, state_path, video, reel_url):
    validate_entry(entry)
    permalink = normalize_video_permalink(reel_url)
    if video is None:
        raise ValueError("请用 --video 指定这次实际发布的 MP4 文件完整路径。")
    video = Path(video).resolve()
    if not video.is_file() or video.suffix.lower() != ".mp4" or video.stat().st_size == 0:
        raise ValueError("实际发布的视频文件不存在、不是 MP4 或为空文件。")
    key = job_key(entry, video)
    for other_key, row in state.items():
        if other_key != key and str(row.get("permalink", "")).rstrip("/") == permalink:
            raise ValueError("此 Reel 链接已登记到另一个视频；请核对实际文件，未修改记录。")
    existing = state.get(key)
    if existing:
        if (existing.get("account"), existing.get("target")) != (entry["account"], entry["target"]):
            raise ValueError("同一目标和视频已有其他账号的任务记录；未覆盖。")
        old_link = existing.get("permalink")
        if old_link and old_link.rstrip("/") != permalink:
            raise ValueError("此视频已关联不同 Reel 链接，未覆盖原记录。")
        if existing.get("status") == "published" and old_link == permalink:
            print("此手动发布已登记，无需重复操作：", key[:12])
            return key
    if state_path.exists():
        backup = ROOT / "backups" / ("manual-record-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        backup.mkdir(parents=True, exist_ok=False)
        shutil.copy2(state_path, backup / state_path.name)
    now = datetime.now().astimezone().isoformat()
    record = dict(existing or {})
    record.setdefault("created", now)
    record.update({"account": entry["account"], "target": entry["target"], "url": entry["url"],
                   "video": str(video), "caption": str(video.with_suffix(".txt")),
                   "status": "published", "permalink": permalink,
                   "confirmation_method": "user_verified_manual_post", "confirmed_at": now})
    state[key] = record
    save_json(state_path, state)
    print("已登记手动发布成功：", entry["account"], entry["target"], key[:12], video.name)
    print("原文件保留；同一目标下相同视频内容将跳过，改文件名或文案也不会重发。")
    return key


def target_key(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"facebook.com", "www.facebook.com"}:
        raise ValueError("目标必须是 https://www.facebook.com/ 下的主页网址。")
    if parsed.username or parsed.password or parsed.port:
        raise ValueError("主页网址不能包含登录信息或端口。")
    page_id = parse_qs(parsed.query).get("id", [""])[0]
    if page_id:
        if parsed.path != "/profile.php" or not page_id.isdecimal():
            raise ValueError("主页编号或网址格式无效。")
        return "id:" + page_id
    slug = parsed.path.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", slug) or slug.lower() in {
        "login", "checkpoint", "reels", "reel", "watch", "settings", "home.php", "profile.php"
    }:
        raise ValueError("请使用公共主页的直接网址，不要使用 Reel、登录或设置网址。")
    return "slug:" + slug.lower()


def validate_entry(entry):
    for key in ("account", "target"):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", entry[key]):
            raise ValueError("账号和目标编号只能含字母、数字、下划线和短横线。")
    if entry.get("type") not in {"page", "personal"}:
        raise ValueError("目标类型必须是 page 或 personal。")
    if entry["type"] == "personal" and (entry["target"] != "personal" or
                                          entry.get("workflow") != "personal_recording_v1"):
        raise ValueError("个人主页需通过 setup_personal.py 登记录制流程，并使用 personal 目标。")
    if not entry.get("name", "").strip():
        raise ValueError("请填写目标主页名称。")
    target_key(entry["url"])


def inbox_for(entry):
    return ROOT / "videos" / entry["account"] / entry["target"] / "inbox"


def job_key(entry, video):
    digest = hashlib.sha256()
    digest.update(target_key(entry["url"]).encode("utf-8"))
    digest.update(b"\0")
    with video.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    # Caption and filename changes must not cause the same video to post twice.
    return digest.hexdigest()


def queue_order(path):
    parts = tuple((1, int(part)) if part.isdecimal() else (0, part.casefold())
                  for part in re.split(r'([0-9]+)', path.name))
    return parts, path.name.casefold(), path.name


def pending_jobs(entry, state):
    folder = inbox_for(entry)
    excluded = {name.lower() for name in entry.get("excluded_files", [])}
    for video in sorted(folder.glob("*.mp4"), key=queue_order):
        if video.name.lower() in excluded:
            print("跳过录制时使用的视频：", video.name)
            continue
        caption = video.with_suffix(".txt")
        if not caption.is_file():
            print("缺少同名 TXT，跳过：", video.name)
            continue
        if video.stat().st_size == 0:
            print("空视频，跳过：", video.name)
            continue
        # Producers should copy under a .part extension and rename when complete.
        if datetime.now().timestamp() - max(video.stat().st_mtime, caption.stat().st_mtime) < 60:
            print("文件刚刚更新，留到下一次检查：", video.name)
            continue
        text = caption.read_text(encoding="utf-8-sig").strip()
        if not text:
            print("文案为空，跳过：", caption.name)
            continue
        key = job_key(entry, video)
        if key not in state:
            yield key, video, caption, text
        else:
            print("已有任务记录，不重复发布：", video.name, state[key]["status"])


def validate_video_filename(filename):
    if (not isinstance(filename, str) or not filename or filename != filename.strip()
            or any(ord(char) < 32 or ord(char) == 127 or char in '<>:"/\\|?*' for char in filename)
            or Path(filename).suffix.lower() != '.mp4'
            or not Path(filename).stem
            or Path(filename).stem.split('.')[0].upper() in
               {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}):
        raise ValueError('需填写有效 MP4 文件名，支持中文，不能包含路径、控制字符或 Windows 保留名称。')


def named_job(entry, state, filename):
    """Resolve exactly one inbox file; never fall back to another queued video."""
    validate_video_filename(filename)
    folder = inbox_for(entry)
    video = folder / filename
    if not video.is_file():
        completed = folder.parent / "completed"
        for archived in completed.rglob(filename):
            if not archived.is_file() or not archived.stat().st_size:
                continue
            row = state.get(job_key(entry, archived), {})
            if (row.get("account"), row.get("target"), row.get("status")) == (
                    entry["account"], entry["target"], "published"):
                print("指定视频已发布并归档，跳过：", entry["account"], filename)
                return None
        raise ValueError("待发布文件夹缺少指定视频：" + str(video))
    if video.stat().st_size == 0:
        raise ValueError("指定视频为空：" + str(video))
    key = job_key(entry, video)
    if key in state:
        row = state[key]
        if (row.get("account"), row.get("target"), row.get("status")) == (
                entry["account"], entry["target"], "published"):
            print("指定视频内容已有成功记录，跳过：", entry["account"], filename)
            return None
        raise ValueError("指定视频已有任务记录（" + str(row.get("status")) + "），请先核对；不会重发。")
    if filename.lower() in {name.lower() for name in entry.get("excluded_files", [])}:
        raise ValueError("指定视频在排除名单中：" + filename)
    caption = video.with_suffix(".txt")
    if not caption.is_file():
        raise ValueError("指定视频缺少同名 TXT：" + str(caption))
    if datetime.now().timestamp() - max(video.stat().st_mtime, caption.stat().st_mtime) < 60:
        raise ValueError("指定文件刚刚更新，请复制完成至少 60 秒后再运行：" + filename)
    text = caption.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise ValueError("指定视频的文案为空：" + str(caption))
    return key, video, caption, text


def checkpoint(page):
    if any(part in page.url for part in ("/checkpoint", "/login", "/two_step_verification")):
        raise RuntimeError("遇到登录或安全验证。请本人处理，程序不会跳过验证。")


def english_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["locale"] = ["en_US"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def navigate_profile(page, url):
    """Retry one transient GET before file selection, never an editor or Post."""
    from playwright.sync_api import Error as BrowserError, TimeoutError as BrowserTimeout

    # Limit recovery to configured profile routes and the ownership-check route.
    target_key(url)
    destination = english_url(url)
    for attempt in range(2):
        try:
            response = page.goto(destination, wait_until='domcontentloaded', timeout=90000)
        except BrowserError as error:
            message = str(error)
            # Security/login redirects must be handled by the account owner.
            checkpoint(page)
            transient = isinstance(error, BrowserTimeout) or any(code in message for code in
                ('net::ERR_TIMED_OUT', 'net::ERR_CONNECTION_RESET', 'net::ERR_CONNECTION_CLOSED'))
            if attempt or not transient or page.is_closed():
                raise
            print('主页首次加载遇到临时网络错误，2 秒后只重试打开一次；尚未选择视频。', flush=True)
            page.wait_for_timeout(2000)
            checkpoint(page)
            continue
        checkpoint(page)
        return response


def require_english_interface(page):
    language = (page.locator("html").get_attribute("lang") or "").strip().lower().replace("_", "-")
    if language and language != "en" and not language.startswith("en-"):
        raise RuntimeError("Facebook 界面仍不是英语。请在此账号的 Facebook 设置中将界面语言改为 English (US)，再执行 prepare；未选择视频或点击发布。")


def ensure_personal_public_audience(page):
    from playwright.sync_api import expect

    settings = page.get_by_role("dialog", name="Reel settings", exact=True)
    expect(settings).to_be_visible(timeout=240000)
    expect(settings.get_by_role("textbox", name="Describe your reel...", exact=True)).to_be_visible(timeout=240000)
    # Audience controls may be outside the upload form and render later than
    # the caption field. Wait in the settings dialog, not in the file form.
    choice = settings.get_by_role("button", name=re.compile(r"^(Public|Friends)\b"))
    try:
        expect(choice).to_be_visible(timeout=60000)
    except Exception:
        raise RuntimeError("Reel settings 中未找到已加载的 Public/Friends 可见范围选项；未填写文案或点击发布。") from None
    public = settings.get_by_role("button", name=re.compile(r"^Public\b"))
    if public.count() == 1 and public.is_visible():
        return
    friends = settings.get_by_role("button", name=re.compile(r"^Friends\b"))
    expect(friends).to_be_visible(timeout=30000)
    friends.click()
    option = page.get_by_role("radio", name=re.compile(r"^Public Anyone on or off"))
    expect(option).to_be_visible(timeout=30000)
    option.check()
    expect(option).to_be_checked()
    page.get_by_role("button", name="Done", exact=True).click()
    expect(public).to_be_visible(timeout=30000)
    print("已将本条 Reel 的可见范围切换为 Public。", flush=True)


HEADER_MANAGEMENT_JS = r"""(heading, kind) => {
    const norm = text => (text || '').replace(/\s+/g, ' ').trim();
    const controls = kind === 'personal'
        ? /^(Edit profile|编辑个人资料|编辑个人主页|Professional dashboard|专业仪表板|专业面板)$/i
        : /^(Edit|Edit Page|Edit profile|编辑|编辑主页|Professional dashboard|专业仪表板|专业面板)$/i;
    // Never climb into the app-wide wrapper containing the management sidebar.
    // That sidebar is also shown while using the personal identity.
    for (let area = heading.parentElement; area && area !== document.body; area = area.parentElement) {
        if (/Manage Page|管理主页|管理公共主页/i.test(area.innerText || '')) break;
        if (area.querySelector('[role="feed"], [role="article"]')) break;
        for (const el of area.querySelectorAll('button, a, [role="button"], [role="link"]')) {
            const label = norm(el.getAttribute('aria-label') || el.innerText);
            const style = getComputedStyle(el);
            if (controls.test(label) && el.getClientRects().length &&
                style.visibility !== 'hidden' && style.display !== 'none' &&
                !el.disabled && el.getAttribute('aria-disabled') !== 'true') {
                return kind === 'personal' ? 'active_personal_header_management_control' : 'active_page_header_management_control';
            }
        }
    }
    return null;
}"""


def page_actor_matches(page, entry):
    # Inspect only the local Page actor identifier. Never print, persist, or
    # return any cookie values, including session credentials.
    try:
        actors = {cookie["value"] for cookie in page.context.cookies(["https://www.facebook.com/"])
                  if cookie.get("name") == "i_user" and cookie.get("value")}
    except Exception:
        raise RuntimeError("无法在本地核对当前主页身份；未点击发布。") from None
    if not actors:
        return False
    target = target_key(entry["url"])
    if not target.startswith("id:"):
        raise RuntimeError("身份核对需要含数字 id 的公共主页网址；未点击发布。")
    if actors != {target[3:]}:
        raise RuntimeError("当前浏览器的发布身份与目标公共主页不一致；未选择视频或点击发布。")
    return True


PROFILE_NAME_ALLOWED_JS = r"""element => !element.closest(
    'article,[role="article"],[role="feed"],nav,[role="navigation"],aside,' +
    '[role="complementary"],[role="banner"],[role="dialog"],[role="alertdialog"]')"""


class ProfileNameNotReady(RuntimeError):
    pass


def profile_name_candidates(page, entry):
    """Use real profile headings, or new personal name text beside Edit profile.

    Names in articles, feeds, menus or management sidebars are not proof. This
    function only establishes loaded profile UI; cookie/owner validation remains
    mandatory in the callers, including the /me check for vanity profiles.
    """
    from playwright.sync_api import TimeoutError as BrowserTimeout

    candidates = []
    headings = page.get_by_role('heading', name=entry['name'], exact=True)
    for index in range(headings.count()):
        candidate = headings.nth(index)
        try:
            if candidate.is_visible() and candidate.evaluate(PROFILE_NAME_ALLOWED_JS, timeout=1000):
                candidates.append(candidate)
        except BrowserTimeout:
            continue
    if entry.get('type') in {'personal','page'} and not candidates:
        kind=entry['type']
        labels = page.get_by_text(entry['name'], exact=True)
        for index in range(labels.count()):
            candidate = labels.nth(index)
            try:
                if (candidate.is_visible() and candidate.evaluate(PROFILE_NAME_ALLOWED_JS, timeout=1000)
                        and candidate.evaluate(HEADER_MANAGEMENT_JS, kind, timeout=1000) == 'active_'+kind+'_header_management_control'):
                    candidates.append(candidate)
            except BrowserTimeout:
                continue
    return candidates


def wait_profile_name(page, entry, timeout_ms=90000):
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        checkpoint(page)
        candidates = profile_name_candidates(page, entry)
        if candidates:
            return candidates[0]
        if time.monotonic() >= deadline:
            raise ProfileNameNotReady('未加载出目标主页名称及有效顶部区域：' + entry['name'])
        page.wait_for_timeout(min(200, max(1, (deadline - time.monotonic()) * 1000)))


def visible_page_switch(page):
    pattern = re.compile(r'^(Switch Now|立即切换|现在切换)$', re.I)
    # A switch can be a button or link. The text fallback retains the recorded
    # layout while requiring one visible, unambiguous known switching action.
    for choices in (page.get_by_role('button', name=pattern), page.get_by_role('link', name=pattern),
                    page.get_by_text(pattern)):
        visible = [choices.nth(i) for i in range(choices.count()) if choices.nth(i).is_visible()]
        if len(visible) > 1:
            raise RuntimeError('找到多个公共主页切换入口，请手动确认；未选择视频或点击发布。')
        if visible:
            return visible[0]
    return None


def ensure_page_identity(page, entry, timeout_ms=90000, picker_delay_ms=2000):
    from playwright.sync_api import TimeoutError as BrowserTimeout

    deadline = time.monotonic() + timeout_ms / 1000
    started = time.monotonic()
    switched, announced, picker_used = False, False, False
    actor_error = None
    banner = page.get_by_text(re.compile(r'^Switch into .+ to start managing it\.?$', re.I))
    while True:
        checkpoint(page)
        if target_key(page.url) != target_key(entry['url']):
            raise RuntimeError('浏览器跳转到了不同主页；未选择视频或点击发布。')
        candidates = profile_name_candidates(page, entry)
        method = None
        if candidates:
            switch = visible_page_switch(page)
            if switch is not None:
                if switched:
                    # A pending switch can render briefly during navigation;
                    # never keep clicking it or claim that absence proves success.
                    method = None
                else:
                    print('正在切换到目标公共主页身份：', entry['name'], flush=True)
                    switch.click(timeout=min(10000, max(1, (deadline - time.monotonic()) * 1000)))
                    switched = True
            elif not any(banner.nth(i).is_visible() for i in range(banner.count())):
                try:
                    method = 'page_actor_id_match' if page_actor_matches(page, entry) else None
                    actor_error = None
                    if method is None:
                        for candidate in candidates:
                            try:
                                if candidate.evaluate(HEADER_MANAGEMENT_JS, timeout=1000) == 'active_page_header_management_control':
                                    method = 'active_page_header_management_control'
                                    break
                            except BrowserTimeout:
                                continue
                except RuntimeError as error:
                    # A different active Page cannot be accepted via a generic
                    # management control; allow a delayed Switch Now to arrive.
                    actor_error = error
        if (method is None and candidates and not switched and not picker_used
                and (time.monotonic() - started) * 1000 >= picker_delay_ms
                and deadline - time.monotonic() >= 1):
            from page_profile_switch import switch_page_from_picker
            picker_used = True
            switch_page_from_picker(page, entry, timeout_ms=int((deadline - time.monotonic()) * 1000))
            switched = True
            actor_error = None
            continue
        if method:
            checkpoint(page)
            if target_key(page.url) != target_key(entry['url']):
                raise RuntimeError('切换后主页网址与配置不同，已停止。')
            print('主页身份检查通过：', entry['name'], entry['url'], flush=True)
            proof = {'target_url': entry['url'], 'name': entry['name'], 'switched': switched, 'method': method}
            if picker_used:
                proof['switch_method'] = 'profile_picker'
            return proof
        if time.monotonic() >= deadline:
            if actor_error is not None:
                raise actor_error
            raise RuntimeError('等待主页加载和身份切换后仍无法确认公共主页身份；未选择视频或点击发布。')
        if not announced:
            print('等待主页加载、管理按钮或 Switch Now 切换入口：', entry['name'], flush=True)
            announced = True
        page.wait_for_timeout(min(250, max(1, (deadline - time.monotonic()) * 1000)))


class PageActorActive(RuntimeError):
    pass


def personal_actor_fingerprint(page, entry):
    # Compare identity metadata only in memory; no cookie values enter logs.
    try:
        cookies = page.context.cookies(["https://www.facebook.com/"])
        people = {c["value"] for c in cookies if c.get("name") == "c_user" and c.get("value")}
        actors = {c["value"] for c in cookies if c.get("name") == "i_user" and c.get("value")}
    except Exception:
        raise RuntimeError("无法在本地核对个人主页登录身份；未点击发布。") from None
    if len(people) != 1 or not next(iter(people)).isdecimal():
        raise RuntimeError("无法确认个人账号登录身份，请在该账号窗口重新检查登录。")
    if actors and actors != people:
        raise PageActorActive("当前仍是公共主页身份，请先手动切回登录者个人主页；未选择视频或点击发布。")
    target = target_key(entry["url"])
    if target.startswith("id:") and people != {target[3:]}:
        raise RuntimeError("登录的个人账号与目标个人主页不一致；未选择视频或点击发布。")
    return hashlib.sha256(("personal:" + next(iter(people))).encode("ascii")).hexdigest()


def verify_personal_vanity_owner(page, entry, marker):
    # Facebook's /me route resolves the logged-in person's own profile. This
    # proves ownership even when a responsive layout hides Edit profile.
    navigate_profile(page, "https://www.facebook.com/me")
    page.wait_for_url(lambda url: urlparse(str(url)).path.rstrip("/") != "/me", timeout=60000)
    checkpoint(page)
    if personal_actor_fingerprint(page, entry) != marker:
        raise RuntimeError("核对本人主页期间登录身份变化，已停止；未选择视频或点击发布。")
    wait_profile_name(page, entry)
    own_key = target_key(page.url)
    expected_key = target_key(entry["url"])
    verified = own_key == expected_key
    if not verified and own_key.startswith("id:"):
        own_marker = hashlib.sha256(("personal:" + own_key[3:]).encode("ascii")).hexdigest()
        canonical = page.locator('link[rel="canonical"]')
        if own_marker == marker and canonical.count() == 1:
            try:
                verified = target_key(canonical.get_attribute("href") or "") == expected_key
            except ValueError:
                verified = False
    if not verified:
        raise RuntimeError("无法通过 Facebook 本人主页入口确认目标短网址属于当前账号；未选择视频或点击发布。")
    navigate_profile(page, entry["url"])
    checkpoint(page)
    wait_profile_name(page, entry)
    if target_key(page.url) != expected_key:
        raise RuntimeError("返回后目标个人主页网址变化，已停止。")


def ensure_personal_identity(page, entry):
    checkpoint(page)
    try:
        marker = personal_actor_fingerprint(page, entry)
    except PageActorActive:
        if not entry.get('auto_switch_personal', False):
            raise
        from page_profile_switch import switch_personal_from_picker
        switch_personal_from_picker(page, entry)
        marker = personal_actor_fingerprint(page, entry)
    wait_profile_name(page, entry)
    if target_key(page.url) != target_key(entry["url"]):
        raise RuntimeError("浏览器网址与目标个人主页不同；未选择视频或点击发布。")
    method = "personal_actor_id_match"
    if target_key(entry["url"]).startswith("slug:"):
        verify_personal_vanity_owner(page, entry, marker)
        method = "personal_me_redirect_match"
    if personal_actor_fingerprint(page, entry) != marker:
        raise RuntimeError("个人主页身份检查过程中登录身份变化，已停止。")
    print("个人主页身份检查通过：", entry["name"], entry["url"], flush=True)
    return {"target_url": entry["url"], "name": entry["name"], "method": method,
            "session_marker": marker}


def ensure_identity(page, entry):
    if entry.get("type") == "personal":
        return ensure_personal_identity(page, entry)
    return ensure_page_identity(page, entry)


def recheck_publish_identity(page, entry, proof):
    checkpoint(page)
    if entry.get("type") == "personal":
        if personal_actor_fingerprint(page, entry) != proof.get("session_marker"):
            raise RuntimeError("准备视频后个人登录身份已变化；未点击发布。")
    else:
        actor_matches = page_actor_matches(page, entry)
        if proof["method"] == "page_actor_id_match" and not actor_matches:
            raise RuntimeError("准备视频后当前主页身份信息已变化；未点击发布。")


def check_identity(entry):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = launch_context(playwright, entry)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            navigate_profile(page, entry["url"])
            require_no_advanced_protection(page)
            result = ensure_identity(page, entry)
            result["checked_at"] = datetime.now().astimezone().isoformat()
            upload_log = ROOT / "logs" / ("identity-" + entry["account"] + "-" + entry["target"] + ".json")
            save_json(upload_log, result)
            print("仅检查和切换主页身份；没有上传或发布视频。")
        finally:
            context.close()


class ReelEntryNotReady(RuntimeError):
    """No Reel activation or file selection occurred while waiting for the menu."""


def wait_reel_button_ready(page, reel_button, timeout_ms=120000):
    deadline=time.monotonic()+timeout_ms/1000
    next_log=0
    while True:
        checkpoint(page)
        require_no_advanced_protection(page)
        modals=page.locator('[role="dialog"]:visible,[role="alertdialog"]:visible,dialog:visible')
        menu=page.get_by_role('dialog',name='Menu',exact=True)
        if modals.count() and not (modals.count()==1 and menu.count()==1 and menu.is_visible()):
            raise RuntimeError('等待 Reel 入口时出现未知弹窗，未选择或发布视频。')
        count=reel_button.count()
        if count>1:
            raise RuntimeError('Reel 入口不唯一，未选择或发布视频。')
        if count==1 and reel_button.is_visible() and reel_button.is_enabled():
            return
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise ReelEntryNotReady('Facebook 菜单仍未加载出可用的 Reel 按钮；尚未选择视频或点击 Post。')
        if time.monotonic()>=next_log:
            print('等待 Facebook 菜单加载完成、Reel 按钮可用；尚未选择或发布视频。',flush=True)
            next_log=time.monotonic()+15
        page.wait_for_timeout(min(250,max(1,int(remaining*1000))))


def select_reel_video(page, reel_button, video, timeout_ms=60000, entry_timeout_ms=120000):
    from playwright.sync_api import TimeoutError as BrowserTimeout
    # Five seconds is a pointer-action timeout, not a menu-loading deadline.
    # Keep readiness outside the filechooser listener: recovery may only occur
    # here, before any Reel activation or automatic file selection.
    wait_reel_button_ready(page,reel_button,entry_timeout_ms)
    # Some Pages open a native picker directly from Reel; others first expose
    # the recorded Reels form. Register before clicking to cover both flows.
    selected = {"method": None, "error": None, "started": False}
    source = str(video.resolve())

    def choose_native(chooser):
        if selected["started"]:
            return
        selected["started"] = True
        try:
            chooser.set_files(source, timeout=timeout_ms)
            selected["method"] = "native_file_chooser"
        except Exception as error:
            selected["error"] = error

    page.on("filechooser", choose_native)
    try:
        require_no_advanced_protection(page)
        try:
            reel_button.click(timeout=min(timeout_ms,5000))
        except BrowserTimeout:
            # A real chooser or form may already have opened before click's
            # wait timed out; never trigger a second selection in that case.
            field=page.get_by_role('form',name='Reels',exact=True).locator('input[type="file"]')
            field_count=field.count()
            if not selected['started'] and field_count==0:
                require_no_advanced_protection(page)
                if reel_button.count()!=1 or not reel_button.is_visible() or not reel_button.is_enabled():
                    raise
                modals=page.locator('[role="dialog"]:visible,[role="alertdialog"]:visible,dialog:visible')
                menu=page.get_by_role('dialog',name='Menu',exact=True)
                if modals.count() and not (modals.count()==1 and menu.count()==1 and menu.is_visible()):
                    raise RuntimeError('Reel 入口被未知弹窗遮挡，未选择视频。')
                if not reel_button.evaluate("e => e.matches('button,a[href],input') || e.hasAttribute('tabindex')"):
                    raise
                print('Reel 鼠标入口被遮挡，改用键盘激活同一个已确认的 Reel 按钮。',flush=True)
                reel_button.focus(timeout=min(timeout_ms,5000))
                from playwright.sync_api import expect
                expect(reel_button).to_be_focused(timeout=min(timeout_ms,5000))
                if not selected['started']:
                    reel_button.press('Enter',timeout=min(timeout_ms,5000))
        deadline = time.monotonic() + timeout_ms / 1000
        while not selected["method"] and selected["error"] is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if selected["started"]:
                page.wait_for_timeout(min(100, max(1, int(remaining * 1000))))
                continue
            checkpoint(page)
            field = page.get_by_role("form", name="Reels", exact=True).locator('input[type="file"]')
            count = field.count()
            if selected["started"]:
                continue
            if count > 1:
                raise RuntimeError("Reels 表单有多个文件输入框，无法唯一选择，已停止。")
            if count == 1:
                selected["started"] = True
                field.set_input_files(source, timeout=max(1, int(remaining * 1000)))
                selected["method"] = "reels_form_file_input"
                break
            page.wait_for_timeout(min(100, max(1, int(remaining * 1000))))
        if selected["error"] is not None:
            raise RuntimeError("自动选择视频失败，未点击发布：" + str(selected["error"])) from selected["error"]
        if not selected["method"]:
            raise RuntimeError("未捕获到选文件窗口，也未找到 Reels 上传框；未点击发布。")
        print("已自动选择视频：", video.name, selected["method"], flush=True)
        return selected["method"]
    finally:
        page.remove_listener("filechooser", choose_native)


MODERN_CAPTION_JS = r"""() => {
    const marker = 'data-local-upload-caption';
    for (const el of document.querySelectorAll('[' + marker + ']')) el.removeAttribute(marker);
    const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
    const norm = text => (text || '').replace(/\s+/g, ' ').trim();
    const editable = '[contenteditable="true"], textarea';
    const found = new Set();
    for (const seed of document.querySelectorAll('div, span, [aria-placeholder], [data-placeholder]')) {
        if (!visible(seed)) continue;
        const label = seed.getAttribute('aria-placeholder') || seed.getAttribute('data-placeholder') || seed.textContent;
        if (norm(label) !== 'Describe your reel...') continue;
        let area = seed;
        for (let depth = 0; area && area !== document.body && depth < 6; depth++, area = area.parentElement) {
            const candidates = [...area.querySelectorAll(editable)].filter(visible);
            if (area.matches(editable) && visible(area)) candidates.push(area);
            if (candidates.length) {
                for (const el of candidates) found.add(el);
                break;
            }
        }
    }
    if (found.size === 1) [...found][0].setAttribute(marker, 'true');
    return found.size;
}"""


def wait_reel_layout(page, timeout_ms=90000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        checkpoint(page)
        if urlparse(page.url).path.rstrip("/") == "/reels/create":
            return "modern"
        form = page.get_by_role("form", name="Reels", exact=True)
        next_button = page.get_by_role("button", name="Next", exact=True)
        if form.count() == 1 and form.is_visible() and next_button.count() == 1 and next_button.is_visible():
            return "classic"
        page.wait_for_timeout(100)
    raise RuntimeError("选择视频后未识别到已录制的 Reel 编辑界面，未点击发布。")


def modern_caption_field(page, timeout_ms=90000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        field = page.get_by_role("textbox", name="Describe your reel...", exact=True)
        if field.count() == 1 and field.is_visible():
            return field
        count = page.evaluate(MODERN_CAPTION_JS)
        if count == 1:
            return page.locator('[data-local-upload-caption="true"]')
        if count > 1:
            raise RuntimeError("新版描述位置关联多个可编辑区域，无法唯一填写，未点击发布。")
        page.wait_for_timeout(100)
    raise RuntimeError("未找到新版 Describe your reel 描述框，未点击发布。")


def verify_caption(field, text):
    from playwright.sync_api import expect

    if field.evaluate("e => 'value' in e"):
        expect(field).to_have_value(text)
    else:
        # Rich editors represent line breaks as block elements or <br> nodes.
        # Check their rendered text so multiline captions retain those breaks.
        expect(field).to_have_text(text, use_inner_text=True)


def fill_caption(field, text):
    from playwright.sync_api import expect

    field.fill(text, timeout=240000)
    verify_caption(field, text)
    # Facebook's hashtag suggestions can cover AI/Next controls while the
    # caption retains focus. Blur just this editor instead of selecting a
    # suggestion, pressing Escape (which can close the composer), or bypassing
    # pointer checks. Verify the committed text, including links, afterward.
    field.blur(timeout=30000)
    expect(field).not_to_be_focused()
    verify_caption(field, text)


def set_ai_label(page, entry, modern=False):
    """Set and verify the requested state, including a previously enabled OFF."""
    from playwright.sync_api import expect

    desired = bool(entry.get("ai_label", False))
    if modern:
        label = page.get_by_role("button", name=re.compile(r"^Add AI label"))
        toggle = label.get_by_label(re.compile(r"^(Off|On)$"))
        expect(toggle).to_be_visible(timeout=30000)
    elif entry.get("type") == "personal":
        toggle = page.get_by_role("switch", name="Add AI label", exact=True)
    else:
        label = page.get_by_role("button", name=re.compile(r"^Add AI label We require you"))
        indicator = label
        attribute = "aria-checked"
        current = label.get_attribute(attribute)
        if current is None:
            attribute = "aria-pressed"
            current = label.get_attribute(attribute)
        if current is None:
            switches = label.get_by_role("switch")
            if switches.count() == 1:
                indicator, attribute = switches, "aria-checked"
                current = indicator.get_attribute(attribute)
        if current not in {"true", "false"}:
            raise RuntimeError("无法确认 AI 标签开关状态；未点击发布。")
        expected = "true" if desired else "false"
        if current != expected:
            label.click()
        expect(indicator).to_have_attribute(attribute, expected)
        print("AI 标签已核对：", "开启" if desired else "关闭", flush=True)
        return
    if desired:
        toggle.check()
        expect(toggle).to_be_checked()
    else:
        toggle.uncheck()
        expect(toggle).not_to_be_checked()
    print("AI 标签已核对：", "开启" if desired else "关闭", flush=True)


def advance_modern_reel(page,text,timeout_ms=90000,retry_after_ms=3000):
    """Require the Settings UI; one retry is allowed only in proven Edit UI."""
    next_button=page.get_by_role('button',name='Next',exact=True)
    next_button.click(timeout=min(timeout_ms,30000))
    started=time.monotonic()
    deadline=started+timeout_ms/1000
    retried=False
    while True:
        checkpoint(page)
        require_no_advanced_protection(page)
        audience=page.get_by_role('button',name=re.compile(r'^Post audience\b'))
        visible=[audience.nth(i) for i in range(audience.count()) if audience.nth(i).is_visible()]
        if len(visible)>1:
            raise RuntimeError('存在多个公开范围控件，未猜选或发布。')
        if visible:
            return
        if time.monotonic()>=deadline:
            raise RuntimeError('点 Next 后未确认进入 Settings；保留原视频，未点击发布。')
        navigation=page.get_by_role('navigation',name='Reel creation steps',exact=True)
        settings=navigation.get_by_role('button',name='Settings',exact=True)
        # In the supplied stalled Edit screenshot, Settings is a navigation
        # button while Edit is plain current-step text. Never retry a generic
        # Next from a different editor state or reset/reselect the media.
        editing=(navigation.count()==1 and navigation.is_visible() and settings.count()==1 and settings.is_visible()
                 and navigation.get_by_role('button',name='Edit',exact=True).count()==0)
        if (not retried and editing and (time.monotonic()-started)*1000>=retry_after_ms
                and next_button.count()==1 and next_button.is_visible() and next_button.is_enabled()):
            verify_caption(modern_caption_field(page,timeout_ms=min(3000,max(1,int((deadline-time.monotonic())*1000)))),text)
            retried=True
            print('仍在 Edit 且 Next 可用，核对文案后仅重试一次 Next。',flush=True)
            next_button.click(timeout=min(10000,max(1,int((deadline-time.monotonic())*1000))))
        page.wait_for_timeout(100)


def prepare_modern_reel(page, entry, text):
    from playwright.sync_api import expect

    field = modern_caption_field(page)
    fill_caption(field, text)
    advance_modern_reel(page,text)
    checkpoint(page)
    audience = page.get_by_role("button", name=re.compile(r"^Post audience\b"))
    expect(audience).to_be_visible(timeout=60000)
    set_ai_label(page, entry, modern=True)
    # Facebook renders separate label/value nodes whose textContent is
    # "Post audiencePublic". Its accessible name retains the separation.
    expect(audience).to_be_enabled(timeout=240000)
    public_audience = page.get_by_role(
        "button", name=re.compile(r"^Post audience(?:\s+Post audience)?\s+Public$")
    )
    if public_audience.count() == 1 and public_audience.is_visible():
        print("本条 Reel 已是 Public，保留当前公开范围。", flush=True)
    else:
        friends_audience = page.get_by_role(
            "button", name=re.compile(r"^Post audience(?:\s+Post audience)?\s+Friends$")
        )
        if friends_audience.count() != 1 or not friends_audience.is_visible():
            raise RuntimeError("新版 Reel 未显示已识别的 Public/Friends 范围，未点击发布。")
        friends_audience.click()
        public = page.get_by_role("radio", name=re.compile(r"^Public Anyone on or off"))
        expect(public).to_be_visible(timeout=30000)
        public.check()
        expect(public).to_be_checked()
        page.get_by_role("button", name="Done", exact=True).click()
    expect(audience).to_have_accessible_name(
        re.compile(r"^Post audience(?:\s+Post audience)?\s+Public$"), timeout=30000
    )
    button = page.get_by_role("button", name="Post", exact=True)
    expect(button).to_be_enabled(timeout=240000)
    print("新版 Reel 检查通过：TXT 文案已填写，Public 和所需 AI 标签已核对。", flush=True)
    return button


class AccountActionRequired(RuntimeError):
    pass


def require_no_advanced_protection(page):
    title=re.compile(r'^Your account needs Advanced Protection$',re.I)
    for role in ('dialog','alertdialog'):
        dialogs=page.get_by_role(role).filter(has=page.get_by_text(title))
        if any(dialogs.nth(i).is_visible() for i in range(dialogs.count())):
            raise AccountActionRequired('Facebook 要求账号本人处理 Advanced Protection／通行密钥提示；尚未选择或发布视频，程序不会代改安全设置。')


def open_facebook_menu(page, click_timeout_ms=5000, keyboard_timeout_ms=5000):
    """Use the known menu's accessible keyboard action if a nonmodal banner blocks its pointer."""
    from playwright.sync_api import expect, TimeoutError as PlaywrightTimeoutError
    prompt = page.get_by_role("alertdialog", name="Push notifications request", exact=True)
    require_no_advanced_protection(page)

    def dismiss_prompt():
        from playwright.sync_api import expect

        if prompt.count() != 1:
            raise RuntimeError("通知请求弹窗不唯一，需手动处理，未打开上传入口。")
        decline = prompt.get_by_role("button", name=re.compile(r"^(?:Not now|Don't allow|Close)$", re.I))
        visible = [decline.nth(index) for index in range(decline.count()) if decline.nth(index).is_visible()]
        # Leave ambiguous choices to the user. Never press Allow/Turn on or
        # dismiss an unrelated modal.
        if len(visible) != 1:
            raise RuntimeError("推送通知弹窗没有唯一的 Not now / Don't allow / Close 按钮；请手动关闭后重试。")
        visible[0].click()
        expect(prompt).to_be_hidden(timeout=5000)
        print("已关闭 Facebook 推送通知请求，继续打开菜单。", flush=True)

    if prompt.is_visible():
        dismiss_prompt()
    # Also handle a prompt appearing between the check above and menu.click().
    # Scope this handler to the menu step; it must not act during Post/receipt.
    page.add_locator_handler(prompt, dismiss_prompt)
    try:
        menu = page.get_by_role("button", name=re.compile(r"^(Facebook menu|Menu)$", re.I))

        def opened():
            drawer = page.get_by_role('dialog', name='Menu', exact=True)
            reel = page.get_by_role('button', name='Reel', exact=True)
            return ((drawer.count() == 1 and drawer.is_visible()) or
                    (menu.count() == 1 and menu.get_attribute('aria-expanded') == 'true'
                     and reel.count() == 1 and reel.is_visible()))

        # A menu already opened by the operator or by a delayed click must not
        # be toggled closed again.
        if opened():
            return
        try:
            menu.click(timeout=click_timeout_ms)
            return
        except PlaywrightTimeoutError:
            require_no_advanced_protection(page)
            if opened():
                return
            if (menu.count() != 1 or not menu.is_visible() or not menu.is_enabled()
                    or menu.get_attribute('aria-expanded') not in {None, 'false'}):
                raise
            # Preserve unknown modal/security dialogs, rather than focusing
            # an underlying control through their interaction boundary.
            if page.locator('[role="dialog"]:visible, [role="alertdialog"]:visible, dialog:visible').count():
                raise
            if not menu.evaluate("e => e.matches('button, a[href], input') || e.hasAttribute('tabindex')"):
                raise
            print('菜单鼠标入口被遮挡，尝试键盘打开同一个 Facebook 菜单。', flush=True)
            menu.focus(timeout=keyboard_timeout_ms)
            expect(menu).to_be_focused(timeout=keyboard_timeout_ms)
            menu.press('Enter', timeout=keyboard_timeout_ms)
            deadline = time.monotonic() + keyboard_timeout_ms / 1000
            while time.monotonic() < deadline:
                if opened():
                    print('Facebook 菜单已通过键盘打开。', flush=True)
                    return
                page.wait_for_timeout(100)
            raise RuntimeError('键盘操作后未确认 Facebook 菜单展开，尚未选择视频；请检查菜单遮挡或截图。')
    finally:
        page.remove_locator_handler(prompt)


def assist_reel_entry(page, entry, video, identity_proof):
    original_key = job_key(entry, video)
    print("已暂停，尚未选择或发布视频。请在实时 Chrome 页面关闭遮罩，并保留菜单里的 Reel 按钮。", flush=True)
    print("不要手动选择视频或点击发布；待上传文件：", str(video.resolve()), flush=True)
    while True:
        try:
            decision = input("处理完成后输入 READY 并回车；取消请输入 CANCEL：").strip()
        except (EOFError, KeyboardInterrupt) as error:
            raise RuntimeError("菜单协助已取消，尚未选择视频或点击发布。") from error
        if decision == "READY":
            break
        if decision == "CANCEL":
            raise RuntimeError("菜单协助已取消，尚未选择视频或点击发布。")
        print("仍在等待 READY，尚未选择视频。空行或其他文字不会退出；取消请输入 CANCEL。", flush=True)
    if job_key(entry, video) != original_key:
        raise RuntimeError("菜单协助期间源视频内容发生变化，未选择视频或点击发布。")
    if target_key(page.url) != target_key(entry['url']):
        raise RuntimeError("菜单协助期间页面已离开目标主页，未选择视频或点击发布。")
    recheck_publish_identity(page, entry, identity_proof)


def profile_composer_reel(page):
    """Use only a unique real profile composer; never a feed, menu or modal."""
    if page.locator('[role="dialog"]:visible,[role="alertdialog"]:visible,dialog:visible').count():
        return None
    candidates=page.get_by_role('button',name='Reel',exact=True)
    eligible=[]
    for index in range(candidates.count()):
        button=candidates.nth(index)
        if not button.is_visible() or not button.is_enabled():
            continue
        if button.evaluate("""e => {
            if(e.closest('[role="feed"],article,[role="article"],nav,[role="navigation"],aside,[role="complementary"],[role="banner"],[role="dialog"],[role="menu"]')) return false;
            for(let node=e.parentElement,depth=0;node && depth<4;node=node.parentElement,depth++) {
                if(node.matches('main,body,[role="main"],[role="feed"],article,[role="article"],nav,aside')) break;
                const controls=[...node.querySelectorAll('button,[role="button"]')].filter(x=>x.getClientRects().length);
                const labels=controls.map(x=>(x.getAttribute('aria-label')||x.innerText||'').trim());
                if(controls.length<=8 && labels.includes('Photo/video') && labels.includes('Live video')) return true;
            }
            return false;
        }"""):
            eligible.append(button)
    return eligible[0] if len(eligible)==1 else None


def prepare_reel(page, entry, video, text, pause_before_reel=False):
    from playwright.sync_api import expect

    page._fb_upload_stage = 'open_target_profile'
    navigate_profile(page, entry["url"])
    require_no_advanced_protection(page)
    page._fb_upload_stage = 'verify_identity'
    identity_proof = ensure_identity(page, entry)
    page._fb_upload_stage = 'open_reel_menu'
    require_english_interface(page)
    for attempt in range(2):
        page._fb_upload_stage='open_reel_menu'
        reel_button=profile_composer_reel(page) if entry.get('type')=='personal' and not pause_before_reel else None
        if reel_button is not None:
            print('已确认个人主页发帖区的 Reel 入口，直接进入，避开顶部菜单遮挡。',flush=True)
        else:
            open_facebook_menu(page)
            if pause_before_reel:
                assist_reel_entry(page, entry, video, identity_proof)
            drawer=page.get_by_role('dialog',name='Menu',exact=True)
            if entry.get('type')!='personal' or (drawer.count()==1 and drawer.is_visible()):
                reel_button=drawer.get_by_role('button',name='Reel',exact=True)
            else:
                reel_button=page.get_by_role('button',name='Reel',exact=True)
        page._fb_upload_stage = 'select_exact_video'
        try:
            select_reel_video(page, reel_button, video)
            break
        except ReelEntryNotReady:
            if attempt or pause_before_reel:
                raise
            checkpoint(page)
            require_no_advanced_protection(page)
            if (target_key(page.url)!=target_key(entry['url']) or
                page.get_by_role('form',name='Reels',exact=True).locator('input[type="file"]').count()):
                raise RuntimeError('页面已进入上传流程或离开目标主页，未刷新或重复选择视频。')
            recheck_publish_identity(page,entry,identity_proof)
            page._fb_upload_stage='recover_loading_menu_before_file'
            print('菜单长时间未加载；尚未激活 Reel，仅重新加载目标主页一次并核验身份。',flush=True)
            navigate_profile(page,entry['url'])
            require_no_advanced_protection(page)
            identity_proof=ensure_identity(page,entry)
            require_english_interface(page)
    page._fb_upload_stage = 'wait_reel_editor'
    layout = wait_reel_layout(page)
    if layout == "modern":
        page._fb_upload_stage = 'modern_caption_audience_ai'
        button = prepare_modern_reel(page, entry, text)
        return button, dict(identity_proof, editor_layout="modern")
    page._fb_upload_stage = 'classic_next_1'
    page.get_by_role("button", name="Next", exact=True).click(timeout=240000)
    page._fb_upload_stage = 'classic_next_2'
    page.get_by_role("button", name="Next", exact=True).click(timeout=240000)
    checkpoint(page)
    if entry.get("type") == "personal":
        page._fb_upload_stage = 'verify_public_audience'
        ensure_personal_public_audience(page)
    page._fb_upload_stage = 'fill_caption'
    field = page.get_by_role("textbox", name="Describe your reel...", exact=True)
    fill_caption(field, text)
    page._fb_upload_stage = 'verify_ai_label'
    set_ai_label(page, entry)
    page._fb_upload_stage = 'ready_to_post'
    button = page.get_by_role("button", name="Post", exact=True)
    expect(button).to_be_enabled(timeout=240000)
    return button, identity_proof


def archive(video, caption):
    completed = video.parent.parent / "completed"
    completed.mkdir(parents=True, exist_ok=True)
    sources = [video, caption]
    comment = video.with_suffix('.comment.txt')
    if comment.is_file():
        sources.append(comment)
    if any((completed / source.name).exists() for source in sources):
        # Keep original filenames together while retaining previous numbered
        # batches. New source contents can reuse 1.mp4 without replacing history.
        completed = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('%Y%m%d-%H%M%S-'),
                                          dir=str(completed)))
    for source in sources:
        shutil.move(str(source), str(completed / source.name))
    return completed


def launch_context(playwright, entry):
    profile = ROOT / "profiles" / entry["account"]
    if not profile.is_dir():
        raise RuntimeError("没有该账号的登录资料：" + str(profile))
    from chrome_profile_guard import require_profile_free
    require_profile_free(profile, entry['account'])
    print('正在启动账号浏览器：', entry['account'], entry['target'], flush=True)
    # Retain sandboxing and the existing local profile. If setup fails after
    # the process was created, close that partial context to release its profile.
    context = None
    try:
        context = playwright.chromium.launch_persistent_context(
            str(profile), channel="chrome", headless=False, chromium_sandbox=True,
            locale="en-US", accept_downloads=False,
        )
        context.add_cookies([{"name": "locale", "value": "en_US", "domain": ".facebook.com",
                             "path": "/", "secure": True}])
        return context
    except Exception as error:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        detail = ROOT / 'logs' / ('browser-start-' + entry['account'] + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.txt')
        try:
            detail.parent.mkdir(parents=True, exist_ok=True)
            detail.write_text(str(error), encoding='utf-8')
            saved = '完整启动日志：' + str(detail)
        except OSError:
            saved = '完整启动日志未能保存。'
        first = str(error).split('\n', 1)[0][:220]
        raise RuntimeError(entry['account'] + ' 的 Chrome 启动/初始化失败，尚未选择视频。' + first + '；' + saved) from None


def run_entry(entry, state, state_path, publish, filename=None, review_before_post=False, pause_before_reel=False,
              ai_label_override=None, new_video_with_old_review=False, expected_job_key=None,
              preserve_old_review_for_exact_job=False):
    from playwright.sync_api import sync_playwright

    if ai_label_override is not None:
        if type(ai_label_override) is not bool:
            raise ValueError("AI 标签覆盖值必须为布尔值。")
        entry = dict(entry, ai_label=ai_label_override)
    validate_entry(entry)
    if review_before_post and (not publish or not filename):
        raise ValueError("发布前预览核对必须用于 publish，并用 --filename 指定视频。")
    if pause_before_reel and not filename:
        raise ValueError("菜单协助必须用 --filename 指定视频。")
    if new_video_with_old_review and (not publish or not filename or not entry.get('prepared_at')):
        raise ValueError('保留旧记录发布新视频仅用于已准备目标的 publish，并且必须指定文件名。')
    if expected_job_key is not None and (not filename or not re.fullmatch(r'[a-f0-9]{64}', expected_job_key)):
        raise ValueError('核对素材指纹必须是完整任务编号，并指定确切文件名。')
    if preserve_old_review_for_exact_job and (not publish or not filename or not expected_job_key or new_video_with_old_review):
        raise ValueError('保留旧待核实任务仅用于已冻结的确切全新素材')
    identity = (entry["account"], entry["target"])
    if publish and not entry.get("enabled", False):
        raise RuntimeError("尚未启用发布。先完成 prepare 检查，再执行 enable。")
    blocking = [(key, row) for key, row in state.items()
                if (row['account'], row['target']) == identity
                and row['status'] in {'preparing', 'posting', 'needs_review'}]
    if blocking and (not (new_video_with_old_review or preserve_old_review_for_exact_job)
                     or any(row['status'] != 'needs_review' for _, row in blocking)):
        raise RuntimeError("该目标有待核对任务。先检查主页并 confirm 或 retry，避免重复发布。")
    if filename:
        selected = named_job(entry, state, filename)
        jobs = [selected] if selected else []
    else:
        jobs = list(pending_jobs(entry, state))
    if not jobs:
        print("没有新的待发布视频：", identity)
        return False
    if expected_job_key is not None and jobs[0][0] != expected_job_key:
        raise ValueError('发布时素材内容与核对结果不同，未打开浏览器或选择其他视频。')
    if preserve_old_review_for_exact_job:
        for old_key,row in blocking:
            if old_key==expected_job_key or target_key(row.get('url',''))!=target_key(entry['url']):
                raise ValueError('当前素材已有待核实记录或旧记录目标不一致，未发布')
    if new_video_with_old_review:
        for old_key, row in blocking:
            if target_key(row.get('url', '')) != target_key(entry['url']):
                raise RuntimeError('旧待核对任务的目标与当前配置不同，已停止。')
            old_name = str(row.get('video', '')).replace('\\', '/').rsplit('/', 1)[-1]
            validate_video_filename(old_name)
            old_file = inbox_for(entry) / old_name
            if old_file.is_file() and job_key(entry, old_file) == old_key:
                raise RuntimeError('旧待核对视频仍在 inbox，请先核对该视频，未选择其他视频代替。')
        print('仅发布当前新素材，保留旧待核对记录：', len(blocking), flush=True)
    # Bind optional product comment text to this exact new task before opening Chrome.
    # Existing published tasks never reach this point; no historical backfill occurs.
    key, video, caption, text = jobs[0]
    comment_plan = None
    if publish and not entry.get('_authorized_comment_text') and (ROOT / 'post_comment_config.json').is_file():
        from post_comment_plan import build_plan
        comment_plan = build_plan(entry, video, key)
    with sync_playwright() as playwright:
        context = launch_context(playwright, entry)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(30000)
            page._fb_upload_stage = 'browser_opened'
            # One video per invocation; scheduled repetitions handle the queue.
            record = {"account": entry["account"], "target": entry["target"],
                      "url": entry["url"], "video": str(video), "caption": str(caption),
                      "created": datetime.now().astimezone().isoformat(), "status": "preparing",
                      "ai_label_requested": bool(entry.get("ai_label", False))}
            record['uploader_version'] = VERSION
            comment_text=entry.get('_authorized_comment_text')
            link_collector=None
            if comment_text:
                from safe_video_comments import PublicationLinks
                link_collector=PublicationLinks(context,entry,text,record['created'])
            if comment_plan is not None:
                record['post_comment_plan'] = comment_plan
                print('已绑定本条产品评论文案；当前仅记录待办，自动发送尚未启用。', flush=True)
            if new_video_with_old_review or preserve_old_review_for_exact_job:
                record['preserved_older_review_jobs'] = [old_key for old_key, _ in blocking]
            if publish:
                state[key] = record
                save_json(state_path, state)
            posted = False
            try:
                if pause_before_reel:
                    button, identity_proof = prepare_reel(page, entry, video, text, pause_before_reel=True)
                else:
                    button, identity_proof = prepare_reel(page, entry, video, text)
                print("视频：", video.name, "目标：", entry["name"], entry["url"])
                if not publish:
                    print("PREPARE：未点击 Post。请在浏览器检查目标、视频、文案和设置。")
                    input("检查完按回车关闭浏览器；不要在这个准备模式中手动发布。")
                    return True
                if review_before_post:
                    print("待核对源文件：", str(video.resolve()), flush=True)
                    print("尚未点击 Post。请播放浏览器中的预览，核对实际画面、文案、Public 和 AI 标签。", flush=True)
                    try:
                        decision = input("确认预览就是上述文件的内容后，输入 POST 并回车；其他输入取消本次发布：").strip()
                    except (EOFError, KeyboardInterrupt) as error:
                        raise RuntimeError("预览核对已取消，未点击 Post。") from error
                    if decision != "POST":
                        raise RuntimeError("未输入 POST，已取消本次发布，未点击 Post。")
                    if job_key(entry, video) != key:
                        raise RuntimeError("核对期间源视频内容发生变化，未点击 Post。")
                    record["preview_review_method"] = "user_entered_POST"
                    record["preview_reviewed_at"] = datetime.now().astimezone().isoformat()
                if (new_video_with_old_review or expected_job_key is not None) and job_key(entry, video) != key:
                    raise RuntimeError('准备期间源视频内容变化，未点击发布。')
                if expected_job_key is not None and caption.read_text(encoding='utf-8-sig').strip() != text:
                    raise RuntimeError('准备期间同名文案变化，未点击发布。')
                page._fb_upload_stage = 'final_identity_check'
                install_receipt_watch(page)
                recheck_publish_identity(page, entry, identity_proof)
                # Persist the intent BEFORE clicking, so crashes cannot retry the Post.
                record["identity_validation"] = identity_proof
                record["status"] = "posting"
                save_json(state_path, state)
                print('准备提交发布：', entry['account'], entry['target'], video.name, flush=True)
                page.evaluate("() => { window.__fbUploadWatch.armed = true; }")
                posted = True
                if link_collector is not None:
                    link_collector.armed=True
                page._fb_upload_stage = 'post_click'
                receipt_started = time.monotonic()
                button.click(timeout=30000)
                page._fb_upload_stage = 'wait_success_receipt'
                print('已点击发布，最多等待 3 分钟；超时记录待核实并继续下一个：', entry['account'], entry['target'], flush=True)
                record["success_message"] = wait_for_receipt(page, button, started_at=receipt_started)
                record["confirmation_method"] = "fresh_success_ui_and_composer_closed"
                record["status"] = "published"
                save_json(state_path, state)
                archive(video, caption)
                print("发布成功，已归档：", video.name)
                if comment_text:
                    try:
                        from safe_video_comments import after_publication
                        result=after_publication(page,context,entry,identity_proof,key,record,comment_text,link_collector)
                        record['comment_status']=result['status']
                        record['comment_error']=result.get('error','')
                    except Exception as comment_error:
                        record.update(comment_status='manual_required',comment_error=str(comment_error)[:2000])
                    save_json(state_path,state)
                    print('视频发布成功；评论状态：',record['comment_status'],record.get('comment_error',''),flush=True)
            except KeyboardInterrupt:
                if publish and record["status"] != "published":
                    record["status"] = "needs_review" if posted else "failed_before_post"
                    record["error"] = "用户中断；已提交则需核实，禁止自动重发"
                    record["failure_stage"] = getattr(page, '_fb_upload_stage', 'unknown')
                    save_json(state_path, state)
                raise
            except Exception as error:
                if publish and record["status"] != "published":
                    record["status"] = "needs_review" if posted else "failed_before_post"
                    if posted and isinstance(error, ReceiptNeedsReview):
                        record["review_reason"] = "publication_receipt_timeout"
                    record["error"] = str(error)[:1600]
                    stage = getattr(page, '_fb_upload_stage', 'unknown')
                    record['failure_stage'] = stage if isinstance(stage, str) else 'unknown'
                    save_json(state_path, state)
                detail = ROOT / 'logs' / ('review-' + key[:12] + '-error.txt')
                try:
                    detail.write_text(str(error), encoding='utf-8')
                except OSError:
                    pass
                shot = ROOT / "logs" / ("review-" + key[:12] + ".png")
                try:
                    page.screenshot(path=str(shot))
                except Exception:
                    pass
                exception_type = (AccountActionRequired if isinstance(error, AccountActionRequired) else
                                  ReceiptNeedsReview if posted and isinstance(error, ReceiptNeedsReview) else RuntimeError)
                raise exception_type("操作未完成或结果需核对。记录：" + key[:12] + "；" + str(error)) from error
        finally:
            context.close()


def main():
    print("本地上传程序版本：", VERSION)
    parser = argparse.ArgumentParser(description="Windows 本地公共主页和个人主页视频上传")
    parser.add_argument("action", choices=["configure", "check-identity", "prepare", "enable", "publish", "status", "confirm", "record-manual", "retry"])
    parser.add_argument("--account", default="fb02")
    parser.add_argument("--target", default="page01")
    parser.add_argument("--url")
    parser.add_argument("--name")
    parser.add_argument("--job")
    parser.add_argument("--video", type=Path)
    parser.add_argument("--filename", help="prepare/publish 只处理指定 MP4 文件名，不处理其他排队视频")
    parser.add_argument("--review-before-post", action="store_true", help="publish 在最终预览暂停，输入 POST 后在同一窗口继续发布")
    parser.add_argument("--pause-before-reel", action="store_true", help="选择视频前暂停，在实时页面处理遮罩后输入 READY 继续")
    parser.add_argument("--verified-absent", action="store_true")
    parser.add_argument('--new-video-with-old-review', action='store_true',
                        help='publish 指定全新视频；仅当旧待核对素材已不在 inbox 时保留旧记录继续')
    parser.add_argument("--ai-label", choices=["on", "off"],
                        help="configure 保存默认值；prepare/publish 仅覆盖本次，不更改默认配置")
    args = parser.parse_args()
    if args.filename and args.action not in {"prepare", "publish"}:
        parser.error("--filename 仅用于 prepare 或 publish")
    if args.review_before_post and (args.action != "publish" or not args.filename):
        parser.error("--review-before-post 仅用于 publish，且需指定 --filename")
    if args.pause_before_reel and (args.action not in {"prepare", "publish"} or not args.filename):
        parser.error("--pause-before-reel 仅用于 prepare/publish，且需指定 --filename")
    if args.new_video_with_old_review and (args.action != 'publish' or not args.filename):
        parser.error('--new-video-with-old-review 仅用于 publish，且需指定 --filename')
    logs = ROOT / "logs"
    if args.ai_label is not None and args.action not in {"configure", "prepare", "publish"}:
        parser.error("--ai-label 仅用于 configure、prepare 或 publish")
    if args.action == "status":
        try:
            return display_status(logs)
        except Exception as error:
            print("STOP：无法读取发布记录：", error)
            return 1
    configuration = read_json(CONFIG, {"targets": []})
    entry = next((item for item in configuration["targets"] if
                  item["account"] == args.account and item["target"] == args.target), None)
    logs.mkdir(exist_ok=True)
    state_path = logs / "publish_state.json"
    lock = logs / "upload.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("另一任务正在运行，或上次异常留下锁。确认所有上传程序已关闭后才能删除 logs\\upload.lock。")
        return 2
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        state = read_json(state_path, {})
        if args.action in {"confirm", "retry"}:
            if not args.job or len(args.job) < 12:
                raise ValueError("请用 --job 指定 status 中显示的 12 位任务编号。")
            matches = [key for key in state if key.startswith(args.job)]
            if len(matches) != 1:
                raise ValueError("没有唯一匹配的任务。")
            key = matches[0]
            row = state[key]
            if args.action == "confirm":
                permalink = normalize_video_permalink(args.url)
                if row["status"] not in {"preparing", "posting", "needs_review"}:
                    raise ValueError("此任务不处于待核对状态。")
                owner = re.search(r"/([0-9]+)/videos/", permalink)
                proof = row.get("identity_validation")
                if row["target"] == "personal" and owner and isinstance(proof, dict) and proof.get("session_marker"):
                    owner_marker = hashlib.sha256(("personal:" + owner.group(1)).encode("ascii")).hexdigest()
                    if owner_marker != proof["session_marker"]:
                        raise ValueError("视频链接的作者编号与原任务核对的个人账号不一致；未修改记录。")
                backup = ROOT / "backups" / ("confirm-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
                backup.mkdir(parents=True, exist_ok=False)
                shutil.copy2(state_path, backup / state_path.name)
                row["status"] = "published"
                row["permalink"] = permalink
                row["confirmation_method"] = "user_verified_existing_post"
                row["confirmed_at"] = datetime.now().astimezone().isoformat()
                save_json(state_path, state)
                archive(Path(row["video"]), Path(row["caption"]))
                print("已确认发布成功并归档：", row["account"], row["target"], key[:12])
            else:
                if not args.verified_absent or row["status"] == "published":
                    raise ValueError("先确认 Facebook 上没有该视频，再加 --verified-absent；已发布任务不能重试。")
                backup = ROOT / "backups" / ("retry-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
                backup.mkdir(parents=True, exist_ok=False)
                shutil.copy2(state_path, backup / state_path.name)
                del state[key]
                save_json(state_path, state)
                print("原任务记录已备份，已解除本次重试限制：", key[:12])
            return 0
        if args.action == "configure":
            if entry is None:
                entry = {"account": args.account, "target": args.target, "type": "page",
                         "url": "", "name": "", "enabled": False, "ai_label": True,
                         "excluded_files": ["2026-10-13_01.mp4"]}
                configuration["targets"].append(entry)
            if args.url:
                entry["url"] = args.url
            if args.name:
                entry["name"] = args.name
            if args.ai_label:
                entry["ai_label"] = args.ai_label == "on"
            validate_entry(entry)
            entry["enabled"] = False
            entry.pop("prepared_at", None)
            for name in ("inbox", "completed", "failed"):
                (inbox_for(entry).parent / name).mkdir(parents=True, exist_ok=True)
            save_json(CONFIG, configuration)
            print("配置已保存，发布尚未启用。")
            return 0
        if entry is None:
            raise ValueError("没有该目标配置；先执行 configure。")
        validate_entry(entry)
        if args.action == "record-manual":
            record_manual_post(entry, state, state_path, args.video, args.url)
        elif args.action == "check-identity":
            check_identity(entry)
        elif args.action == "enable":
            if not entry.get("prepared_at"):
                raise ValueError("先执行 prepare 并在本地浏览器检查目标、文案和设置。")
            entry["enabled"] = True
            save_json(CONFIG, configuration)
            print("已启用该目标。publish 和定时任务将实际发布新视频。")
        else:
            run_options = {}
            if args.new_video_with_old_review:
                run_options['new_video_with_old_review'] = True
            if args.ai_label is not None:
                run_options["ai_label_override"] = args.ai_label == "on"
            if args.pause_before_reel:
                prepared = run_entry(entry, state, state_path, args.action == "publish",
                                     filename=args.filename, review_before_post=args.review_before_post,
                                     pause_before_reel=True, **run_options)
            elif args.review_before_post:
                prepared = run_entry(entry, state, state_path, True, filename=args.filename,
                                     review_before_post=True, **run_options)
            elif args.filename:
                prepared = run_entry(entry, state, state_path, args.action == "publish",
                                     filename=args.filename, **run_options)
            else:
                prepared = run_entry(entry, state, state_path, args.action == "publish", **run_options)
            if args.action == "prepare" and prepared:
                entry["prepared_at"] = datetime.now().astimezone().isoformat()
                save_json(CONFIG, configuration)
        return 0
    except ReceiptNeedsReview as error:
        print("REVIEW：", error)
        return 3
    except Exception as error:
        print("STOP：", error)
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
