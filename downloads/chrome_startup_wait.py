"""Wait for the actual loopback endpoint, including Windows Chrome relaunches."""
import subprocess,time,uuid
from datetime import datetime

VERSION='1.0-wait-for-endpoint-after-launcher-exit'

def spawn(args,root,account):
    folder=root/'logs';folder.mkdir(exist_ok=True)
    path=folder/('chrome-startup-'+account+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.txt')
    with path.open('wb') as handle:
        process=subprocess.Popen([*args[:-1],'--enable-logging=stderr',args[-1]],stdout=subprocess.DEVNULL,stderr=handle)
    process._fb_startup_log=path
    return process

def wait_endpoint(process,path,validate,timeout=30):
    end=time.monotonic()+timeout
    while True:
        if path.is_file():
            try:return validate(path)
            except (OSError,ValueError):pass
        if time.monotonic()>=end:
            code=process.poll()
            detail='启动进程退出码 '+str(code) if code is not None else '启动进程仍在运行'
            raise RuntimeError('Chrome在30秒内未建立本机控制连接，尚未选择或上传视频；'+detail+'；启动诊断：'+str(getattr(process,'_fb_startup_log','未生成')))
        # Windows Chrome may hand off/relaunch and exit its initial process.
        # A launcher exit alone is not proof that the browser failed.
        time.sleep(.2)
