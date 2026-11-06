"""User-authorized persistent caption and excluded accounts, effective Nov 6."""
import hashlib,json,re,shutil,uuid
from datetime import date
import fb_upload as upload
from apply_common_caption import atomic_caption

VERSION='1.0-exact-caption-excluded-accounts'
SCHEMA='publication-preferences-v1'
CAPTION='''A small decision can change the way a story unfolds.
What would you have done in this situation?

New perspectives through a good book.

Get your own copy on Amazon:
https://www.amazon.com/s?maas=maas_adg_B87EF70D0CB3092D4D7277407B28F038_afap_abs&ref_=aa_maas&tag=maas&me=AEFRCMPTGXRXD&marketplaceID=ATVPDKIKX0DER

#ShortDrama #LifeChoices #Prycken'''
EXCLUDED=['fb16','fb17','fb18','fb21']


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


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
    return value if requested>=effective else None


def save_authorized():
    """Caller holds original upload locks. No source video or caption sidecar edited here."""
    payload=dict(schema=SCHEMA,effective_from='2026-11-06',caption_policy='exact-unified-new-videos',caption=CAPTION,excluded_accounts=EXCLUDED)
    desired=dict(payload=payload,sha256=digest(payload));path=upload.ROOT/'publication_preferences.json';common=upload.ROOT/'common_caption_today.txt'
    if upload.read_json(path,None)==desired and common.is_file() and common.read_text(encoding='utf-8-sig').strip()==CAPTION:return desired
    backup=upload.ROOT/'backups'/('publication-preferences-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
    for file in (path,common):
        if file.is_file():shutil.copy2(file,backup/file.name)
    atomic_caption(common,CAPTION);upload.save_json(path,desired)
    return desired
