"""Atomic UTF-8 local run-state files; never publication or browser state."""
import json,os,tempfile,time
from pathlib import Path

def save(path,value):
    path=Path(path)
    if path.is_symlink():raise ValueError('记录文件是链接，未覆盖。')
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:
        temp=Path(handle.name);handle.write(json.dumps(value,ensure_ascii=False).encode('utf-8'));handle.flush();os.fsync(handle.fileno())
    try:
        for attempt in range(80):
            try:temp.replace(path);break
            except PermissionError:
                if attempt==79:raise
                time.sleep(.025)
    finally:temp.unlink(missing_ok=True)
