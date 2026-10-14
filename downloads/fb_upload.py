"""Local Windows uploader based on the user's recorded public Page flow."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "upload_config.json"
VERSION = "2.3"
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


def wait_for_receipt(page, button):
    page.wait_for_function("() => Boolean(window.__fbUploadWatch && window.__fbUploadWatch.message)", timeout=120000)
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
    if entry.get("type") != "page":
        raise ValueError("这份录制只支持公共主页；个人主页需要另行录制和验证。")
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


def checkpoint(page):
    if any(part in page.url for part in ("/checkpoint", "/login", "/two_step_verification")):
        raise RuntimeError("遇到登录或安全验证。请本人处理，程序不会跳过验证。")


HEADER_MANAGEMENT_JS = r"""heading => {
    const norm = text => (text || '').replace(/\s+/g, ' ').trim();
    const controls = /^(Edit|Edit Page|Edit profile|编辑|编辑主页|Professional dashboard|专业仪表板|专业面板)$/i;
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
                return 'active_page_header_management_control';
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


def check_identity(entry):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = launch_context(playwright, entry)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(entry["url"], wait_until="domcontentloaded", timeout=90000)
            result = ensure_page_identity(page, entry)
            result["checked_at"] = datetime.now().astimezone().isoformat()
            upload_log = ROOT / "logs" / ("identity-" + entry["account"] + "-" + entry["target"] + ".json")
            save_json(upload_log, result)
            print("仅检查和切换主页身份；没有上传或发布视频。")
        finally:
            context.close()


def prepare_reel(page, entry, video, text):
    from playwright.sync_api import expect

    page.goto(entry["url"], wait_until="domcontentloaded", timeout=90000)
    identity_proof = ensure_page_identity(page, entry)
    page.get_by_role("button", name="Facebook menu", exact=True).click()
    page.get_by_role("dialog", name="Menu", exact=True).get_by_role("button", name="Reel", exact=True).click()
    form = page.get_by_role("form", name="Reels", exact=True)
    form.locator('input[type="file"]').set_input_files(str(video.resolve()))
    page.get_by_role("button", name="Next", exact=True).click(timeout=240000)
    page.get_by_role("button", name="Next", exact=True).click(timeout=240000)
    checkpoint(page)
    field = page.get_by_role("textbox", name="Describe your reel...", exact=True)
    field.fill(text, timeout=240000)
    expect(field).to_have_value(text) if field.evaluate("e => 'value' in e") else expect(field).to_have_text(text)
    # Turn the requested AI label ON, never toggle an already enabled label OFF.
    if entry.get("ai_label", False):
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
    return playwright.chromium.launch_persistent_context(
        str(profile), channel="chrome", headless=False, chromium_sandbox=True,
        locale="en-US", accept_downloads=False,
    )


def run_entry(entry, state, state_path, publish):
    from playwright.sync_api import sync_playwright

    validate_entry(entry)
    identity = (entry["account"], entry["target"])
    if publish and not entry.get("enabled", False):
        raise RuntimeError("尚未启用发布。先完成 prepare 检查，再执行 enable。")
    if any((row["account"], row["target"]) == identity and row["status"] in
           {"preparing", "posting", "needs_review"} for row in state.values()):
        raise RuntimeError("该目标有待核对任务。先检查主页并 confirm 或 retry，避免重复发布。")
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
                actor_matches = page_actor_matches(page, entry)
                if identity_proof["method"] == "page_actor_id_match" and not actor_matches:
                    raise RuntimeError("准备视频后当前主页身份信息已变化；未点击发布。")
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
                    record["error"] = str(error)[:1600]
                    save_json(state_path, state)
                shot = ROOT / "logs" / ("review-" + key[:12] + ".png")
                try:
                    page.screenshot(path=str(shot))
                except Exception:
                    pass
                raise RuntimeError("操作未完成或结果需核对。记录：" + key[:12] + "；" + str(error)) from error
        finally:
            context.close()


def main():
    print("本地上传程序版本：", VERSION)
    parser = argparse.ArgumentParser(description="Windows 本地公共主页视频上传")
    parser.add_argument("action", choices=["configure", "check-identity", "prepare", "enable", "publish", "status", "confirm", "retry"])
    parser.add_argument("--account", default="fb02")
    parser.add_argument("--target", default="page01")
    parser.add_argument("--url")
    parser.add_argument("--name")
    parser.add_argument("--job")
    parser.add_argument("--verified-absent", action="store_true")
    parser.add_argument("--ai-label", choices=["on", "off"])
    args = parser.parse_args()
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
                if not args.url or not re.fullmatch(r"https://(?:www\.)?facebook\.com/reel/[0-9]+/?", args.url):
                    raise ValueError("手动确认需提供主页上该视频的完整 Facebook Reel 链接。")
                if row["status"] not in {"preparing", "posting", "needs_review"}:
                    raise ValueError("此任务不处于待核对状态。")
                row["status"] = "published"
                row["permalink"] = args.url
                save_json(state_path, state)
                archive(Path(row["video"]), Path(row["caption"]))
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
        if args.action == "check-identity":
            check_identity(entry)
        elif args.action == "enable":
            if not entry.get("prepared_at"):
                raise ValueError("先执行 prepare 并在本地浏览器检查目标、文案和设置。")
            entry["enabled"] = True
            save_json(CONFIG, configuration)
            print("已启用该目标。publish 和定时任务将实际发布新视频。")
        else:
            prepared = run_entry(entry, state, state_path, args.action == "publish")
            if args.action == "prepare" and prepared:
                entry["prepared_at"] = datetime.now().astimezone().isoformat()
                save_json(CONFIG, configuration)
        return 0
    except Exception as error:
        print("STOP：", error)
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
