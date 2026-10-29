import ctypes
import re
import sys
import time
from datetime import datetime,timezone
from pathlib import Path


def select_manifest(root,batch):
    matches=[]
    for path in (root/'logs').glob('frozen-material-2026-10-29-*.json'):
        if not re.fullmatch(r'frozen-material-2026-10-29-[a-f0-9]{16}\.json',path.name):continue
        value=batch.upload.read_json(path,{})
        payload=value.get('payload',{})
        checksum=batch.digest(payload)
        if (payload.get('schema')==batch.SCHEMA and value.get('sha256')==checksum
            and path.stem.endswith(checksum[:16]) and payload.get('date')=='2026-10-29'
            and payload.get('start')=='2026-10-29T17:00:00+08:00'
            and payload.get('include_fb10_pages') is True and payload.get('ai_label') is False
            and set(payload.get('excluded_accounts',[]))=={'fb16','fb18','fb21'}
            and len(payload.get('jobs',[]))==30):matches.append((path,value))
    if len(matches)!=1:raise RuntimeError('没有找到唯一有效的 30 条冻结清单，未选择其他计划。请保留输出。')
    return matches[0]


def main():
    root=Path(sys.argv[1]);sys.path.insert(0,str(root))
    import scheduled_material_batch as batch
    path,manifest=select_manifest(root,batch)
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!='2026-10-29':
        raise RuntimeError('已不是本批授权日期，不补跑过期计划。')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    kernel.CloseHandle.restype=ctypes.c_int
    kernel.SetThreadExecutionState.argtypes=[ctypes.c_uint]
    kernel.SetThreadExecutionState.restype=ctypes.c_uint
    ctypes.set_last_error(0)
    handle=kernel.CreateMutexW(None,False,'Local\\FBUploadWait-'+manifest['sha256'][:16])
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error()==183:
        kernel.CloseHandle(handle)
        raise RuntimeError('这一批的等待或执行窗口已打开，不重复启动。')
    previous=kernel.SetThreadExecutionState(0x80000001)
    try:
        start=datetime.fromisoformat(manifest['payload']['start'])
        print('已启用窗口定时：30 条原视频；北京时间 2026-10-29 17:00:00 开始。',flush=True)
        print('请保持本窗口打开。临时防休眠已请求；没有修改冻结清单，也没有提前发布。',flush=True)
        next_log=0
        while True:
            remaining=(start-datetime.now(timezone.utc)).total_seconds()
            if remaining<=0:break
            if time.monotonic()>=next_log:
                print('等待北京时间 17:00；剩余约',int(remaining+59)//60,'分钟。',flush=True)
                next_log=time.monotonic()+60
            time.sleep(min(30,remaining))
        print('已到开始时间，执行原冻结批次并尝试评论。',flush=True)
        return batch.run(path,manifest.get('output_dir'))
    finally:
        kernel.SetThreadExecutionState(previous or 0x80000000)
        kernel.CloseHandle(handle)


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:
        print('已停止；保留发布记录，请核实实际结果，勿直接重复发布。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',error,flush=True)
        raise SystemExit(1)
