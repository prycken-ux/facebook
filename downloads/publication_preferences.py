"""User-authorized persistent caption and excluded accounts, effective Nov 6."""
import hashlib,json,re,shutil,uuid
from datetime import date,datetime,timezone,timedelta
import fb_upload as upload
from apply_common_caption import atomic_caption

VERSION='1.0-exact-caption-excluded-accounts'
ACCOUNT_RESUMPTION_VERSION='1.0-effective-dated-resumption'
CONTENT_UPDATES_VERSION='1.0-frozen-caption-and-comment'
SCHEMA='publication-preferences-v1'
CAPTION='''A small decision can change the way a story unfolds.
What would you have done in this situation?

New perspectives through a good book.

Get your own copy on Amazon:
https://www.amazon.com/s?maas=maas_adg_B87EF70D0CB3092D4D7277407B28F038_afap_abs&ref_=aa_maas&tag=maas&me=AEFRCMPTGXRXD&marketplaceID=ATVPDKIKX0DER

#ShortDrama #LifeChoices #Prycken'''
EXCLUDED=['fb16','fb17','fb18','fb21']
EVERYDAY_CAPTION='''Everyday moments can offer a new perspective.
What stood out to you in this video?

Discover more perspectives through a good book.

Get your own copy on Amazon:
https://www.amazon.com/s?maas=maas_adg_B87EF70D0CB3092D4D7277407B28F038_afap_abs&ref_=aa_maas&tag=maas&me=AEFRCMPTGXRXD&marketplaceID=ATVPDKIKX0DER

#EverydayMoments #NewPerspectives #Prycken'''
EVERYDAY_COMMENT='''Get your own copy:
https://www.amazon.com/s?maas=maas_adg_B87EF70D0CB3092D4D7277407B28F038_afap_abs&ref_=aa_maas&tag=maas&me=AEFRCMPTGXRXD&marketplaceID=ATVPDKIKX0DER
Shop on Shopfy https://prycken.com/'''


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def content_policy(for_date,revision=None):
    requested=date.fromisoformat(for_date)
    value=upload.read_json(upload.ROOT/'publication_preferences.json',{})
    if not isinstance(value,dict):raise ValueError('后续发布规则格式异常')
    updates=value.get('content_updates',[])
    if not isinstance(updates,list):raise ValueError('正文评论版本记录格式异常')
    selected=None;seen=set()
    for item in updates:
        if not isinstance(item,dict):raise ValueError('正文评论版本格式异常')
        payload=item.get('payload',{});checksum=item.get('sha256')
        if (not isinstance(payload,dict) or checksum!=digest(payload) or checksum in seen
                or payload.get('schema')!='publication-content-v1'
                or any(not isinstance(payload.get(key),str) or not payload[key].strip() or len(payload[key])>5000 for key in ('caption','comment'))):
            raise ValueError('正文评论版本校验失败')
        seen.add(checksum)
        effective=date.fromisoformat(payload['effective_from'])
        if effective<date(2026,11,6):raise ValueError('正文评论版本起始日期异常')
        if effective<=requested and (revision is None or revision==checksum):selected=item
    if revision is not None and selected is None:raise ValueError('冻结批次的正文评论版本缺失或未生效')
    return selected


