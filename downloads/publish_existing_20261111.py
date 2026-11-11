"""Nov-11 existing configured targets first; defer new or unregistered targets."""
import contextlib
import re
import sys
from collections import Counter
from pathlib import Path

if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import publish_today_20261111 as base

DATE='2026-11-11'
SCOPE='nov11-existing-configured-targets-first-v1'
DEFERRED_NEW={('fb24','personal')}|{('fb09',f'page{n:02d}') for n in range(1,11)}


def inventory(config):
    if not isinstance(config,dict) or not isinstance(config.get('targets'),list) or any(not isinstance(e,dict) for e in config['targets']):
        raise ValueError('原上传配置格式异常，未修改配置')
    entries=config['targets'];pairs=Counter((e.get('account'),e.get('target')) for e in entries)
    deferred={pair:dict(account=pair[0],target=pair[1],reason='按要求暂缓新增目标，先完成原有账号视频') for pair in DEFERRED_NEW}
    ready=set()
    for entry in entries:
        account,target=entry.get('account'),entry.get('target');pair=account,target
        if pair in DEFERRED_NEW or account not in {f'fb{n:02d}' for n in range(1,24)}:continue
        if account=='fb09' and entry.get('type')=='page':
            deferred[pair]=dict(account=account,target=target,reason='新增fb09公共主页暂缓');continue
        try:
            base.upload.validate_entry(entry)
            if pairs[pair]!=1:raise ValueError('发布目标编号重复，未猜选')
            if not (base.upload.ROOT/'profiles'/account).is_dir():raise ValueError('原浏览器资料缺失，未创建空白资料代替')
            if not base.batch.eligible(entry,True,date=DATE):raise ValueError('原发布规则尚未允许该目标')
            ready.add(pair)
            if account in base.RESTORED:
                print('恢复账号沿用原配置：',account+'/'+target,entry['type'],entry['name'],entry['url'],flush=True)
        except Exception as error:
            deferred[pair]=dict(account=account,target=target,reason=(str(error) or type(error).__name__).split('\n',1)[0])
    for account in sorted(base.RESTORED):
        if not any(e.get('account')==account for e in entries):
            deferred[(account,'未登记')]=dict(account=account,target='未登记',reason='已有登录不等于已登记发布目标；此账号留待本批结束后补接入')
    return ready,[deferred[pair] for pair in sorted(deferred)]


def execute(real_footage):
    base.authorized(real_footage)
    with base.locked():
        base.preferences.save_authorized(resume_from=DATE);content=base.preferences.save_content_authorized()
        config=base.upload.read_json(base.upload.CONFIG,{})
        ready,deferred=inventory(config)
        report=base.upload.ROOT/'logs/deferred-targets-2026-11-11.json'
        base.upload.save_json(report,dict(schema=SCOPE,date=DATE,targets=deferred))
        for row in deferred:print('本批暂缓：',row['account']+'/'+row['target'],row['reason'],flush=True)
        if not ready:raise ValueError('当前没有完整登记的原有发布目标，未建立空清单')
        pointer=base.upload.read_json(base.upload.ROOT/'logs'/('priority-batch-'+DATE+'.json'),None)
        if isinstance(pointer,dict) and re.fullmatch('frozen-material-'+DATE+r'-[a-f0-9]{16}\.json',str(pointer.get('manifest',''))):
            prior=base.upload.read_json(base.upload.ROOT/'logs'/pointer['manifest'],{})
            if any((j.get('account'),j.get('target')) not in ready for j in prior.get('payload',{}).get('jobs',[])):
                raise ValueError('今天已有不同范围的冻结清单，保留原记录，未另建批次或重发')
    original=base.batch.eligible
    def eligible(entry,include_pages,date=None):
        return (entry.get('account'),entry.get('target')) in ready and original(entry,include_pages,date=date)
    base.batch.eligible=eligible
    try:path,value=base.priority.prepare(DATE)
    finally:base.batch.eligible=original
    with base.locked():
        if base.upload.read_json(path,{})!=value:raise ValueError('今天清单在启动期间变化，未运行')
        payload=value['payload']
        if (payload.get('publication_content_sha256')!=content['sha256'] or payload.get('comment_retry_policy')!=base.COMMENT_RETRY_VERSION
                or any((j['account'],j['target']) not in ready for j in payload['jobs'])):
            raise ValueError('今天已有不同范围或文案的冻结清单，保留原记录，未另建批次或重发')
        modes=dict(scheduled_priority_runner=base.workflow.VERSION,browser_launch_mode=base.workflow.normal.NORMAL_CHROME_VERSION,local_file_input_mode=base.workflow.local.VERSION)
        if any(value.get(key) not in {None,expected} for key,expected in modes.items()):raise ValueError('今天原批次的浏览器流程不一致')
        value.update(modes);base.workflow.validate(path,value);base.upload.save_json(path,value)
    print('现在先发布11月11日原有已登记目标：',len(payload['jobs']),'条；实拍，AI标签关闭。',flush=True)
    print('保留fb09原个人主页；暂缓新fb24、fb09十个公共主页及缺少登记的账号。',flush=True)
    print('沿用已确认的实拍正文和双链接评论；先发布、再安全补发视频、再评论、最后补评一次。请保持窗口打开。',flush=True)
    result=base.workflow.run(path)
    print('本批原有目标流程已结束；暂缓账号另行接入处理，清单：',report,flush=True)
    for row in deferred:print('待处理：',row['account']+'/'+row['target'],row['reason'],flush=True)
    return result


def start(root,real_footage):
    root=Path(root).resolve()
    if sys.platform!='win32' or base.upload.ROOT.resolve()!=root:raise ValueError('请在原Windows上传电脑运行')
    base.authorized(real_footage);base.recover_locks(root)
    logs=root/'logs';logs.mkdir(parents=True,exist_ok=True)
    with (logs/'direct-existing-priority-2026-11-11.log').open('a',encoding='utf-8') as log:
        with contextlib.redirect_stdout(base.batch.Tee(sys.stdout,log)),contextlib.redirect_stderr(base.batch.Tee(sys.stderr,log)):
            return execute(real_footage)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1]),'--real-footage' in sys.argv[2:]))
    except KeyboardInterrupt:print('已停止；保留发布、补发和评论记录，重跑继续今天原批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
