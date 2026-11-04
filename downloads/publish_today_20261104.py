"""Nov-4 batch: normal Chrome, uploads first, one safe retry, then comments."""
import argparse,sys
from datetime import datetime,timezone
import fb_upload as upload
import scheduled_material_batch as batch
import publish_priority_batch as priority
import normal_chrome_batch as normal
from add_fb_accounts import locked

DATE='2026-11-04'
MODE=normal.NORMAL_CHROME_VERSION


def execute(real_footage):
    if not real_footage:raise ValueError('今天视频需明确确认全部实拍')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!=DATE:raise ValueError('只运行北京时间11月4日今天的新批次')
    original_prepare=priority.prepare;original_launch=upload.launch_context
    def prepare(date):
        path,value=original_prepare(date)
        with locked():
            current=upload.read_json(path,{})
            if current!=value:raise ValueError('今天清单在启动期间变化，未运行')
            mode=value.get('browser_launch_mode')
            if mode not in {None,MODE}:raise ValueError('今天清单浏览器策略不匹配')
            if mode is None:
                value['browser_launch_mode']=MODE;upload.save_json(path,value)
        upload.launch_context=normal.launcher_for_jobs(value['payload']['jobs'])
        return path,value
    priority.prepare=prepare
    print('11月4日新批次使用普通Chrome原登录资料、扩展和代理；按上传→一次补发→评论执行。',flush=True)
    try:return priority.execute(DATE,real_footage)
    finally:priority.prepare=original_prepare;upload.launch_context=original_launch


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='11月4日：先发布、再安全补发一次、最后通过确切视频链接评论')
    parser.add_argument('--real-footage',action='store_true');args=parser.parse_args()
    try:raise SystemExit(execute(args.real_footage))
    except KeyboardInterrupt:print('已停止；发布、补发和评论记录保留，重跑继续今天原批次。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
