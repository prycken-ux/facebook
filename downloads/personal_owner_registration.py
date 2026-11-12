"""Register proven current personal owners; no video selection or publication."""
import contextlib
import copy
import re
import sys
import time
from datetime import datetime,timezone
import recover_nov11_missed_20261112 as old
import personal_owner_routes as routes
import page_reel_ai_compat as editor
upload=old.upload
BASE_REGISTRATION=old.registration_plan
DAY='2026-11-12'
NAME_REUSE_VERSION='1.0-verified-owner-name-cache'


def clean_name(value):
    if not isinstance(value,str):return None
    value=re.sub(r'^\([0-9+]+\)\s*','',value.strip())
    value=re.sub(r'\s*[|–-]\s*Facebook\s*$','',value,flags=re.I).strip()
    if (not value or len(value)>200 or any(ord(c)<32 for c in value)
            or value.casefold() in {'facebook','meta','log in to facebook','sign up for facebook','log in or sign up','confirm your identity','登录 facebook','登录facebook'}):return None
    if re.fullmatch(r'Facebook\s*[-–—|:]\s*(?:log in or sign up|登录或注册)',value,re.I):return None
    return value


def cached_name(account,entry,proof):
    owner=upload.target_key(entry['url'])
    keys={owner}|set(proof.get('verified_aliases',[]))
    sources=[upload.read_json(upload.CONFIG,{}).get('targets',[]),
             upload.read_json(upload.ROOT/'account_registry.json',{}).get('accounts',[])]
    slot=upload.read_json(upload.ROOT/'additional_personal_accounts.json',{}).get('slots',{}).get(account,{})
    sources.append([slot.get('mapping',{})])
    for rows in sources:
        names=set()
        for row in rows:
            if (not isinstance(row,dict) or row.get('account')!=account or row.get('target','personal')!='personal'
                    or row.get('type')!='personal'):continue
            try:matches=upload.target_key(row.get('url','')) in keys
            except ValueError:matches=False
            name=clean_name(row.get('name'))
            if matches and name:names.add(name)
        if len(names)>1:raise ValueError('同一本人身份保存了不同名称，未猜选或覆盖。')
        if names:return next(iter(names))
    return None


def automatic_name(page,account,entry,proof):
    # Called only after numeric owner and /me alias verification. Never reuse
    # the previous person on a reused account number.
    routes.stable_actor(page,entry,proof['recovery_login_marker'])
    saved=cached_name(account,entry,proof)
    if saved:
        print('自动沿用已保存的本人名称：',account,saved,flush=True)
        return saved
    name=clean_name(routes.numeric.public_name(page))
    if name:return name
    meta=page.locator('meta[property="og:title"]')
    if meta.count()==1:
        name=clean_name(meta.get_attribute('content'))
        if name:return name
    return clean_name(page.title())


def register_alias(config,registry,manifest,account,entry,proof,old_fb17):
    config,registry,manifest=copy.deepcopy((config,registry,manifest))
    aliases=set(proof.get('verified_aliases',[]))
    if account!='fb17':
        for row in config['targets']+registry['accounts']:
            if row.get('account')==account and upload.target_key(row.get('url','')) in aliases:
                row['url']=entry['url']  # Same proven owner; canonicalize, do not replace a person.
    result=BASE_REGISTRATION(config,registry,manifest,account,entry,proof,old_fb17)
    row=next(r for r in result[0]['targets'] if r['account']==account)
    row['personal_route_validation']=dict(version=routes.VERSION,aliases=sorted(aliases),route_method=proof['route_method'],checked_at=proof['checked_at'])
    return result


def discover(account):
    from playwright.sync_api import sync_playwright
    profile=upload.ROOT/'profiles'/account
    if not profile.is_dir() or profile.is_symlink():raise ValueError('原登录资料缺失，未创建空白资料。')
    old.assert_free(account);old.close_selected_window(account)
    probe=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',name='Current personal owner',url='https://www.facebook.com/me',auto_switch_personal=True)
    with sync_playwright() as pw:
        context=old.normal.launch_normal(pw,probe)
        try:
            page=context.pages[-1] if context.pages else context.new_page()
            people={c['value'] for c in context.cookies(['https://www.facebook.com/']) if c.get('name')=='c_user' and str(c.get('value','')).isdecimal()}
            if len(people)!=1:raise ValueError('当前登录身份不唯一，请在该编号原窗口完成登录。')
            owner=next(iter(people));entry=dict(probe,url='https://www.facebook.com/profile.php?id='+owner)
            upload.navigate_profile(page,entry['url'])
            proof=routes.ensure_personal(page,entry)
            name=None;deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                routes.stable_actor(page,entry,proof['recovery_login_marker'])
                name=automatic_name(page,account,entry,proof)
                if name:break
                page.wait_for_timeout(200)
            if not name:
                raise ValueError('本人身份已核验，但保存记录和页面信息均未提供有效名称；本账号已记录待处理，不等待手动输入。')
            if not name or len(name)>200 or any(ord(c)<32 for c in name):raise ValueError('本人主页名称无效。')
            entry['name']=name;proof.update(name=name,checked_at=datetime.now(timezone.utc).isoformat())
            if routes.stable_actor(page,entry,proof['recovery_login_marker'])!=proof['session_marker']:
                raise ValueError('登记期间本人身份变化。')
            return entry,proof
        finally:context.close()


@contextlib.contextmanager
def launcher(value):
    original=upload.launch_context
    upload.launch_context=old.normal.launcher_for_jobs(value['payload']['jobs'],date=DAY)
    try:yield
    finally:upload.launch_context=original

