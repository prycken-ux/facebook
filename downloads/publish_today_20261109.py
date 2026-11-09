"""Nov-9 real footage, direct foreground publication using the installed workflow."""
import hashlib,sys
from datetime import datetime,timezone
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import publication_preferences as preferences
import scheduled_material_batch as batch
import publish_priority_batch as priority
import scheduled_priority_workflow as workflow
from add_fb_accounts import locked
from confirm_all_nov05_20261106 import recover_locks

DATE='2026-11-09'
CAPTION_SHA256='1851bd1c8114a948407c4f2f7a0c17edd9d865736a496a15c21dd4f605f9f861'


def authorized(real_footage):
    if not real_footage:raise ValueError('今天全批尚未确认实拍，不启动')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('这条指令只发布北京时间11月9日的新批次')
    workflow.require_versions()
    if (preferences.VERSION!='1.0-exact-caption-excluded-accounts'
            or preferences.EXCLUDED!=['fb16','fb17','fb18','fb21']
            or hashlib.sha256(preferences.CAPTION.encode()).hexdigest()!=CAPTION_SHA256):raise ValueError('统一正文或跳过账号规则与本次授权不一致')


def execute(real_footage):
    authorized(real_footage)
    with locked():preferences.save_authorized()
    path,value=priority.prepare(DATE)
    with locked():
        if upload.read_json(path,{})!=value:raise ValueError('今天清单在启动期间变化，未运行')
        modes={'scheduled_priority_runner':workflow.VERSION,'browser_launch_mode':workflow.normal.NORMAL_CHROME_VERSION,
               'local_file_input_mode':workflow.local.VERSION}
        if any(value.get(key) not in {None,expected} for key,expected in modes.items()):raise ValueError('今天原批次的浏览器或运行流程不一致，未另建批次')
        value.update(modes);workflow.validate(path,value);upload.save_json(path,value)
    print('直接运行11月9日新批次：',len(value['payload']['jobs']),'条；AI标签关闭。',flush=True)
    print('本次及后续跳过fb16/fb17/fb18/fb21；正文使用已确认的短剧通用文案和原亚马逊链接。',flush=True)
    print('原清单开始时间：',value['payload']['start'],'；首次准备会给文件留出稳定时间。',flush=True)
    print('先全部发布，再对可恢复的发布前失败补发一次，最后评论并刷新核验。请保持窗口打开。',flush=True)
    return workflow.run(path)


def start(root,real_footage):
    root=Path(root).resolve()
    if sys.platform!='win32' or upload.ROOT.resolve()!=root:raise ValueError('请在原Windows上传电脑运行')
    authorized(real_footage)
    recover_locks(root)
    logs=root/'logs';logs.mkdir(parents=True,exist_ok=True)
    with (logs/('direct-priority-'+DATE+'.log')).open('a',encoding='utf-8') as log:
        import contextlib
        with contextlib.redirect_stdout(batch.Tee(sys.stdout,log)),contextlib.redirect_stderr(batch.Tee(sys.stderr,log)):
            return execute(real_footage)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(start(Path(sys.argv[1]),'--real-footage' in sys.argv[2:]))
    except KeyboardInterrupt:print('已停止；已有发布、补发和评论记录保留，重跑继续今天原批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
