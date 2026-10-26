"""Capture the actual account-button and profile-picker accessibility labels."""
import argparse
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import fb_upload as upload
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window, select_pairs

ROOT = Path(__file__).resolve().parent
CONTROLS_JS = r'''root => Array.from(root.querySelectorAll('button,a,[role="button"],[role="link"]')).filter(el => {
    const style=getComputedStyle(el);
    return el.getClientRects().length && style.visibility!=='hidden' && style.display!=='none';
}).slice(0,60).map(el => ({tag:el.tagName,role:el.getAttribute('role'),
    label:el.getAttribute('aria-label'),title:el.getAttribute('title'),text:(el.innerText||'').slice(0,160),
    hasPopup:el.getAttribute('aria-haspopup'),expanded:el.getAttribute('aria-expanded'),
    images:Array.from(el.querySelectorAll('img,svg[role="img"]')).slice(0,3).map(img=>({
        label:img.getAttribute('aria-label'),alt:img.getAttribute('alt'),title:img.getAttribute('title')}))}))'''


def clean_aria(snapshot):
    # Link destinations and incidental URLs are unnecessary for locating controls.
    lines=[]
    for line in snapshot.splitlines():
        if re.match(r'\s*- /url:',line):
            continue
        line=re.sub(r'^(\s*- (?:textbox|combobox|searchbox)(?: "[^"\n]*")?(?: \[[^\]\n]*\])?):.*$',r'\1',line)
        lines.append(line)
    return '\n'.join(lines)[:40000]


def capture(page, folder, label):
    upload.checkpoint(page)
    folder.mkdir(parents=True, exist_ok=True)
    sections = []
    for role in ('banner', 'menu', 'dialog'):
        regions = page.get_by_role(role)
        for index in range(regions.count()):
            region = regions.nth(index)
            if not region.is_visible():
                continue
            prefix = label + '-' + role + '-' + str(index)
            try:
                snapshot = clean_aria(region.aria_snapshot(timeout=5000))
                (folder / (prefix + '.txt')).write_text(snapshot, encoding='utf-8')
                sections.append(dict(role=role,index=index,controls=region.evaluate(CONTROLS_JS,timeout=5000)))
            except Exception:
                sections.append(dict(role=role,index=index,unavailable=True))
    upload.save_json(folder / (label + '-controls.json'), sections)
    page.screenshot(path=str(folder / (label + '.png')), timeout=10000)


def wait_for_picker(page, read=input):
    while True:
        print('请在浏览器点右上角头像 → See all profiles，展开 Your profiles & Pages 列表。', flush=True)
        print('列表展开后回到此窗口，输入 READY 并回车；取消请输入 CANCEL。', flush=True)
        try:
            answer = read('READY / CANCEL: ').strip().upper()
        except EOFError:
            raise RuntimeError('输入已关闭，已取消本次采集。') from None
        if answer == 'CANCEL':
            raise RuntimeError('已取消本次采集。')
        if answer != 'READY':
            print('等待输入 READY 或 CANCEL。', flush=True)
            continue
        upload.checkpoint(page)
        regions = page.get_by_role('dialog').filter(has=page.get_by_text(re.compile(r'^Your profiles\s*(?:&|and)\s*Pages$',re.I)))
        if sum(regions.nth(i).is_visible() for i in range(regions.count())) == 1:
            return
        # A new layout without dialog semantics is itself useful diagnostic data;
        # record it without assuming a particular container role or selecting rows.
        print('将记录当前已展开界面及其控件标签。', flush=True)
        return


def main():
    parser = argparse.ArgumentParser(description='采集账号头像和公共主页选择列表，不选择主页或发布视频')
    parser.add_argument('--account', default='fb10')
    parser.add_argument('--target', default='page04')
    parser.add_argument('--close-windows', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'fb(?:0[1-9]|[1-9][0-9]+)',args.account) or not re.fullmatch(r'page[0-9]{2,}',args.target):
        raise ValueError('请指定有效的账号和公共主页编号。')
    with locked():
        entries, _ = select_pairs([(args.account,args.target)])
        entry = entries[0]
        if args.close_windows:
            close_selected_window(args.account)
        folder = ROOT / 'logs' / ('profile-switch-ui-' + args.account + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        folder.mkdir(parents=True)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            context = upload.launch_context(playwright, entry)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=90000)
                capture(page, folder, 'initial')
                wait_for_picker(page)
                capture(page, folder, 'picker')
                # If no dialog is exposed, collect only control labels globally;
                # do not serialize form values, messages, links or raw DOM.
                dialogs = page.get_by_role('dialog')
                if not any(dialogs.nth(i).is_visible() for i in range(dialogs.count())):
                    upload.save_json(folder/'picker-page-controls.json',page.locator('body').evaluate(CONTROLS_JS,timeout=5000))
            finally:
                context.close()
        output = ROOT / 'logs' / ('profile-switch-ui-' + args.account + '.zip')
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in folder.iterdir():
                if path.is_file():
                    archive.write(path,path.name)
        print('采集完成，请上传：',output,flush=True)
        return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print('STOP：',str(error).splitlines()[0],flush=True)
        raise SystemExit(1)
