import ast, hashlib, importlib.util, io, shutil, ssl, sys, tempfile, urllib.request, zipfile
from datetime import datetime
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from add_fb_accounts import locked

expected = '558538fa79aaa6144deea48cba2300c55bea4f73787d7a48732df6ba7e4c7888'
urls = [
    'https://raw.githubusercontent.com/prycken-ux/facebook/b6c6b8239357872d9e7fafa60fa7c669a4170b8d/downloads/retry-oct30-eight-v1.zip',
    'https://github.com/prycken-ux/facebook/raw/b6c6b8239357872d9e7fafa60fa7c669a4170b8d/downloads/retry-oct30-eight-v1.zip'
]

def write_atomic(path, content):
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

with locked():
    import fb_upload
    if fb_upload.VERSION not in {'2.38', '2.39', '2.40', '2.41', '2.42'}:
        raise RuntimeError('Expected uploader 2.38 through 2.42; no files changed.')
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    data = None
    for number, url in enumerate(urls, 1):
        print('Downloading verified update, source', number, flush=True)
        try:
            with urllib.request.urlopen(url, context=context, timeout=25) as response:
                candidate = response.read(2 * 1024 * 1024 + 1)
            if hashlib.sha256(candidate).hexdigest() != expected:
                raise RuntimeError('Package checksum mismatch')
            data = candidate
            break
        except Exception as error:
            print('Download failed:', str(error).splitlines()[0], flush=True)
    if data is None:
        raise RuntimeError('Both download sources failed; no scripts changed.')

    names = ['fb_upload.py', 'publish_fb10_pages_direct.py', 'publish_other_accounts_direct.py', 'retry_current_verified_absent.py', 'resume_confirmed_other_failures.py', 'scheduled_material_batch.py', 'safe_video_comments.py', 'published_video_lookup.py', 'daily_publish_and_comments.py', 'retry_oct30_eight.py']
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        updates = {name: archive.read(name) for name in names}
    for content in updates.values():
        ast.parse(content.decode('utf-8-sig'))
    backup = root / 'backups' / ('retry-eight-install-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    originals = {}
    for name in names:
        path = root / name
        originals[name] = path.read_bytes() if path.exists() else None
        if path.exists():
            shutil.copy2(path, backup / name)
    changed = []
    try:
        for name in names:
            write_atomic(root / name, updates[name])
            changed.append(name)
        # Timestamp-based bytecode may otherwise survive an atomic same-second update.
        for name in names:
            cache = Path(importlib.util.cache_from_source(str(root / name)))
            if cache.is_file():
                cache.resolve().relative_to(root.resolve())
                cache.unlink()
    except BaseException:
        for name in reversed(changed):
            if originals[name] is None:
                (root / name).unlink(missing_ok=True)
            else:
                write_atomic(root / name, originals[name])
        raise
    print('Installed uploader 2.42: exact eight-job retry with caption popup protection. Backup:', backup, flush=True)
    print('Existing publication records, captions, comments and frozen media are unchanged. No upload started by this installer.', flush=True)
