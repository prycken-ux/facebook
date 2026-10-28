"""Switch between existing managed Pages using the visible profile picker."""
import hashlib
import re
import time

import fb_upload as upload

PICKER_TITLE = re.compile(r'^(Your profiles\s*(?:&|and)\s*Pages|Profiles\s*&\s*Pages|你的个人主页和公共主页|您的个人主页和公共主页)$', re.I)
ACCOUNT_BUTTON = re.compile(r'^(Your profile|Account, your profile|Account|Your profile and settings|Account controls and settings|个人主页|你的个人主页|账户|帐户|账号)$', re.I)
ACCOUNT_WITH_NAME = re.compile(r'^(Your profile|Your profile and settings|Account controls and settings|你的个人主页|账户|帐户|账号)[,:，：]\s*\S.+$', re.I)
ALL_PROFILES = re.compile(r'^(See all profiles|See all profiles and Pages|查看所有个人主页|查看所有主页|查看全部个人主页|查看所有个人主页和公共主页)$', re.I)
SEARCH_PROFILES = re.compile(r'^(Search profiles and Pages|Search profiles|搜索个人主页和公共主页|搜索个人主页)$', re.I)


def login_marker(page):
    try:
        people = {c['value'] for c in page.context.cookies(['https://www.facebook.com/'])
                  if c.get('name') == 'c_user' and c.get('value')}
    except Exception:
        raise RuntimeError('无法核对主页切换前后的登录者身份。') from None
    if len(people) != 1 or not next(iter(people)).isdecimal():
        raise RuntimeError('缺少唯一的登录者身份，未操作公共主页选择列表。')
    return hashlib.sha256(('person:' + next(iter(people))).encode('ascii')).hexdigest()


def unique_visible(choices, label):
    visible = [choices.nth(i) for i in range(choices.count()) if choices.nth(i).is_visible()]
    if len(visible) > 1:
        raise RuntimeError(label + '存在多个可见入口，未猜选。')
    return visible[0] if visible else None


def picker_dialog(page):
    choices = page.get_by_role('dialog').filter(has=page.get_by_text(PICKER_TITLE))
    return unique_visible(choices, '个人主页和公共主页列表')


def remaining(deadline, limit=10000):
    left = int((deadline - time.monotonic()) * 1000)
    if left <= 0:
        raise RuntimeError('公共主页列表切换超时，未选择视频或点击发布。')
    return min(left, limit)


def wait_value(page, deadline, probe, label, marker):
    stage = min(deadline, time.monotonic() + 10)
    while True:
        upload.checkpoint(page)
        if login_marker(page) != marker:
            raise RuntimeError('公共主页切换过程中登录者身份变化，已停止。')
        value = probe()
        if value is not None:
            return value
        if time.monotonic() >= stage:
            raise RuntimeError(label + '未加载，未选择视频或点击发布。')
        page.wait_for_timeout(min(200, remaining(stage)))


def exact_control(scope, pattern):
    for choices in (scope.get_by_role('button', name=pattern), scope.get_by_role('link', name=pattern),
                    scope.get_by_text(pattern)):
        control = unique_visible(choices, '主页切换控件')
        if control is not None:
            return control
    return None


def see_all_profiles_control(page):
    found = []
    for role in ('menu', 'dialog'):
        menus = page.get_by_role(role)
        for index in range(menus.count()):
            menu = menus.nth(index)
            if menu.is_visible():
                control = exact_control(menu, ALL_PROFILES)
                if control is not None:
                    found.append(control)
    if len(found) > 1:
        raise RuntimeError('存在多个查看所有个人主页菜单，未猜选。')
    return found[0] if found else None


def account_control(page):
    # Some layouts place account controls next to, rather than inside, banner.
    # Require a named account action outside content and existing dialogs; never
    # infer the avatar by image position, a profile name, or an unnamed button.
    allowed = '''el => !el.closest('main,[role="main"],article,[role="article"],' +
        '[role="feed"],aside,[role="complementary"],[role="dialog"],[role="menu"]')'''
    visible = []
    for pattern in (ACCOUNT_BUTTON, ACCOUNT_WITH_NAME):
        for role in ('button', 'link'):
            choices = page.get_by_role(role, name=pattern)
            for index in range(choices.count()):
                choice = choices.nth(index)
                if choice.is_visible() and choice.evaluate(allowed, timeout=1000):
                    visible.append(choice)
    # The supplied live header is visually present, while role-scoped captures
    # sometimes return no banner/navigation at all. Accept the exact recorded
    # button attribute as a DOM fallback only when role lookup found nothing.
    # This does not guess by position, nested image, notification icon or name.
    if not visible:
        choices = page.locator('[role="button"][aria-label="Account, your profile" i]')
        for index in range(choices.count()):
            choice = choices.nth(index)
            if choice.is_visible() and choice.evaluate(allowed, timeout=1000):
                visible.append(choice)
    if len(visible) > 1:
        raise RuntimeError('账号头像存在多个可见入口，未猜选。')
    return visible[0] if visible else None


