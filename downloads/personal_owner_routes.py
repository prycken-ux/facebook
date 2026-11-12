"""Verify numeric personal owners even when Facebook redirects to a vanity URL."""
import contextlib
from urllib.parse import urlparse
import fb_upload as upload
import recovery_numeric_identity as numeric

VERSION='1.0-me-bound-personal-aliases'
NON_PROFILES={'me','friends','notifications','bookmarks','groups','marketplace','search','gaming','privacy','help','recover','login.php','account','accounts'}


def stable_actor(page,entry,login):
    upload.checkpoint(page)
    upload.require_no_advanced_protection(page)
    if numeric.picker.login_marker(page)!=login:
        raise RuntimeError('核验期间登录者变化，未选择视频或点击发布。')
    return upload.personal_actor_fingerprint(page,entry)


def canonical(page):
    values=page.locator('link[rel="canonical"]')
    if values.count()!=1:return None
    try:return upload.target_key(values.get_attribute('href') or '')
    except ValueError:return None


def ensure_personal(page,entry):
    expected=upload.target_key(entry['url'])
    if entry.get('type')!='personal' or not expected.startswith('id:'):
        raise ValueError('此恢复核验只接受确切数字ID的个人主页。')
    login=numeric.picker.login_marker(page)
    try:marker=stable_actor(page,entry,login)
    except upload.PageActorActive:
        while True:
            print('请在当前窗口右上角切回登录者的个人主页：',entry['account'],entry['url'],flush=True)
            value=input('仅切换身份，勿手动发布；完成后回车核验，S跳过，Q结束：').strip().upper()
            if value=='Q':raise KeyboardInterrupt
            if value=='S':raise RuntimeError('用户跳过尚未切回本人的账号，未发布。')
            if value:continue
            try:marker=stable_actor(page,entry,login);break
            except upload.PageActorActive:continue
        upload.navigate_profile(page,entry['url'])
    current=upload.target_key(page.url)
    aliases=[]
    if current!=expected:
        if not current.startswith('slug:') or current[5:].casefold() in NON_PROFILES:
            raise RuntimeError('当前不是可核验的本人主页网址；未选择或发布视频。')
        initial=current
        initial_canonical=canonical(page)
        # A displayed name and cookies alone cannot bind an arbitrary vanity
        # URL. /me must resolve to it, or supply a canonical numeric mapping.
        upload.navigate_profile(page,'https://www.facebook.com/me')
        upload.checkpoint(page)
        page.wait_for_url(lambda url:urlparse(str(url)).path.rstrip('/')!='/me',timeout=30000)
        if stable_actor(page,entry,login)!=marker:
            raise RuntimeError('本人主页入口核验期间个人身份变化。')
        own=upload.target_key(page.url)
        if own!=initial and not (own==expected and (initial_canonical==expected or canonical(page)==initial)):
            raise RuntimeError('短网址未通过Facebook本人主页入口核验；未发布。')
        aliases=[initial]
        upload.navigate_profile(page,entry['url'])
        if stable_actor(page,entry,login)!=marker or upload.target_key(page.url) not in {expected,initial}:
            raise RuntimeError('返回本人主页后网址或身份变化，未发布。')
    if stable_actor(page,entry,login)!=marker:
        raise RuntimeError('个人身份核验期间发生变化。')
    proof=dict(target_url=entry['url'],name=entry['name'],method='personal_actor_id_match',session_marker=marker,
               recovery_login_marker=login,verified_aliases=aliases,route_method='me_redirect_owner_match' if aliases else 'numeric_owner_match')
    print('本人主页归属核验通过：',entry['account'],entry['url'],'；已验证短网址：',', '.join(a[5:] for a in aliases) or '数字ID直接匹配',flush=True)
    return proof


@contextlib.contextmanager
def scoped(accounts):
    original=upload.ensure_identity
    original_recheck=upload.recheck_publish_identity
    def ensure(page,entry):
        if entry.get('account') not in accounts or entry.get('target')!='personal':return original(page,entry)
        rows=[r for r in upload.read_json(upload.CONFIG,{}).get('targets',[]) if (r.get('account'),r.get('target'))==(entry['account'],'personal')]
        if len(rows)!=1 or upload.target_key(rows[0]['url'])!=upload.target_key(entry['url']):
            raise RuntimeError('当前登记身份与本次确切个人号不一致。')
        return ensure_personal(page,entry)
    def recheck(page,entry,proof):
        if proof.get('recovery_login_marker') and numeric.picker.login_marker(page)!=proof['recovery_login_marker']:
            raise RuntimeError('选择视频后登录者变化，未点击发布。')
        return original_recheck(page,entry,proof)
    upload.ensure_identity=ensure
    upload.recheck_publish_identity=recheck
    try:yield
    finally:
        upload.ensure_identity=original
        upload.recheck_publish_identity=original_recheck
