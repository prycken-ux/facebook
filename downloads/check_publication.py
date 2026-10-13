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


def reels_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["sk"] = ["reels_tab"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True), fragment=""))


def inspect_known_reel(page, entry, permalink, caption):
    page.goto(permalink, wait_until="domcontentloaded", timeout=90000)
    upload.checkpoint(page)
    prefix = " ".join(caption.split())[:100]
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
      const norm = text => text.replace(/\\s+/g, ' ').trim();
      const body = norm(document.body.innerText);
      const authorLinks = [...document.querySelectorAll('a[href]')]
        .filter(a => norm(a.innerText) === name)
        .map(a => {
          const u = new URL(a.href);
          if (!['facebook.com','www.facebook.com'].includes(u.hostname)) return null;
          const id = u.searchParams.get('id');
          return {text: norm(a.innerText), url: u.origin + u.pathname + (id ? '?id=' + id : '')};
        }).filter(Boolean);
      return {caption_prefix_present: Boolean(prefix && body.includes(prefix)),
              full_caption_present: Boolean(caption && body.includes(norm(caption))),
              author_links: authorLinks.slice(0, 15)};
    }""", {"name": entry["name"], "prefix": prefix, "caption": caption})
    result["known_reel_url"] = permalink
    result["caption_prefix"] = prefix
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
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(30000)
                page.goto(reels_url(entry["url"]), wait_until="domcontentloaded", timeout=90000)
                upload.checkpoint(page)
                try:
                    page.locator('a[href*="/reel/"]').first.wait_for(state="visible", timeout=30000)
                except Exception:
                    pass
                report["checks"]["reel_links_on_page"] = page.evaluate("""() => {
                  const urls = [...document.querySelectorAll('a[href]')].map(a => {
                    const u = new URL(a.href);
                    if (!['facebook.com','www.facebook.com'].includes(u.hostname)) return null;
                    return /^\\/reel\\/[0-9]+\\/?$/.test(u.pathname) ? u.origin + u.pathname : null;
                  }).filter(Boolean);
                  return [...new Set(urls)].slice(0, 40);
                }""")
                report["checks"]["reel_details"] = inspect_known_reel(page, entry, row["permalink"], caption)
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
