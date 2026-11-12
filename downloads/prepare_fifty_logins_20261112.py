"""Prepare fifty independent local login slots; no Facebook account creation."""
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

BATCH_ID = 'personal-20261112-fifty-fb25-fb74'
ACCOUNTS = tuple('fb%02d' % n for n in range(25, 75))


def prepare(root):
    root = Path(root).resolve()
    if sys.platform != 'win32':
        raise ValueError('请在原Windows上传电脑运行。')
    sys.path.insert(0, str(root))
    import add_personal_accounts as accounts
    import add_fb_accounts as legacy
    import fb_upload as upload
    if any(module.ROOT.resolve() != root for module in (accounts, legacy, upload)):
        raise ValueError('程序目录与原上传目录不一致，未创建。')
    if getattr(accounts, 'RESERVATION_VERSION', '') != '1.1-minimum-account-number':
        raise ValueError('原新增账号模块版本不匹配，未创建。')
    chrome = legacy.find_chrome()
    with legacy.locked():
        config, registry, manifest = accounts.documents()
        saved = manifest['batches'].get(BATCH_ID)
        if saved is None:
            occupied = accounts.occupied_numbers(config, registry, manifest)
            if max(occupied) >= 25:
                raise ValueError('本机已有fb25或之后的编号资料，未覆盖；请保留本条提示核对编号。')
        elif saved.get('accounts') != list(ACCOUNTS) or saved.get('count') != 50:
            raise ValueError('本次50个账号的预留记录不一致，未另建一批。')
        # A rerun may use only the same owned slots, never a linked directory.
        for account in ACCOUNTS:
            paths = [root/'profiles'/account, root/'videos'/account,
                     root/accounts.SHORTCUTS/(account+' 登录.lnk')]
            for path in paths:
                for component in (path, *path.parents):
                    if component == root:
                        break
                    if component.is_symlink():
                        raise ValueError('账号路径包含目录链接，未写入：' + str(component))
            for name in ('inbox', 'completed', 'failed'):
                path = root/'videos'/account/'personal'/name
                if path.is_symlink() or path.parent.is_symlink():
                    raise ValueError('素材路径包含目录链接，未写入：' + str(path))
        before = {path: path.read_bytes() for path in
                  (root/'upload_config.json', root/'account_registry.json')}
        selected = accounts.reserve(50, BATCH_ID, minimum_number=25)
        if selected != list(ACCOUNTS):
            raise ValueError('分配编号与本次fb25–fb74不一致，停止创建快捷方式。')
        folder = root/accounts.SHORTCUTS
        folder.mkdir(exist_ok=True)
        items = accounts.shortcut_items(selected, chrome)
        existing = [Path(item['path']) for item in items if Path(item['path']).is_file()]
        if existing:
            backup = root/'backups'/('fifty-login-shortcuts-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            backup.mkdir(parents=True)
            for path in existing:
                shutil.copy2(path, backup/path.name)
        legacy.write_shortcuts(items)
        missing = [item['path'] for item in items if not Path(item['path']).is_file()]
        if missing:
            raise ValueError('仍有登录快捷方式未生成，重跑本命令继续同一批编号。')
        for path, data in before.items():
            if path.read_bytes() != data:
                raise RuntimeError('原账号配置在操作期间变化，请核对：' + str(path))
    print('已创建/核对50个独立登录快捷方式：fb25–fb74。', flush=True)
    print('登录入口：', folder, flush=True)
    print('视频放置示例：', root/'videos/fb25/personal/inbox', flush=True)
    print('每个编号都有personal/inbox、personal/completed、personal/failed。', flush=True)
    print('可逐个双击登录；不要把同一个Facebook账号登录到多个编号。', flush=True)
    print('新编号已预留，尚未登记本人主页身份。登录完成后核验登记，再加入后续视频发布及评论。', flush=True)
    print('原账号和发布记录保留；重复运行仍使用这50个编号。本次没有上传视频或发送评论。', flush=True)
    try:
        os.startfile(str(folder))
    except OSError:
        print('入口已创建，请手动打开上面的登录文件夹。', flush=True)
    return selected


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    try:
        prepare(Path(sys.argv[1]))
    except KeyboardInterrupt:
        print('已停止；保留预留记录，重跑继续这50个编号。', flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：', str(error) or type(error).__name__, flush=True)
        raise SystemExit(1)
