"""Read-only local diagnostic: no upload, Post click, token or cookie export."""
import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.sync_api import sync_playwright
import fb_upload as upload


def caption_probe(caption):
    # Hashtags are separate DOM links and insert spaces into rendered text.
    # Check a meaningful caption sentence first, rather than glued hashtags.
    return " ".join(caption.split("#", 1)[0].split())[:45]


def video_nodes(payload, wanted_id):
    """Extract only public information about the already confirmed video."""
    result = []
    def visit(node, actors=(), message="", story=False, depth=0):
        if depth > 80:
            return
        if isinstance(node, list):
            for child in node:
                visit(child, actors, message, story, depth + 1)
        elif isinstance(node, dict):
            owners = list(actors)
            for key in ("owner", "video_owner", "actors"):
                values = node.get(key, [])
                if isinstance(values, dict):
                    values = [values]
                if isinstance(values, list):
                    owners.extend(str(value["id"]) for value in values if isinstance(value, dict) and str(value.get("id", "")).isdecimal())
            for key in ("message", "description"):
                value = node.get(key)
                if isinstance(value, dict) and isinstance(value.get("text"), str):
                    message = value["text"]
                elif isinstance(value, str):
                    message = value
            story = story or node.get("__typename") == "Story"
            if str(node.get("id", "")) == wanted_id:
                result.append({"video_id": wanted_id, "typename": str(node.get("__typename", "")),
                               "owner_ids": sorted(set(owners)), "caption": message[:4000],
                               "in_story": story,
                               "published_flag": node.get("is_published") if isinstance(node.get("is_published"), bool) else None})
            for child in node.values():
                if isinstance(child, (dict, list)):
                    visit(child, tuple(owners), message, story, depth + 1)
    visit(payload)
    return result


class KnownVideoResponses:
    def __init__(self, known_id):
        self.known_id = known_id
        self.items = []
        self.responses_checked = 0

    def receive(self, response):
        parsed = urlparse(response.url)
        if parsed.hostname not in {"www.facebook.com", "facebook.com"} or parsed.path.rstrip("/") != "/api/graphql":
            return
        try:
            body = response.text()
            if len(body) > 4_000_000:
                return
            self.responses_checked += 1
            body = re.sub(r"^\s*for\s*\(\s*;;\s*\)\s*;", "", body)
            try:
                payloads = [json.loads(body)]
            except ValueError:
                payloads = []
                for line in body.splitlines():
                    try:
                        payloads.append(json.loads(line))
                    except ValueError:
                        pass
            for payload in payloads:
                for item in video_nodes(payload, self.known_id):
                    if item not in self.items and len(self.items) < 30:
                        self.items.append(item)
        except Exception:
            # No response headers, cookies, query bodies or raw data are saved.
            pass


def reels_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["sk"] = ["reels_tab"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True), fragment=""))