def save_content_authorized():
    """Caller holds the original worker locks; update defaults, never frozen jobs."""
    path=upload.ROOT/'publication_preferences.json';common=upload.ROOT/'common_caption_today.txt'
    if not path.is_file():raise ValueError('缺少原发布规则，未另建账号范围或覆盖旧配置')
    load('2026-11-11');content_policy('9999-12-31')
    value=upload.read_json(path,{})
    payload=dict(schema='publication-content-v1',effective_from='2026-11-11',caption=EVERYDAY_CAPTION,comment=EVERYDAY_COMMENT)
    item=dict(payload=payload,sha256=digest(payload))
    updates=value.setdefault('content_updates',[])
    if item not in updates:updates.append(item)
    elif updates[-1]!=item:raise ValueError('已有更晚的文案设置，未用旧指令覆盖')
    if upload.read_json(path,{})==value and common.is_file() and common.read_text(encoding='utf-8-sig').strip()==EVERYDAY_CAPTION:return item
    backup=upload.ROOT/'backups'/('publication-content-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
    originals={file:file.read_bytes() if file.is_file() else None for file in (path,common)}
    for file,data in originals.items():
        if data is not None:(backup/file.name).write_bytes(data)
    try:atomic_caption(common,EVERYDAY_CAPTION);upload.save_json(path,value)
    except BaseException:
        for file,data in originals.items():
            if data is None:file.unlink(missing_ok=True)
            else:shutil.copy2(backup/file.name,file)
        raise
    print('之后新批次的实拍正文和双链接评论已保存；原设置备份：',backup,flush=True)
    return item


def load(for_date):
    path=upload.ROOT/'publication_preferences.json';value=upload.read_json(path,None)
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('后续发布规则格式异常')
    payload=value.get('payload',{})
    if not isinstance(payload,dict):raise ValueError('后续发布规则内容格式异常')
    if (value.get('sha256')!=digest(payload) or payload.get('schema')!=SCHEMA
            or payload.get('caption_policy')!='exact-unified-new-videos' or not isinstance(payload.get('caption'),str)
            or not payload['caption'].strip() or len(payload['caption'])>5000
            or not isinstance(payload.get('excluded_accounts'),list)
            or any(not re.fullmatch(r'fb\d{2,}',str(a)) for a in payload['excluded_accounts'])):raise ValueError('后续发布规则校验失败，未使用其他文案或账号范围')
    effective=date.fromisoformat(payload['effective_from']);requested=date.fromisoformat(for_date)
    resumption=value.get('account_resumption')
    resumed=None
    if resumption is not None:
        if not isinstance(resumption,dict):raise ValueError('账号恢复日期规则格式异常')
        resumed=resumption.get('payload',{})
        if (not isinstance(resumed,dict) or resumption.get('sha256')!=digest(resumed)
                or resumed.get('schema')!='account-resumption-v1' or not isinstance(resumed.get('accounts'),list)
                or not resumed['accounts'] or len(set(resumed['accounts']))!=len(resumed['accounts'])
                or not set(resumed['accounts']).issubset(set(payload['excluded_accounts']))):raise ValueError('账号恢复日期规则校验失败')
        if date.fromisoformat(resumed['effective_from'])<effective:raise ValueError('账号恢复日期早于规则起始日期')
    if requested<effective:return None
    if resumed is None or requested<date.fromisoformat(resumed['effective_from']):return value
    # Keep the base fingerprint valid for historical dates; project only the active future rule.
    active=dict(payload,excluded_accounts=[a for a in payload['excluded_accounts'] if a not in resumed['accounts']],
                included_accounts=list(resumed['accounts']),account_resumption_sha256=resumption['sha256'])
    return dict(payload=active,sha256=digest(active))


def save_authorized(resume_from=None):
    """Caller holds original upload locks. No source video or caption sidecar edited here."""
    payload=dict(schema=SCHEMA,effective_from='2026-11-06',caption_policy='exact-unified-new-videos',caption=CAPTION,excluded_accounts=EXCLUDED)
    desired=dict(payload=payload,sha256=digest(payload));path=upload.ROOT/'publication_preferences.json';common=upload.ROOT/'common_caption_today.txt'
    existing=upload.read_json(path,None)
    if isinstance(existing,dict) and existing.get('account_resumption') is not None:
        load('2026-11-06')  # Validate before preserving a later explicit authorization.
        desired['account_resumption']=existing['account_resumption']
    if resume_from is not None:
        if date.fromisoformat(resume_from)<date.fromisoformat(payload['effective_from']):raise ValueError('恢复日期无效')
        resumed=dict(schema='account-resumption-v1',effective_from=resume_from,accounts=list(EXCLUDED))
        desired['account_resumption']=dict(payload=resumed,sha256=digest(resumed))
    if isinstance(existing,dict) and 'content_updates' in existing:
        content_policy('9999-12-31');desired['content_updates']=existing['content_updates']
    content=content_policy(datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat())
    caption=content['payload']['caption'] if content else CAPTION
    if existing==desired and common.is_file() and common.read_text(encoding='utf-8-sig').strip()==caption:return desired
    backup=upload.ROOT/'backups'/('publication-preferences-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
    for file in (path,common):
        if file.is_file():shutil.copy2(file,backup/file.name)
    atomic_caption(common,caption);upload.save_json(path,desired)
    return desired
