"""Nov-11 foreground batch, restored accounts, exact fb24 and ten fb09 Pages."""
import hashlib
import sys
from datetime import datetime,timezone
from pathlib import Path

if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import publication_preferences as preferences
import scheduled_material_batch as batch
import publish_priority_batch as priority
import scheduled_priority_workflow as workflow
import automatic_comment_retry as comment_retry
import connect_fb09_ten_pages_20261111 as fb09
from add_fb_accounts import locked
from confirm_all_nov05_20261106 import recover_locks

DATE='2026-11-11'
ALLOWED={f'fb{n:02d}' for n in range(1,25)}
RESTORED={'fb16','fb17','fb18','fb21'}
CONTENT_VERSION='1.0-frozen-caption-and-comment'
COMMENT_RETRY_VERSION='1.0-scoped-retry-readonly-reconcile'
CAPTION_SHA256='8d8da3c2d7d6d413afd4636fcaa64a07448a3cd57acd878052ad373d529cd491'
COMMENT_SHA256='7ac834103ddb1f1cd18ba8a7b5752a5f210875a3b0c16fc9e3985f1e602273b5'


def authorized(real_footage):
    if not real_footage:raise ValueError('今天全批尚未确认实拍，不启动')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('此指令只发布北京时间11月11日的新批次')
    workflow.require_versions()
    if (getattr(batch,'ACCOUNT_RESUMPTION_VERSION','')!='1.0-effective-dated-resumption'
            or preferences.CONTENT_UPDATES_VERSION!=CONTENT_VERSION or batch.CONTENT_UPDATES_VERSION!=CONTENT_VERSION
            or priority.COMMENT_RECOVERY_VERSION!=COMMENT_RETRY_VERSION or comment_retry.VERSION!=COMMENT_RETRY_VERSION
            or batch.COMMENT_RETRY_POLICY!=COMMENT_RETRY_VERSION or priority.comments.COMMENT_RECOVERY_VERSION!=COMMENT_RETRY_VERSION
            or priority.daily.COMMENT_RECOVERY_VERSION!=COMMENT_RETRY_VERSION):raise ValueError('发布与补评配套程序版本不一致')
    if (hashlib.sha256(preferences.EVERYDAY_CAPTION.encode()).hexdigest()!=CAPTION_SHA256
            or hashlib.sha256(preferences.EVERYDAY_COMMENT.encode()).hexdigest()!=COMMENT_SHA256):raise ValueError('正文或评论与已确认的原文不一致')


def check_targets():
    config=upload.read_json(upload.CONFIG,{})
    _,missing=fb09.plan(config)
    if missing:raise ValueError('fb09这些公共主页尚未登记，未猜选：'+','.join(missing))
    for account in sorted(RESTORED|{'fb24'}):
        entries=[e for e in config['targets'] if (e.get('account'),e.get('target'))==(account,'personal')]
        if len(entries)!=1:raise ValueError(account+'缺少唯一的原个人主页配置')
        row=entries[0];upload.validate_entry(row)
        if row.get('type')!='personal' or not (upload.ROOT/'profiles'/account).is_dir():raise ValueError(account+'原个人号资料缺失，未创建空白资料代替')
        if not batch.eligible(row,True,date=DATE):raise ValueError(account+'尚未完成本人核验和发布接入，未跳过核验强行发布')
    registry=upload.read_json(upload.ROOT/'additional_personal_accounts.json',{})
    batch_id='personal-20261110-one-fb24';slot=registry.get('slots',{}).get('fb24',{});reservation=registry.get('batches',{}).get(batch_id,{})
    if slot.get('batch_id')!=batch_id or reservation.get('accounts')!=['fb24'] or reservation.get('count')!=1:
        raise ValueError('fb24不是这次新接入并核验的个人号，未恢复以前删除的账号')
    if not (upload.ROOT/'profiles/fb09').is_dir():raise ValueError('fb09原登录资料缺失')


def execute(real_footage):
    authorized(real_footage)
    with locked():
        preferences.save_authorized(resume_from=DATE);content=preferences.save_content_authorized()
        if batch.excluded_accounts(DATE):raise ValueError('今天仍有旧的账号跳过规则，未静默漏发')
        check_targets()
    original=batch.eligible
    def eligible(entry,include_pages,date=None):
        return entry.get('account') in ALLOWED and original(entry,include_pages,date=date)
    batch.eligible=eligible
    try:path,value=priority.prepare(DATE)
    finally:batch.eligible=original
    with locked():
        if upload.read_json(path,{})!=value:raise ValueError('今天原清单在启动期间变化，未运行')
        payload=value['payload']
        if (payload.get('publication_content_sha256')!=content['sha256'] or payload.get('comment_retry_policy')!=COMMENT_RETRY_VERSION
                or any(j['account'] not in ALLOWED for j in payload['jobs'])):
            raise ValueError('今天已有其他文案或账号范围的原批次，保留原清单，未另建批次或重复发布')
        modes=dict(scheduled_priority_runner=workflow.VERSION,browser_launch_mode=workflow.normal.NORMAL_CHROME_VERSION,local_file_input_mode=workflow.local.VERSION)
        if any(value.get(key) not in {None,expected} for key,expected in modes.items()):raise ValueError('今天原批次的浏览器或流程不一致')
        value.update(modes);workflow.validate(path,value);upload.save_json(path,value)
    print('直接运行11月11日新批次：',len(payload['jobs']),'条；全部实拍，AI标签关闭。',flush=True)
    print('fb16/fb17/fb18/fb21恢复正常发布；包含新fb24和fb09/page01–page10。',flush=True)
    print('正文：Everyday moments…；评论使用原亚马逊链接及Shop on Shopfy https://prycken.com/。',flush=True)
    for account in sorted(RESTORED|{'fb24','fb09'}):
        jobs=[j for j in payload['jobs'] if j['account']==account]
        print('今天清单：',account,len(jobs),'条；目标：',','.join(sorted({j['target'] for j in jobs})) or '无未记录的新素材',flush=True)
    print('先发布，再安全补发一次视频，再评论，最后补评一次。已提交待核实的不重复发送。请保持窗口打开。',flush=True)
    return workflow.run(path)


def start(root,real_footage):
    root=Path(root).resolve()
    if sys.platform!='win32' or upload.ROOT.resolve()!=root:raise ValueError('请在原Windows上传电脑运行')
    authorized(real_footage);recover_locks(root)
    logs=root/'logs';logs.mkdir(parents=True,exist_ok=True)
    with (logs/('direct-priority-'+DATE+'.log')).open('a',encoding='utf-8') as log:
        import contextlib
        with contextlib.redirect_stdout(batch.Tee(sys.stdout,log)),contextlib.redirect_stderr(batch.Tee(sys.stderr,log)):
            return execute(real_footage)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1]),'--real-footage' in sys.argv[2:]))
    except KeyboardInterrupt:print('已停止；视频、补发、评论记录保留，重跑同一命令继续今天原批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
