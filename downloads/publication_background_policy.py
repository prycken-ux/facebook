"""Windowless automatic work; visible Chrome is limited to manual verification."""
import contextlib,shutil
from contextvars import ContextVar
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import fb_upload as upload
import normal_chrome_batch as normal

VERSION='1.0-headless-auto-manual-verification-only'
_MANUAL=ContextVar('fb_explicit_manual_verification',default=False)


@contextlib.contextmanager
def manual_verification():
    token=_MANUAL.set(True)
    try:yield
    finally:_MANUAL.reset(token)


def save_background(root):
    path=Path(root)/normal.background.SETTINGS
    if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):raise ValueError('后台运行设置是链接，未修改。')
    previous=upload.read_json(path,None)
    if previous is not None:normal.background.mode(root)
    value=dict(previous or {},schema=normal.background.SCHEMA,mode='background')
    if value==previous:return
    if path.exists():
        backup=Path(root)/'backups'/('background-only-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True);shutil.copy2(path,backup/path.name)
    upload.save_json(path,value)


def retire_foreground_modes(controller):
    modes=controller.get('modes',{})
    if not isinstance(modes,dict):raise ValueError('原浏览器模式记录异常，未重置发布进度。')
    retired={account:mode for account,mode in modes.items() if mode!='background'}
    if retired:
        history=controller.setdefault('retired_foreground_mode_history',[])
        if not isinstance(history,list):raise ValueError('原模式变更记录异常。')
        history.append(dict(retired_at=datetime.now(timezone.utc).isoformat(),reason='user-request-auto-headless-manual-verification-only',modes=retired))
        controller['modes']={account:'background' for account in modes}
    controller['automatic_browser_mode']='background'


@contextlib.contextmanager
def installed():
    original=normal.launch_normal
    def launch(pw,entry):
        visible=_MANUAL.get() and entry.get('_local_file_selfcheck') is True
        selected='foreground' if visible else 'background'
        if visible:print('需要本人验证，打开此账号检查窗口：',entry['account'],entry['target'],flush=True)
        # Apply at the real launch boundary: stale per-account preferences or a
        # nested legacy "foreground_minimized" helper cannot force auto UI.
        with patch.object(normal.background,'mode',return_value=selected):return original(pw,entry)
    with patch.object(normal,'launch_normal',side_effect=launch):yield
