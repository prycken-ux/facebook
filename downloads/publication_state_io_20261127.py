"""Bounded state-file IO with Windows read/write/delete sharing, no state reset."""
import ctypes,json,os,sys,time
from pathlib import Path
VERSION='1.0-shared-state-read-with-bounded-retry'
TRANSIENT={5,32,33}

def shared_bytes(path,max_bytes):
    if sys.platform!='win32':
        with Path(path).open('rb') as h:return h.read(max_bytes+1)
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];k.CreateFileW.restype=wintypes.HANDLE
    k.ReadFile.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p];k.ReadFile.restype=wintypes.BOOL
    k.CloseHandle.argtypes=[wintypes.HANDLE];k.CloseHandle.restype=wintypes.BOOL
    handle=k.CreateFileW(str(path),0x80000000,7,None,3,0x80,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        parts=[];size=0
        while size<=max_bytes:
            requested=min(65536,max_bytes+1-size);buf=ctypes.create_string_buffer(requested);count=wintypes.DWORD()
            if not k.ReadFile(handle,buf,requested,ctypes.byref(count),None):raise ctypes.WinError(ctypes.get_last_error())
            if not count.value:break
            parts.append(buf.raw[:count.value]);size+=count.value
        return b''.join(parts)
    finally:k.CloseHandle(handle)

def retryable(error):return isinstance(error,PermissionError) or getattr(error,'winerror',None) in TRANSIENT

def read(path,default=None,required=False,timeout=2.0,max_bytes=4_000_000,reader=None):
    path=Path(path);deadline=time.monotonic()+timeout;attempt=0
    reader=shared_bytes if reader is None else reader
    while True:
        try:
            blob=reader(path,max_bytes)
            if len(blob)>max_bytes:raise ValueError('状态文件超过预期范围：'+path.name)
            return json.loads(blob.decode('utf-8-sig'))
        except FileNotFoundError:
            if required:raise
            return default
        except OSError as error:
            if not retryable(error) or time.monotonic()>=deadline:raise
            delay=min(.01*2**min(attempt,5),.20,max(0,deadline-time.monotonic()));attempt+=1;time.sleep(delay)