def switch_page_from_picker(page, entry, timeout_ms=60000):
    """Choose one exact configured Page name, then require its numeric actor ID.

    The visible picker opens under the account avatar. Name selection authorizes
    a switch attempt only: successful proof still requires unchanged login owner,
    the target's exact i_user ID, and navigation back to the configured URL.
    """
    upload.checkpoint(page)
    if entry.get('type') != 'page' or not upload.target_key(entry['url']).startswith('id:'):
        raise RuntimeError('公共主页选择列表只用于已配置的数字 ID 公共主页。')
    if upload.target_key(page.url) != upload.target_key(entry['url']):
        raise RuntimeError('当前网址不是待核验的公共主页，未打开切换列表。')
    marker = login_marker(page)
    deadline = time.monotonic() + timeout_ms / 1000
    dialog = picker_dialog(page)
    if dialog is None:
        # Do not toggle an already-open account menu closed.
        see_all = see_all_profiles_control(page)
        if see_all is None:
            account = wait_value(page, deadline, lambda: account_control(page), '账号头像入口', marker)
            account.click(timeout=remaining(deadline))
        dialog = picker_dialog(page)
        if dialog is None:
            see_all = wait_value(page, deadline, lambda: see_all_profiles_control(page), '查看所有个人主页入口', marker)
            see_all.click(timeout=remaining(deadline))
            dialog = wait_value(page, deadline, lambda: picker_dialog(page), '个人主页和公共主页列表', marker)
    choices = dialog.get_by_text(entry['name'], exact=True)
    target = unique_visible(choices, '目标公共主页名称')
    if target is None:
        # Only the labelled search field inside the known picker may be filled.
        search = unique_visible(dialog.get_by_role('textbox', name=SEARCH_PROFILES), '主页列表搜索框')
        if search is None:
            search = unique_visible(dialog.get_by_placeholder(SEARCH_PROFILES), '主页列表搜索框')
        if search is not None:
            search.fill(entry['name'], timeout=remaining(deadline))
        target = wait_value(page, deadline, lambda: unique_visible(choices, '目标公共主页名称'), '目标公共主页名称', marker)
    upload.checkpoint(page)
    if login_marker(page) != marker:
        raise RuntimeError('选择公共主页前登录者身份变化，已停止。')
    print('从个人主页和公共主页列表切换：', entry['name'], flush=True)
    target.click(timeout=remaining(deadline))
    while True:
        upload.checkpoint(page)
        if login_marker(page) != marker:
            raise RuntimeError('公共主页切换过程中登录者身份变化，已停止。')
        actor_matches = False
        try:
            actor_matches = upload.page_actor_matches(page, entry)
        except RuntimeError:
            # A stale actor is expected briefly during a real switch; it cannot
            # be accepted, nor can a matching display name override it.
            pass
        if actor_matches and picker_dialog(page) is None:
            break
        page.wait_for_timeout(min(200, remaining(deadline)))
    # Switching commonly keeps the configured Page open. Reloading that same
    # route can collide with the switch's own navigation and time out despite
    # the correct actor and usable UI. Navigate only if the switch left it.
    try:
        at_target = upload.target_key(page.url) == upload.target_key(entry['url'])
    except ValueError:
        at_target = False
    if not at_target:
        page.goto(upload.english_url(entry['url']), wait_until='commit', timeout=remaining(deadline, 30000))
    upload.checkpoint(page)
    if login_marker(page) != marker or not upload.page_actor_matches(page, entry):
        raise RuntimeError('返回目标公共主页后身份核对失败，未选择视频或点击发布。')
    if upload.target_key(page.url) != upload.target_key(entry['url']):
        raise RuntimeError('切换后的公共主页网址与配置不一致。')
    upload.wait_profile_name(page, entry, timeout_ms=45000)
    upload.checkpoint(page)
    if (login_marker(page) != marker or not upload.page_actor_matches(page, entry)
            or upload.target_key(page.url) != upload.target_key(entry['url'])):
        raise RuntimeError('主页内容加载后身份或网址变化，未选择视频或点击发布。')
    return True
