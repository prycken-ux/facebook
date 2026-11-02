import ast, hashlib, importlib.util, io, shutil, ssl, sys, tempfile, urllib.request, zipfile
from datetime import datetime
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from add_fb_accounts import locked

expected = 'c91bcef77f69dac9406aec3e49671076e126aa7fca2881698816d095687d038e'
urls = [
    'https://raw.githubusercontent.com/prycken-ux/facebook/fa390e30161c96a15a3127333e7a557d300b06c5/downloads/new-batch-retry-tabs-v1.zip',
    'https://github.com/prycken-ux/facebook/raw/fa390e30161c96a15a3127333e7a557d300b06c5/downloads/new-batch-retry-tabs-v1.zip'
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
    if fb_upload.VERSION not in {'2.47'}:
        raise RuntimeError('Expected installed uploader 2.47; no files changed.')
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

    names = ['scheduled_material_batch.py','publish_new_with_comments.py','published_video_lookup.py','published_video_surfaces.py']
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        updates = {name: archive.read(name) for name in names}
    for content in updates.values():
        ast.parse(content.decode('utf-8-sig'))
    backup = root / 'backups' / ('new-batch-retry-tabs-install-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
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
    print('Installed new-batch workflow 2.2 / comment lookup 1.1 on uploader 2.47. Backup:', backup, flush=True)
    print('INSTALL ONLY: no videos or comments sent. Old publication/comment records, captions and browser profiles are unchanged. New batches exclude all validated previous-day frozen media keys, run the first pass and one recoverable before-Post retry, then verify comments with profile/Reels/video lookup. No historical task is started. No batch was started. Existing records and retry claims are preserved; no old job was requeued.', flush=True)
