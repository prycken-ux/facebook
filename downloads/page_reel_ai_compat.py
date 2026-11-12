"""Handle styled AI controls using their checked state, including hidden inputs."""
import contextlib
import re
import time
import fb_upload as upload

VERSION = '1.0-styled-ai-controls'


class AIControlNotReady(RuntimeError):
    pass


def read_state(control):
    info = control.evaluate("""e=>({native:e.tagName==='INPUT'&&e.type==='checkbox',
        checked:e.checked,aria:e.getAttribute('aria-checked'),pressed:e.getAttribute('aria-pressed'),
        disabled:Boolean(e.disabled)||e.getAttribute('aria-disabled')==='true'})""")
    if info['disabled']:
        raise AIControlNotReady('AI标签控件尚未可用，未点击发布。')
    if info['native']:
        return bool(info['checked'])
    value = info['aria'] if info['aria'] is not None else info['pressed']
    if value not in {'true', 'false'}:
        raise RuntimeError('AI标签没有可核验的开关状态，未点击发布。')
    return value == 'true'


def ai_control(page):
    labels = page.get_by_role('button', name=re.compile(r'^Add AI label\b'))
    visible = [labels.nth(i) for i in range(labels.count()) if labels.nth(i).is_visible()]
    if len(visible) > 1:
        raise RuntimeError('AI标签有多个可见入口，未猜选。')
    if len(visible) == 1:
        label = visible[0]
        nested = label.locator('input[type="checkbox"],[role="switch"],[role="checkbox"]')
        # React can expose the same native input with role=checkbox; the CSS
        # union returns that element once. Hidden native checked state is valid
        # only inside this uniquely identified visible AI control.
        if nested.count() == 1:
            control = nested.first
            read_state(control)
            return control, control if control.is_visible() else label
        if nested.count() > 1:
            raise RuntimeError('AI标签关联多个开关，未猜选。')
        if label.get_attribute('aria-checked') is not None or label.get_attribute('aria-pressed') is not None:
            read_state(label)
            return label, label
    matches = []
    for role in ('switch', 'checkbox'):
        controls = page.get_by_role(role, name='Add AI label', exact=True)
        matches.extend(controls.nth(i) for i in range(controls.count()) if controls.nth(i).is_visible())
    if len(matches) == 1:
        read_state(matches[0])
        return matches[0], matches[0]
    if matches:
        raise RuntimeError('AI标签状态控件不唯一，未点击发布。')
    raise AIControlNotReady('未识别到唯一AI标签状态控件，未点击发布。')


def set_modern_ai(page, entry, timeout_ms=30000):
    desired = bool(entry.get('ai_label', False))
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        upload.checkpoint(page)
        upload.require_no_advanced_protection(page)
        try:
            control, clicker = ai_control(page)
            break
        except AIControlNotReady:
            if time.monotonic() >= deadline:
                raise
            page.wait_for_timeout(200)
    current = read_state(control)
    if current != desired:
        # Normal pointer checks remain in force. Never click through an overlay
        # or manipulate checked properties with JavaScript.
        clicker.click(timeout=max(1, int((deadline-time.monotonic())*1000)))
    while read_state(control) != desired:
        upload.checkpoint(page)
        if time.monotonic() >= deadline:
            raise RuntimeError('AI标签点击后状态未匹配，未点击发布。')
        page.wait_for_timeout(100)
    print('AI标签已核对：', '开启' if desired else '关闭', '；支持隐藏原生开关的新布局。', flush=True)


@contextlib.contextmanager
def installed():
    original = upload.set_ai_label
    def set_label(page, entry, modern=False):
        if modern:
            return set_modern_ai(page, entry)
        return original(page, entry, modern=modern)
    upload.set_ai_label = set_label
    try:
        yield
    finally:
        upload.set_ai_label = original
