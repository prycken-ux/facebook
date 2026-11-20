"""Recognized-source patch: preserve primary errors and tolerate launcher handoff."""
import ast
from patch_owned_chrome_cleanup_20261120 import transform as cleanup_transform

VERSION='1.0-windows-chrome-startup-wait-and-diagnostics'
MARKER="STARTUP_WAIT_VERSION='1.0-wait-for-endpoint-after-launcher-exit'"

def transform(source):
    ast.parse(source)
    if MARKER in source:return source
    source=cleanup_transform(source)
    previous="    process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
    replacement="    from chrome_startup_wait import spawn,wait_endpoint\n    process=spawn(args,upload.ROOT,account)"
    if source.count(previous)!=1:raise ValueError('Chrome启动位置不同，保留原程序。')
    source=source.replace(previous,replacement)
    previous='''        end=time.monotonic()+30
        while not port_file.is_file():
            if process.poll() is not None:raise RuntimeError('普通Chrome在建立本机连接前退出，尚未上传')
            if time.monotonic()>=end:raise RuntimeError('普通Chrome本机连接尚未就绪，尚未上传')
            time.sleep(.2)
        try:address=endpoint(port_file)
        except (OSError,ValueError):
            time.sleep(.3);address=endpoint(port_file)'''
    if source.count(previous)!=1:raise ValueError('Chrome等待结构不同，保留原程序。')
    source=source.replace(previous,'        address=wait_endpoint(process,port_file,endpoint)')+'\n'+MARKER+'\n'
    ast.parse(source)
    return source