def inspect_known_reel(page, entry, permalink, caption):
    page.goto(permalink, wait_until="domcontentloaded", timeout=90000)
    upload.checkpoint(page)
    prefix = caption_probe(caption)
    author = page.get_by_role("link", name=entry["name"], exact=True)
    try:
        author.first.wait_for(state="visible", timeout=30000)
    except Exception:
        pass
    if prefix:
        try:
            page.wait_for_function(
                "prefix => document.body.innerText.replace(/\\s+/g, ' ').includes(prefix)",
                arg=prefix, timeout=15000,
            )
        except Exception:
            pass
    result = page.evaluate("""({name, prefix, caption}) => {
      const norm = text => text.normalize('NFKC').replace(/\\s+/g, ' ').trim();
      const body = norm(document.body.innerText);
      const authorLinks = [...document.querySelectorAll('a[href]')]
        .filter(a => norm(a.innerText) === name)
        .map(a => {
          const u = new URL(a.href);
          if (!['facebook.com','www.facebook.com'].includes(u.hostname)) return null;
          const id = u.searchParams.get('id');
          return {text: norm(a.innerText), url: u.origin + u.pathname + (id ? '?id=' + id : '')};
        }).filter(Boolean);
      return {caption_prefix_present: Boolean(prefix && body.includes(norm(prefix))),
              full_caption_present: Boolean(caption && body.includes(norm(caption))),
              author_links: authorLinks.slice(0, 15)};
    }""", {"name": entry["name"], "prefix": prefix, "caption": caption})
    result["known_reel_url"] = permalink
    result["caption_prefix"] = prefix
    result["reel_page_buttons"] = page.get_by_role("button").evaluate_all(
        "els => els.map(e => e.getAttribute('aria-label') || e.innerText).filter(Boolean).slice(0, 40)"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="只读检查公共主页和已发布 Reel")
    parser.add_argument("--account", default="fb02")
    parser.add_argument("--target", default="page01")
    args = parser.parse_args()
    config = upload.read_json(upload.CONFIG, {"targets": []})
    entry = next((e for e in config["targets"] if e["account"] == args.account and e["target"] == args.target), None)
    if entry is None:
        raise ValueError("没有该目标的配置。")
    upload.validate_entry(entry)
    logs = upload.ROOT / "logs"
    logs.mkdir(exist_ok=True)
    state = upload.read_json(logs / "publish_state.json", {})
    rows = [row for row in state.values() if row["account"] == args.account and
            row["target"] == args.target and row["status"] == "published" and row.get("permalink")]
    if not rows:
        raise ValueError("先用 confirm 补记已发布的视频链接，再运行检查。")
    row = rows[-1]
    if not re.fullmatch(r"https://(?:www\.)?facebook\.com/reel/[0-9]+/?", row["permalink"]):
        raise ValueError("已保存的视频链接格式无效。")
    # Only read the caption from the expected local archive, never from arbitrary state paths.
    caption_path = upload.inbox_for(entry).parent / "completed" / Path(row["caption"]).name
    caption = caption_path.read_text(encoding="utf-8-sig").strip()
    report = {"created": datetime.now().astimezone().isoformat(), "account": args.account,
              "target": args.target, "target_url": entry["url"], "checks": {}}
    lock = logs / "upload.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("上传程序仍在运行或有锁文件。请先确认上传程序已退出。")
    try:
        with os.fdopen(fd, "w") as file:
            file.write(str(os.getpid()))
        with sync_playwright() as playwright:
            context = upload.launch_context(playwright, entry)
            try:
                known_id = row["permalink"].rstrip("/").split("/")[-1]
                collector = KnownVideoResponses(known_id)
                context.on("response", collector.receive)
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(30000)
                page.goto(entry["url"], wait_until="domcontentloaded", timeout=90000)
                upload.checkpoint(page)
                tab = page.get_by_role("tab", name="Reels", exact=True)
                if tab.count() == 1:
                    tab.click()
                else:
                    page.goto(reels_url(entry["url"]), wait_until="domcontentloaded", timeout=90000)
                upload.checkpoint(page)
                try:
                    page.locator('a[href*="/reel/"], a[href*="v="]').first.wait_for(state="visible", timeout=30000)
                except Exception:
                    pass
                report["checks"]["reel_links_on_page"] = page.evaluate("""() => {
                  const urls = [...document.querySelectorAll('a[href]')].map(a => {
                    const u = new URL(a.href);
                    if (!['facebook.com','www.facebook.com'].includes(u.hostname)) return null;
                    if (/^\\/reel\\/[0-9]+\\/?$/.test(u.pathname)) return u.origin + u.pathname;
                    const id = u.searchParams.get('v');
                    return id && /^[0-9]+$/.test(id) ? 'https://www.facebook.com/reel/' + id : null;
                  }).filter(Boolean);
                  return [...new Set(urls)].slice(0, 40);
                }""")
                report["checks"]["reel_details"] = inspect_known_reel(page, entry, row["permalink"], caption)
                # Reading page text below also lets queued response callbacks finish.
                page.title()
                report["checks"]["known_video_data"] = collector.items
                report["checks"]["video_data_responses_checked"] = collector.responses_checked
                print("只读检查完成，没有上传或发布视频。")
            except Exception as error:
                report["error"] = str(error)[:1400]
                print("检查未完成：", error)
            finally:
                context.close()
        destination = logs / "page_check.json"
        upload.save_json(destination, report)
        print("检查文件：", destination)
        print("请把 page_check.json 发来。文件不包含密码、Cookie 或访问令牌。")
        return 1 if "error" in report else 0
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as error:
        print("STOP：", error)
        raise SystemExit(1)
