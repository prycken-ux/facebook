"""Local Windows uploader based on the user's recorded Page and personal flows."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "upload_config.json"
VERSION = "2.16"
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
    if (window.__fbUploadWatch && window.__fbUploadWatch.observer) {
        window.__fbUploadWatch.observer.disconnect();
    }
    const rx = new RegExp(pattern, 'i');
    const seen = new WeakMap();
    const watch = {armed: false, message: null, observer: null};
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
    });
    watch.observer.observe(document.body, {childList: true, subtree: true, characterData: true});
}"""


def install_receipt_watch(page):
    page.evaluate(RECEIPT_WATCH_JS, SUCCESS_PATTERN)


class ReceiptNeedsReview(RuntimeError):
    """Post was clicked, but no fresh success receipt could be established."""


def wait_for_receipt(page, button):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        page.wait_for_function("() => Boolean(window.__fbUploadWatch && window.__fbUploadWatch.message)", timeout=120000)
    except PlaywrightTimeoutError as error:
        # A login/checkpoint is an operational stop, not a deferred receipt.
        checkpoint(page)
        raise ReceiptNeedsReview("已点击发布，120 秒内未识别到成功回执；保留待核对，不会自动重发。") from error
    message = page.evaluate("() => window.__fbUploadWatch.message")
    if not isinstance(message, str) or not re.fullmatch(SUCCESS_PATTERN, message, re.I):
        raise RuntimeError("没有收到本次发布的有效成功提示。")
    # A notification alone must not mark an open upload composer as completed.
    button.wait_for(state="hidden", timeout=30000)
    checkpoint(page)
    return message


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


def pending_jobs(entry, state):
    folder = inbox_for(entry)
    excluded = {name.lower() for name in entry.get("excluded_files", [])}
    for video in sorted(folder.glob("*.mp4")):
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


