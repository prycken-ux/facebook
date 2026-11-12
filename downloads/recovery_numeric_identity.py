"""Recovery-only identity gates: numeric owner/actor, with visible picker fallback."""
import contextlib
import re
import time

import fb_upload as upload
import page_profile_switch as picker

VERSION = '1.0-numeric-actor-with-guided-picker'


def guard(page, entry, marker):
    upload.checkpoint(page)
    upload.require_no_advanced_protection(page)
    if picker.login_marker(page) != marker:
        raise RuntimeError('核验期间登录者变化；未选择视频或点击发布。')
    if upload.target_key(page.url) != upload.target_key(entry['url']):
        raise RuntimeError('当前主页网址与目标数字ID不一致；未选择视频或点击发布。')


def actor_ok(page, entry):
    if entry['type'] == 'personal':
        try:
            upload.personal_actor_fingerprint(page, entry)
            return True
        except upload.PageActorActive:
            return False
    try:
        return upload.page_actor_matches(page, entry)
    except RuntimeError:
        return False


def wait_actor(page, entry, marker, timeout_ms):
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        upload.checkpoint(page)
        if picker.login_marker(page) != marker:
            raise RuntimeError('主页切换期间登录者变化，已停止。')
        if actor_ok(page, entry) and picker.picker_dialog(page) is None:
            if upload.target_key(page.url) != upload.target_key(entry['url']):
                upload.navigate_profile(page, entry['url'])
            guard(page, entry, marker)
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('自动切换后尚未取得目标数字身份。')
        page.wait_for_timeout(150)


def ensure(page, entry, timeout_ms=15000, interactive=True):
    if not upload.target_key(entry['url']).startswith('id:'):
        raise RuntimeError('本次恢复只接受已核验的数字ID主页。')
    marker = picker.login_marker(page)
    guard(page, entry, marker)
    switched = False
    if not actor_ok(page, entry):
        try:
            # A missing heading must not prevent opening the known picker.
            switch = upload.visible_page_switch(page) if entry['type'] == 'page' else None
            if switch is not None:
                switch.click(timeout=timeout_ms)
            else:
                picker.select_configured_profile(page, entry, marker, time.monotonic() + timeout_ms / 1000)
            wait_actor(page, entry, marker, timeout_ms)
            switched = True
        except Exception as error:
            # A login/checkpoint/owner change cannot be overridden by Enter.
            upload.checkpoint(page)
            upload.require_no_advanced_protection(page)
            if picker.login_marker(page) != marker:
                raise RuntimeError('自动切换期间登录者变化，已停止。') from None
            if not interactive:
                raise
            print('自动身份切换未完成：', str(error).split('\n', 1)[0], flush=True)
            while True:
                print('请在当前Chrome右上角切换到：', entry['name'], entry['url'], flush=True)
                answer = input('仅切换身份，勿手动发视频。完成后回车核验；S跳过，Q结束：').strip().upper()
                if answer == 'Q':
                    raise KeyboardInterrupt
                if answer == 'S':
                    raise RuntimeError('用户跳过未核验的身份；未选择视频或点击发布。')
                if answer:
                    continue
                upload.checkpoint(page)
                if picker.login_marker(page) != marker:
                    raise RuntimeError('人工切换期间登录者变化，已停止。')
                if actor_ok(page, entry):
                    if upload.target_key(page.url) != upload.target_key(entry['url']):
                        upload.navigate_profile(page, entry['url'])
                    guard(page, entry, marker)
                    switched = True
                    break
                print('数字身份仍未匹配，未选择文件；请检查右上角当前身份。', flush=True)
    guard(page, entry, marker)
    if not actor_ok(page, entry):
        raise RuntimeError('目标数字身份未通过最终核验。')
    proof = dict(target_url=entry['url'], name=entry['name'], switched=switched, recovery_login_marker=marker,
                 method='personal_actor_id_match' if entry['type'] == 'personal' else 'page_actor_id_match')
    if entry['type'] == 'personal':
        proof['session_marker'] = upload.personal_actor_fingerprint(page, entry)
    print('数字身份核验通过：', entry['account'], entry['target'], entry['name'], entry['url'], flush=True)
    return proof


def public_name(page):
    names = set()
    for node in page.get_by_role('heading', level=1).all():
        if node.is_visible() and node.evaluate(upload.PROFILE_NAME_ALLOWED_JS):
            name = node.inner_text().strip()
            if name:
                names.add(name)
    if len(names) == 1:
        return next(iter(names))
    # Responsive profiles can omit h1. Metadata is only a candidate; require
    # the exact public name visibly outside feed/menu/sidebar/dialog content.
    candidates = [page.title()]
    meta = page.locator('meta[property="og:title"]')
    if meta.count() == 1:
        candidates.append(meta.get_attribute('content') or '')
    for candidate in candidates:
        candidate = re.sub(r'^\(\d+\)\s*', '', candidate)
        candidate = re.sub(r'\s*[|–-]\s*Facebook\s*$', '', candidate, flags=re.I).strip()
        if not candidate or candidate.lower() == 'facebook':
            continue
        for node in page.get_by_text(candidate, exact=True).all():
            if node.is_visible() and node.evaluate(upload.PROFILE_NAME_ALLOWED_JS):
                names.add(candidate)
    return next(iter(names)) if len(names) == 1 else None


@contextlib.contextmanager
def scoped(pairs):
    original = upload.ensure_identity
    original_recheck = upload.recheck_publish_identity
    owners = {}
    def identify(page, entry):
        pair = (entry.get('account'), entry.get('target'))
        if pair not in pairs:
            return original(page, entry)
        config = upload.read_json(upload.CONFIG, {})
        targets = [r for r in config.get('targets', []) if (r.get('account'), r.get('target')) == pair]
        if len(targets) != 1 or upload.target_key(targets[0]['url']) != upload.target_key(entry['url']):
            raise RuntimeError('恢复身份与当前唯一登记目标不一致。')
        marker = picker.login_marker(page)
        if owners.setdefault(entry['account'], marker) != marker:
            raise RuntimeError('本次恢复运行期间账号登录者发生变化。')
        return ensure(page, entry)
    def recheck(page, entry, proof):
        if proof.get('recovery_login_marker') and picker.login_marker(page) != proof['recovery_login_marker']:
            raise RuntimeError('选择视频后登录者变化；未点击发布。')
        return original_recheck(page, entry, proof)
    upload.ensure_identity = identify
    upload.recheck_publish_identity = recheck
    try:
        yield
    finally:
        upload.ensure_identity = original
        upload.recheck_publish_identity = original_recheck
