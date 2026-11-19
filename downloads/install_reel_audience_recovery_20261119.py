"""Install a narrow audience-prompt fix; never start publication or old retries."""
import ast
import importlib.util
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import material_distribution_worker_check as workers

VERSION = '1.0-install-audience-prompt-only-no-publication'
BOOTSTRAP = re.compile(workers.BOOTSTRAP.pattern.replace(
    'start_distribute_first24_materials_20261116', 'start_install_reel_audience_recovery_nov19').replace(
    'verified-first24-material-distribution', 'verified-reel-audience-recovery-install'))
BASE_FUNCTION = 'def ensure_personal_public_audience(page):\n    from playwright.sync_api import expect\n\n    settings = page.get_by_role("dialog", name="Reel settings", exact=True)\n    expect(settings).to_be_visible(timeout=240000)\n    expect(settings.get_by_role("textbox", name="Describe your reel...", exact=True)).to_be_visible(timeout=240000)\n    # Audience controls may be outside the upload form and render later than\n    # the caption field. Wait in the settings dialog, not in the file form.\n    choice = settings.get_by_role("button", name=re.compile(r"^(Public|Friends)\\b"))\n    try:\n        expect(choice).to_be_visible(timeout=60000)\n    except Exception:\n        raise RuntimeError("Reel settings 中未找到已加载的 Public/Friends 可见范围选项；未填写文案或点击发布。") from None\n    public = settings.get_by_role("button", name=re.compile(r"^Public\\b"))\n    if public.count() == 1 and public.is_visible():\n        return\n    friends = settings.get_by_role("button", name=re.compile(r"^Friends\\b"))\n    expect(friends).to_be_visible(timeout=30000)\n    friends.click()\n    option = page.get_by_role("radio", name=re.compile(r"^Public Anyone on or off"))\n    expect(option).to_be_visible(timeout=30000)\n    option.check()\n    expect(option).to_be_checked()\n    page.get_by_role("button", name="Done", exact=True).click()\n    expect(public).to_be_visible(timeout=30000)\n    print("已将本条 Reel 的可见范围切换为 Public。", flush=True)'
PATCHED_FUNCTION = 'def ensure_personal_public_audience(page):\n    from playwright.sync_api import expect\n    from reel_audience_dialog_recovery import wait_for_public_controls, AudienceRecoveryBlocked\n\n    settings = page.get_by_role("dialog", name="Reel settings", exact=True, include_hidden=True)\n    expect(settings).to_be_visible(timeout=240000)\n    expect(settings.get_by_role("textbox", name="Describe your reel...", exact=True, include_hidden=True)).to_be_visible(timeout=240000)\n    # Audience controls may be outside the upload form and render later than\n    # the caption field. Wait in the settings dialog, not in the file form.\n    choice = settings.get_by_role("button", name=re.compile(r"^(Public|Friends)\\b"))\n    try:\n        wait_for_public_controls(page, settings, choice)\n    except AudienceRecoveryBlocked:\n        raise\n    except Exception:\n        raise RuntimeError("Reel settings 中未找到已加载的 Public/Friends 可见范围选项；未填写文案或点击发布。") from None\n    public = settings.get_by_role("button", name=re.compile(r"^Public\\b"))\n    if public.count() == 1 and public.is_visible():\n        return\n    friends = settings.get_by_role("button", name=re.compile(r"^Friends\\b"))\n    expect(friends).to_be_visible(timeout=30000)\n    friends.click()\n    option = page.get_by_role("radio", name=re.compile(r"^Public Anyone on or off"))\n    expect(option).to_be_visible(timeout=30000)\n    option.check()\n    expect(option).to_be_checked()\n    page.get_by_role("button", name="Done", exact=True).click()\n    expect(public).to_be_visible(timeout=30000)\n    print("已将本条 Reel 的可见范围切换为 Public。", flush=True)'


