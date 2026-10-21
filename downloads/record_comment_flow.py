"""Open the existing account in Playwright Inspector for manual flow recording."""
import argparse
from datetime import datetime
import os
import sys
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from playwright.sync_api import sync_playwright
import fb_upload as upload


def safe_facebook_url(url):
    view = urlparse(url)
    if (view.scheme != 'https' or view.hostname not in {'facebook.com', 'www.facebook.com'}
            or view.username or view.password or view.port):
        raise RuntimeError('请保留在 Facebook 评论页面，未保存其他网站内容。')
    allowed = {'id', 'comment_id', 'reply_comment_id', 'locale', 'sk'}
    return urlunparse(view._replace(
        query=urlencode([(k,v) for k,v in parse_qsl(view.query) if k in allowed]), fragment=''))


def save_comment_view(page, entry):
    """Capture visible UI for selector adaptation, never credentials or cookies."""
    upload.checkpoint(page)
    view_url = safe_facebook_url(page.url)
    target_url = safe_facebook_url(entry['url'])
    fields = page.locator('input[type="password"]')
    if any(fields.nth(i).is_visible() for i in range(fields.count())):
        raise RuntimeError('当前是登录页面，未保存页面结构。')
    snapshot = page.locator('body').aria_snapshot()
    if not isinstance(snapshot, str) or not snapshot.strip():
        raise RuntimeError('未取得有效页面结构。')
    folder = upload.ROOT / 'logs' / 'comment-recordings' / (
        entry['account'] + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'comments.aria.txt').write_text(snapshot, encoding='utf-8')
    page.screenshot(path=str(folder / 'comments.png'))
    upload.save_json(folder / 'context.json', {
        'account': entry['account'], 'target': entry['target'], 'type': entry['type'],
        'target_url': target_url, 'view_url': view_url,
        'captured_at': datetime.now().astimezone().isoformat(),
        'purpose': 'comment_ui_adaptation_only',
    })
    print('已保存评论区截图与页面结构：', folder, flush=True)
    return folder


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
                print('录制到回复输入框即可，不用发送；可将录制代码复制保存为 Python 文件。', flush=True)
                print('保持评论区和回复框展开，点 Inspector 的 Resume；工具会保存截图和页面结构后结束。', flush=True)
                print('程序不会自动上传视频或发送评论。', flush=True)
                page.pause()
                save_comment_view(page, entry)
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
