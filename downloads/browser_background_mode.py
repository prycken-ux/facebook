"""Persistent opt-in to Chrome's supported windowless mode; no UI fallback."""
import json
from pathlib import Path

VERSION='1.0-windowless-normal-chrome'
SETTINGS='browser_run_settings.json'
SCHEMA='facebook-browser-run-mode-v1'


def mode(root):
    path=Path(root)/SETTINGS
    if path.is_symlink():raise ValueError('浏览器运行设置是链接，未启动浏览器。')
    if not path.exists():return 'foreground'
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if (not isinstance(value,dict) or value.get('schema')!=SCHEMA
            or value.get('mode') not in {'foreground','background'}):
        raise ValueError('浏览器后台运行设置异常，未自动退回前台。')
    return value['mode']


def arguments(selected):
    if selected=='foreground':return ['--new-window']
    if selected=='background':return ['--headless=new','--window-size=1440,1000']
    raise ValueError('未知浏览器运行模式。')
