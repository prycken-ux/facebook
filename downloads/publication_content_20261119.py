"""Exact user-authorized Nov19 caption and comment; preserve all old revisions."""
import copy
import shutil
import uuid
from pathlib import Path
import publication_preferences as preferences

DAY = '2026-11-19'
VERSION = '1.0-nov19-exact-book-caption-comment'
CAPTION = 'If this book speaks to you, you can find the same one from the video here.Get your copy here:https://www.amazon.com/gp/product/B0GYJ55PH6?maas=maas_adg_2C08551FB464224E2CDB58F74A72570A_afap_abs&ref_=aa_maas&tag=maas Shop on shopify: https://prycken.com/'
COMMENT = 'Get your own copy here:https://www.amazon.com/gp/product/B0GYJ55PH6?maas=maas_adg_B2F4D52E550EDAC7E6A92C0290F501F6_afap_abs&ref_=aa_maas&tag=maas'
PAYLOAD = dict(schema='publication-content-v1',effective_from=DAY,caption=CAPTION,comment=COMMENT)
CONTENT = dict(payload=PAYLOAD,sha256=preferences.digest(PAYLOAD))


def verify(root, revision=None):
    if preferences.upload.ROOT.resolve()!=Path(root).resolve():
        raise ValueError('正文评论目录不符。')
    if revision is not None and revision!=CONTENT['sha256']:
        raise ValueError('今日正文评论授权版本不符，未更改原冻结任务。')
    saved=preferences.content_policy(DAY,CONTENT['sha256'])
    if saved!=CONTENT:
        raise ValueError('缺少用户指定的11月19日正文评论，未替换成旧文案。')
    return saved


def save_authorized(root):
    root=Path(root).resolve()
    if preferences.upload.ROOT.resolve()!=root:
        raise ValueError('正文评论目录不符。')
    path=root/'publication_preferences.json';common=root/'common_caption_today.txt'
    if preferences.load(DAY) is None:
        raise ValueError('缺少原发布规则，未重建账号授权。')
    preferences.content_policy('9999-12-31')
    value=preferences.upload.read_json(path,{})
    updates=value.setdefault('content_updates',[])
    if any(item['payload']['effective_from']>DAY for item in updates):
        raise ValueError('已有更晚文案规则，未用旧日期覆盖。')
    if CONTENT not in updates:
        updates.append(copy.deepcopy(CONTENT))
    elif updates[-1]!=CONTENT:
        raise ValueError('同日已有后续文案版本，未回退覆盖。')
    if (preferences.upload.read_json(path,{})==value and common.is_file()
            and common.read_text(encoding='utf-8-sig').strip()==CAPTION):
        return verify(root)
    backup=root/'backups'/('publication-content-nov19-'+uuid.uuid4().hex[:12]);backup.mkdir(parents=True)
    originals={p:p.read_bytes() if p.is_file() else None for p in (path,common)}
    for p,data in originals.items():
        if data is not None:(backup/p.name).write_bytes(data)
    try:
        preferences.atomic_caption(common,CAPTION)
        preferences.upload.save_json(path,value)
        verify(root)
    except BaseException:
        for p,data in originals.items():
            if data is None:p.unlink(missing_ok=True)
            else:shutil.copy2(backup/p.name,p)
        raise
    print('今日新正文与单链接评论已保存并核验；旧版本保留。备份：',backup,flush=True)
    return copy.deepcopy(CONTENT)