def named_job(entry, state, filename):
    """Resolve exactly one inbox file; never fall back to another queued video."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]*\.mp4", filename, re.I):
        raise ValueError("--filename 需填写 MP4 文件名，例如 2026-10-15_01.mp4，不能包含路径。")
    folder = inbox_for(entry)
    video = folder / filename
    if not video.is_file():
        completed = folder.parent / "completed" / filename
        if completed.is_file():
            row = state.get(job_key(entry, completed), {})
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


def ensure_page_identity(page, entry):
    from playwright.sync_api import expect

    checkpoint(page)
    expect(page.get_by_role("heading", name=entry["name"], exact=True).first).to_be_visible(timeout=90000)
    if target_key(page.url) != target_key(entry["url"]):
        raise RuntimeError("浏览器跳转到了不同主页；未选择视频或点击发布。")
    switch = page.get_by_role("button", name=re.compile(r"^(Switch Now|立即切换|现在切换)$", re.I))
    if switch.count() == 0:
        switch = page.get_by_text(re.compile(r"^(Switch Now|立即切换|现在切换)$", re.I))
    switched = False
    if switch.count() == 1 and switch.is_visible():
        print("正在切换到目标公共主页身份：", entry["name"], flush=True)
        switch.click()
        expect(switch).not_to_be_visible(timeout=90000)
        switched = True
    banner = page.get_by_text(re.compile(r"^Switch into .+ to start managing it\.?$", re.I))
    expect(banner).not_to_be_visible(timeout=30000)
    method = "page_actor_id_match" if page_actor_matches(page, entry) else None
    if method is None:
        heading = page.get_by_role("heading", name=entry["name"], exact=True).first
        method = heading.evaluate(HEADER_MANAGEMENT_JS)
        if method != "active_page_header_management_control":
            raise RuntimeError("无法确认公共主页身份：当前身份编号不可用，且主页顶部未找到有效管理按钮。未选择视频或点击发布。")
    checkpoint(page)
    expect(page.get_by_role("heading", name=entry["name"], exact=True).first).to_be_visible(timeout=30000)
    if target_key(page.url) != target_key(entry["url"]):
        raise RuntimeError("切换后主页网址与配置不同，已停止。")
    print("主页身份检查通过：", entry["name"], entry["url"], flush=True)
    return {"target_url": entry["url"], "name": entry["name"], "switched": switched,
            "method": method}


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
        raise RuntimeError("当前仍是公共主页身份，请先手动切回登录者个人主页；未选择视频或点击发布。")
    target = target_key(entry["url"])
    if target.startswith("id:") and people != {target[3:]}:
        raise RuntimeError("登录的个人账号与目标个人主页不一致；未选择视频或点击发布。")
    return hashlib.sha256(("personal:" + next(iter(people))).encode("ascii")).hexdigest()


def verify_personal_vanity_owner(page, entry, marker):
    from playwright.sync_api import expect

    # Facebook's /me route resolves the logged-in person's own profile. This
    # proves ownership even when a responsive layout hides Edit profile.
    page.goto(english_url("https://www.facebook.com/me"), wait_until="domcontentloaded", timeout=90000)
    page.wait_for_url(lambda url: urlparse(str(url)).path.rstrip("/") != "/me", timeout=60000)
    checkpoint(page)
    if personal_actor_fingerprint(page, entry) != marker:
        raise RuntimeError("核对本人主页期间登录身份变化，已停止；未选择视频或点击发布。")
    expect(page.get_by_role("heading", name=entry["name"], exact=True).first).to_be_visible(timeout=90000)
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
    page.goto(english_url(entry["url"]), wait_until="domcontentloaded", timeout=90000)
    checkpoint(page)
    expect(page.get_by_role("heading", name=entry["name"], exact=True).first).to_be_visible(timeout=90000)
    if target_key(page.url) != expected_key:
        raise RuntimeError("返回后目标个人主页网址变化，已停止。")


def ensure_personal_identity(page, entry):
    from playwright.sync_api import expect

    checkpoint(page)
    marker = personal_actor_fingerprint(page, entry)
    heading = page.get_by_role("heading", name=entry["name"], exact=True).first
    expect(heading).to_be_visible(timeout=90000)
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
            page.goto(english_url(entry["url"]), wait_until="domcontentloaded", timeout=90000)
            result = ensure_identity(page, entry)
            result["checked_at"] = datetime.now().astimezone().isoformat()
            upload_log = ROOT / "logs" / ("identity-" + entry["account"] + "-" + entry["target"] + ".json")
            save_json(upload_log, result)
            print("仅检查和切换主页身份；没有上传或发布视频。")
        finally:
            context.close()


def select_reel_video(page, reel_button, video, timeout_ms=60000):
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
        reel_button.click(timeout=timeout_ms)
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


def fill_caption(field, text):
    from playwright.sync_api import expect

    field.fill(text, timeout=240000)
    if field.evaluate("e => 'value' in e"):
        expect(field).to_have_value(text)
    else:
        # Rich editors represent line breaks as block elements or <br> nodes.
        # Check their rendered text so multiline captions retain those breaks.
        expect(field).to_have_text(text, use_inner_text=True)


def prepare_modern_reel(page, entry, text):
    from playwright.sync_api import expect

    field = modern_caption_field(page)
    fill_caption(field, text)
    page.get_by_role("button", name="Next", exact=True).click(timeout=240000)
    checkpoint(page)
    audience = page.get_by_role("button", name=re.compile(r"^Post audience Post audience"))
    expect(audience).to_be_visible(timeout=60000)
    if entry.get("ai_label", False):
        label = page.get_by_role("button", name=re.compile(r"^Add AI label"))
        toggle = label.get_by_label(re.compile(r"^(Off|On)$"))
        expect(toggle).to_be_visible(timeout=30000)
        toggle.check()
        expect(toggle).to_be_checked()
    # Facebook renders separate label/value nodes whose textContent is
    # "Post audiencePublic". Its accessible name retains the separation.
    expect(audience).to_be_enabled(timeout=240000)
    public_audience = page.get_by_role(
        "button", name=re.compile(r"^Post audience\s+Post audience\s+Public$")
    )
    if public_audience.count() == 1 and public_audience.is_visible():
        print("本条 Reel 已是 Public，保留当前公开范围。", flush=True)
    else:
        friends_audience = page.get_by_role(
            "button", name=re.compile(r"^Post audience\s+Post audience\s+Friends$")
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
        re.compile(r"^Post audience\s+Post audience\s+Public$"), timeout=30000
    )
    button = page.get_by_role("button", name="Post", exact=True)
    expect(button).to_be_enabled(timeout=240000)
    print("新版 Reel 检查通过：TXT 文案已填写，Public 和所需 AI 标签已核对。", flush=True)
    return button


def prepare_reel(page, entry, video, text):
    from playwright.sync_api import expect

    page.goto(english_url(entry["url"]), wait_until="domcontentloaded", timeout=90000)
    identity_proof = ensure_identity(page, entry)
    require_english_interface(page)
    page.get_by_role("button", name=re.compile(r"^(Facebook menu|Menu)$", re.I)).click()
    if entry.get("type") == "personal":
        reel_button = page.get_by_role("button", name="Reel", exact=True)
    else:
        reel_button = page.get_by_role("dialog", name="Menu", exact=True).get_by_role("button", name="Reel", exact=True)
    select_reel_video(page, reel_button, video)
    layout = wait_reel_layout(page)
    if layout == "modern":
        button = prepare_modern_reel(page, entry, text)
        return button, dict(identity_proof, editor_layout="modern")
    page.get_by_role("button", name="Next", exact=True).click(timeout=240000)
    page.get_by_role("button", name="Next", exact=True).click(timeout=240000)
    checkpoint(page)
    if entry.get("type") == "personal":
        ensure_personal_public_audience(page)
    field = page.get_by_role("textbox", name="Describe your reel...", exact=True)
    fill_caption(field, text)
    # Turn the requested AI label ON, never toggle an already enabled label OFF.
    if entry.get("ai_label", False) and entry.get("type") == "personal":
        label = page.get_by_role("switch", name="Add AI label", exact=True)
        label.check()
        expect(label).to_be_checked()
    elif entry.get("ai_label", False):
        label = page.get_by_role("button", name=re.compile(r"^Add AI label We require you"))
        current = label.get_attribute("aria-checked") or label.get_attribute("aria-pressed")
        if current is None:
            switches = label.get_by_role("switch")
            if switches.count() == 1:
                current = switches.get_attribute("aria-checked")
        if current not in {"true", "false"}:
            raise RuntimeError("无法确认 AI 标签开关状态。请补充录制该开关的属性，未点击发布。")
        if current == "false":
            label.click()
    button = page.get_by_role("button", name="Post", exact=True)
    expect(button).to_be_enabled(timeout=240000)
    return button, identity_proof


def archive(video, caption):
    completed = video.parent.parent / "completed"
    completed.mkdir(parents=True, exist_ok=True)
    for source in (video, caption):
        destination = completed / source.name
        if destination.exists():
            raise RuntimeError("completed 已有同名文件；已保留发布记录，请手动整理，程序不会再次发布。")
    for source in (video, caption):
        shutil.move(str(source), str(completed / source.name))


def launch_context(playwright, entry):
    profile = ROOT / "profiles" / entry["account"]
    if not profile.is_dir():
        raise RuntimeError("没有该账号的登录资料：" + str(profile))
    # Use the existing installed Chrome, retain the browser security sandbox.
    context = playwright.chromium.launch_persistent_context(
        str(profile), channel="chrome", headless=False, chromium_sandbox=True,
        locale="en-US", accept_downloads=False,
    )
    # Persistent profiles can retain a different Facebook site language even
    # when the browser locale is English. This is a UI preference, not login data.
    context.add_cookies([{"name": "locale", "value": "en_US", "domain": ".facebook.com",
                         "path": "/", "secure": True}])
    return context


def run_entry(entry, state, state_path, publish, filename=None):
    from playwright.sync_api import sync_playwright

    validate_entry(entry)
    identity = (entry["account"], entry["target"])
    if publish and not entry.get("enabled", False):
        raise RuntimeError("尚未启用发布。先完成 prepare 检查，再执行 enable。")
    if any((row["account"], row["target"]) == identity and row["status"] in
           {"preparing", "posting", "needs_review"} for row in state.values()):
        raise RuntimeError("该目标有待核对任务。先检查主页并 confirm 或 retry，避免重复发布。")
    if filename:
        selected = named_job(entry, state, filename)
        jobs = [selected] if selected else []
    else:
        jobs = list(pending_jobs(entry, state))
    if not jobs:
        print("没有新的待发布视频：", identity)
        return False
    with sync_playwright() as playwright:
        context = launch_context(playwright, entry)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(30000)
            # One video per invocation; scheduled repetitions handle the queue.
            key, video, caption, text = jobs[0]
            record = {"account": entry["account"], "target": entry["target"],
                      "url": entry["url"], "video": str(video), "caption": str(caption),
                      "created": datetime.now().astimezone().isoformat(), "status": "preparing"}
            if publish:
                state[key] = record
                save_json(state_path, state)
            posted = False
            try:
                button, identity_proof = prepare_reel(page, entry, video, text)
                print("视频：", video.name, "目标：", entry["name"], entry["url"])
                if not publish:
                    print("PREPARE：未点击 Post。请在浏览器检查目标、视频、文案和设置。")
                    input("检查完按回车关闭浏览器；不要在这个准备模式中手动发布。")
                    return True
                install_receipt_watch(page)
                recheck_publish_identity(page, entry, identity_proof)
                # Persist the intent BEFORE clicking, so crashes cannot retry the Post.
                record["identity_validation"] = identity_proof
                record["status"] = "posting"
                save_json(state_path, state)
                page.evaluate("() => { window.__fbUploadWatch.armed = true; }")
                posted = True
                button.click()
                record["success_message"] = wait_for_receipt(page, button)
                record["confirmation_method"] = "fresh_success_ui_and_composer_closed"
                record["status"] = "published"
                save_json(state_path, state)
                archive(video, caption)
                print("发布成功，已归档：", video.name)
            except Exception as error:
                if publish and record["status"] != "published":
                    record["status"] = "needs_review" if posted else "failed_before_post"
                    if posted and isinstance(error, ReceiptNeedsReview):
                        record["review_reason"] = "publication_receipt_timeout"
                    record["error"] = str(error)[:1600]
                    save_json(state_path, state)
                shot = ROOT / "logs" / ("review-" + key[:12] + ".png")
                try:
                    page.screenshot(path=str(shot))
                except Exception:
                    pass
                exception_type = ReceiptNeedsReview if posted and isinstance(error, ReceiptNeedsReview) else RuntimeError
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
    parser.add_argument("--verified-absent", action="store_true")
    parser.add_argument("--ai-label", choices=["on", "off"])
    args = parser.parse_args()
    if args.filename and args.action not in {"prepare", "publish"}:
        parser.error("--filename 仅用于 prepare 或 publish")
    logs = ROOT / "logs"
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
                del state[key]
                save_json(state_path, state)
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
            if args.filename:
                prepared = run_entry(entry, state, state_path, args.action == "publish", filename=args.filename)
            else:
                prepared = run_entry(entry, state, state_path, args.action == "publish")
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
