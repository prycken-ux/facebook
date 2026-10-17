"""Open the existing account in Playwright Inspector for manual flow recording."""
import argparse
import os
import sys
from playwright.sync_api import sync_playwright
import fb_upload as upload


def main():
    parser = argparse.ArgumentParser(description='录制评论操作供适配；程序不会自动发送回复')
    parser.add_argument('--account', required=True)
    parser.add_argument('--target')
    args = parser.parse_args()
    config = upload.read_json(upload.CONFIG, {'targets': []})
    entries = [entry for entry in config.get('targets', []) if entry.get('account') == args.account
               and (args.target is None or entry.get('target') == args.target)]
    if len(entries) != 1:
        print('STOP：没有唯一匹配的目标，请检查账号或指定 --target。')
        return 1
    entry = entries[0]
    upload.validate_entry(entry)
    lock = upload.ROOT / 'logs/upload.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print('STOP：上传任务正在运行或有遗留锁，请先核对。')
        return 2
    try:
        with os.fdopen(fd, 'w') as file:
            file.write(str(os.getpid()))
        with sync_playwright() as playwright:
            context = upload.launch_context(playwright, entry)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(upload.english_url(entry['url']), wait_until='domcontentloaded', timeout=90000)
                upload.ensure_identity(page, entry)
                upload.require_english_interface(page)
                print('已打开评论流程录制窗口：', entry['account'], entry['name'], flush=True)
                print('在 Inspector 中启用 Record，打开自己的视频和评论区，点 Reply 并输入测试文字。', flush=True)
                print('录制到输入框即可，不用发送；将录制代码复制保存为 Python 文件。', flush=True)
                print('完成后点 Inspector 的 Resume 结束。程序不会自动上传视频或发送评论。', flush=True)
                page.pause()
            finally:
                context.close()
        return 0
    except Exception:
        print('STOP：录制窗口未完成。请保留当前截图检查；本程序没有自动发送评论。')
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
