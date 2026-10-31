import ast, hashlib, importlib.util, io, shutil, ssl, sys, tempfile, urllib.request, zipfile
from datetime import datetime
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from add_fb_accounts import locked

expected = 'e0b31f94359c94d3e93c10e6fdb4cda7a9c062bf208028b08056c85d68598f0b'
urls = [
    'https://raw.githubusercontent.com/prycken-ux/facebook/e7fde6598a1f791621a8b8be42ec1ea52d8c7322/downloads/fb06-direct-comment-v1.zip',
    'https://github.com/prycken-ux/facebook/raw/e7fde6598a1f791621a8b8be42ec1ea52d8c7322/downloads/fb06-direct-comment-v1.zip'
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
    if fb_upload.VERSION != '2.42':
        raise RuntimeError('Expected uploader 2.42; no files changed.')
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

    names = ['safe_video_comments.py', 'send_fb06_comment_once.py']
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        updates = {name: archive.read(name) for name in names}
    for content in updates.values():
        ast.parse(content.decode('utf-8-sig'))
    backup = root / 'backups' / ('fb06-comment-install-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
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
    print('Installed fb06 single-video comment workflow with reload verification. Backup:', backup, flush=True)
    print('Existing publication records, captions, comments and frozen media are unchanged. No upload started by this installer.', flush=True)