def build_core(data):
    text = data.decode('utf-8-sig')
    nodes = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)
             and n.name == 'ensure_personal_public_audience']
    if len(nodes) != 1:
        raise ValueError('原公开范围函数不唯一，未覆盖核心。')
    node = nodes[0]
    actual = ast.get_source_segment(text, node).replace('\r\n', '\n')
    if actual == PATCHED_FUNCTION:
        return data
    if actual != BASE_FUNCTION:
        raise ValueError('原公开范围函数不是已核对的版本，未覆盖其他修改。')
    lines = text.splitlines(keepends=True)
    newline = '\r\n' if '\r\n' in text else '\n'
    lines[node.lineno-1:node.end_lineno] = [(PATCHED_FUNCTION + '\n').replace('\n', newline)]
    changed = ''.join(lines)
    ast.parse(changed)
    prefix = b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b''
    return prefix + changed.encode('utf-8')


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def clear_cache(path):
    Path(importlib.util.cache_from_source(str(path))).unlink(missing_ok=True)


def probe(root):
    script = ('import ast,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
              'import fb_upload as u;import reel_audience_dialog_recovery as r;'
              "assert u.VERSION=='2.47' and r.VERSION=='1.0-reel-audience-close-or-continue';"
              "assert 'wait_for_public_controls' in u.ensure_personal_public_audience.__code__.co_names;"
              "print('VERIFIED: audience prompt Close/Continue fix installed. No video published.',flush=True)")
    subprocess.run([sys.executable, '-c', script, str(root)], check=True)


def install(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    import fb_upload as upload
    from add_fb_accounts import locked
    if upload.ROOT.resolve() != root or upload.VERSION != '2.47':
        raise ValueError('需使用原2.47上传目录，未修改其他目录。')
    with patch.object(workers, 'BOOTSTRAP', BOOTSTRAP):
        live = workers.active_workers(root, Path(__file__).resolve())
    if live:
        raise ValueError('仍有发布、分配或登录检查进程，请等其结束后安装：' + ','.join(str(r['pid']) for r in live))
    core = root / 'fb_upload.py'
    helper = root / 'reel_audience_dialog_recovery.py'
    for path in (core, helper):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('程序路径为链接，未修改。')
    helper_bytes = Path(__file__).with_name(helper.name).read_bytes()
    ast.parse(helper_bytes.decode('utf-8-sig'))
    with locked():
        original = core.read_bytes()
        changed = build_core(original)
        old_helper = helper.read_bytes() if helper.exists() else None
        if changed == original and old_helper == helper_bytes:
            probe(root)
            print('此修正已安装，不重复修改。没有发布或补发视频。', flush=True)
            return 0
        backup = root / 'backups' / ('reel-audience-dialog-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True)
        (backup / core.name).write_bytes(original)
        if old_helper is not None:
            (backup / helper.name).write_bytes(old_helper)
        try:
            atomic_write(helper, helper_bytes)
            atomic_write(core, changed)
            clear_cache(core)
            clear_cache(helper)
            probe(root)
        except BaseException:
            atomic_write(core, original)
            if old_helper is None:
                helper.unlink(missing_ok=True)
            else:
                atomic_write(helper, old_helper)
            clear_cache(core)
            clear_cache(helper)
            raise
    print('原程序已备份：', backup, flush=True)
    print('今后在 Reel 公开范围步骤，已识别的提示可自动 Close/Continue，然后仍确认 Public。', flush=True)
    print('本入口只安装修正；不启动昨天或今天的发布/补发，不改视频、账号或成功状态。', flush=True)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    try:
        if sys.platform != 'win32':
            raise ValueError('请在原Windows上传电脑的PowerShell窗口运行。')
        raise SystemExit(install(Path(sys.argv[1])))
    except KeyboardInterrupt:
        print('已暂停安装，未启动任何视频任务。', flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', str(error) or type(error).__name__, flush=True)
        raise SystemExit(1)
