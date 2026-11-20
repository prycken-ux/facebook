"""Resolve only Reel audience information/loading prompts before Public checks."""
import re
import time

VERSION = '1.1-contenteditable-caption-audience-recovery'


class AudienceRecoveryBlocked(RuntimeError):
    pass


def guard(page):
    import fb_upload as upload
    try:
        upload.checkpoint(page)
        upload.require_no_advanced_protection(page)
    except Exception as error:
        raise AudienceRecoveryBlocked(str(error)) from error


SNAPSHOT = r'''e => {
 const visible=x=>{const s=getComputedStyle(x),r=x.getBoundingClientRect();return s.visibility!=='hidden'&&s.display!=='none'&&r.width>0&&r.height>0};
 const norm=s=>(s||'').replace(/\s+/g,' ').trim();
 const box=e.getBoundingClientRect();
 return {text:norm(e.innerText),label:norm(e.getAttribute('aria-label')),
  headings:[...e.querySelectorAll('h1,h2,h3,[role="heading"]')].filter(visible).map(x=>norm(x.innerText)),
  fields:e.querySelectorAll('textarea,input:not([type="hidden"]),[contenteditable="true"],[role="textbox"],[role="combobox"]').length,
  width:box.width,height:box.height,vw:innerWidth,vh:innerHeight};
}'''
KNOWN = re.compile(r'^(?:Review audience|Review your audience|检查受众|查看受众|檢查受眾)$', re.I)
UNSAFE = re.compile(r'log\s?in|sign\s?in|password|verification|captcha|security code|confirm.{0,35}account|advanced protection|discard|delete|leave reel|登录|登入|验证|驗證|密码|密碼|放弃|放棄|删除|刪除', re.I)
CLOSE = re.compile(r'^(?:Close|关闭|關閉|Dismiss)$', re.I)
CONTINUE = re.compile(r'^(?:Continue|继续|繼續)$', re.I)


def visible_buttons(dialog, pattern):
    matches = dialog.get_by_role('button', name=pattern)
    return [matches.nth(i) for i in range(matches.count()) if matches.nth(i).is_visible()]


def prompt(page, settings):
    candidates = []
    visible_other = False
    dialogs = page.get_by_role('dialog', include_hidden=True)
    for i in range(dialogs.count()):
        item = dialogs.nth(i)
        if not item.is_visible():
            continue
        # Never use the editor's own Close button, including nested dialogs.
        captions = item.get_by_role('textbox', name='Describe your reel...', exact=True, include_hidden=True)
        if captions.count():
            continue
        visible_other = True
        snap = item.evaluate(SNAPSHOT)
        if UNSAFE.search(snap['text'] + ' ' + snap['label']):
            continue
        known = bool(KNOWN.fullmatch(snap['label']) or any(KNOWN.fullmatch(t) for t in snap['headings']))
        skeleton = (not snap['headings'] and not snap['fields'] and not snap['label']
                    and re.fullmatch(r'(?:[×✕✖xX]|Close|Loading[.…]*|正在加载[.…]*|加载中[.…]*)?', snap['text']))
        if not known and not skeleton:
            continue
        if not (100 <= snap['width'] <= snap['vw'] * .95 and 45 <= snap['height'] <= snap['vh'] * .85):
            continue
        close = visible_buttons(item, CLOSE)
        onward = visible_buttons(item, CONTINUE) if known else []
        if len(onward) == 1:
            candidates.append((item, onward[0], 'Continue'))
        elif len(close) == 1:
            if skeleton:
                controls = item.locator('button,[role="button"],a[href],input,textarea,select,[contenteditable="true"]')
                if sum(controls.nth(j).is_visible() for j in range(controls.count())) != 1:
                    continue
            candidates.append((item, close[0], 'Close'))
    if len(candidates) > 1:
        raise AudienceRecoveryBlocked('公开范围提示不唯一，保留编辑器，不猜选关闭按钮。')
    return (candidates[0] if candidates else None), visible_other


def caption_value(field):
    """Read the actual native or contenteditable caption without changing it."""
    return field.evaluate("""e => {
      if (e instanceof HTMLInputElement || e instanceof HTMLTextAreaElement || e instanceof HTMLSelectElement) return e.value;
      if (e.isContentEditable) return e.innerText;
      throw new Error('Unsupported Reel caption editor; no prompt was clicked');
    }""")


def wait_for_public_controls(page, settings, choice, timeout_ms=60000, grace_ms=2500):
    """One normal Close/Continue click, then require real Public/Friends controls."""
    deadline = time.monotonic() + min(timeout_ms, 60000) / 1000
    first_seen = None
    acted = False
    field = settings.get_by_role('textbox', name='Describe your reel...', exact=True, include_hidden=True)
    if settings.count() != 1 or not settings.is_visible() or field.count() != 1:
        raise AudienceRecoveryBlocked('未确认唯一 Reel settings 编辑器，不自动关闭弹窗。')
    original_editor = settings.element_handle()
    original_caption = caption_value(field)
    while True:
        guard(page)
        candidate, visible_other = prompt(page, settings)
        if candidate:
            if acted:
                raise AudienceRecoveryBlocked('公开范围提示再次出现，保留当前视频并跳过，不反复点击。')
            if first_seen is None:
                first_seen = time.monotonic()
            if (time.monotonic() - first_seen) * 1000 >= grace_ms:
                dialog, button, action = candidate
                # Fix the actual elements: DOM changes must not retarget an editor Close.
                handle = button.element_handle()
                dialog_handle = dialog.element_handle()
                if handle is None or dialog_handle is None:
                    raise AudienceRecoveryBlocked('提示正在变化，未点击其他关闭按钮。')
                handle.click(timeout=min(5000, max(1, int((deadline-time.monotonic())*1000))))
                acted = True
                while dialog_handle.is_visible():
                    guard(page)
                    if time.monotonic() >= deadline:
                        raise AudienceRecoveryBlocked('公开范围提示操作后未消失，保留视频并跳过。')
                    page.wait_for_timeout(100)
                if (not original_editor.evaluate('e=>e.isConnected') or not settings.is_visible()
                        or caption_value(field) != original_caption):
                    raise AudienceRecoveryBlocked('提示操作后编辑器或文案发生变化，未点击发布。')
                print('已自动处理 Reel 公开范围提示：' + action + '；继续核对 Public。', flush=True)
                continue
        elif not visible_other and choice.count() == 1 and choice.is_visible():
            return
        else:
            first_seen = None
        if time.monotonic() >= deadline:
            raise AudienceRecoveryBlocked('公开范围仍未就绪或有未知弹窗，保留视频并跳过。')
        page.wait_for_timeout(100)
