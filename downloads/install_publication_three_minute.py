import ast, hashlib, io, shutil, ssl, sys, tempfile, urllib.request, zipfile
from datetime import datetime
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from add_fb_accounts import locked

expected = '5e5e8dcbe120a7fc5ec58e4ed0d829830131026794748d0cf7dbae3293324787'
urls = [
    'https://raw.githubusercontent.com/prycken-ux/facebook/aa3c4d58b282af6d8a0ddbd4481d40e72eb3effb/downloads/publication-hard-three-minutes-v1.zip',
    'https://github.com/prycken-ux/facebook/raw/aa3c4d58b282af6d8a0ddbd4481d40e72eb3effb/downloads/publication-hard-three-minutes-v1.zip'
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
    if fb_upload.VERSION not in {'2.38', '2.39'}:
        raise RuntimeError('Expected uploader 2.38 or 2.39; no files changed.')
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

    names = ['fb_upload.py', 'publish_fb10_pages_direct.py', 'publish_other_accounts_direct.py', 'retry_current_verified_absent.py', 'resume_confirmed_other_failures.py', 'scheduled_material_batch.py']
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        updates = {name: archive.read(name) for name in names}
    for content in updates.values():
        ast.parse(content.decode('utf-8-sig'))
    backup = root / 'backups' / ('hard-three-minutes-install-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
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
    except BaseException:
        for name in reversed(changed):
            if originals[name] is None:
                (root / name).unlink(missing_ok=True)
            else:
                write_atomic(root / name, originals[name])
        raise
    print('Installed uploader 2.39: post-click receipt and editor wait share a hard 180-second limit. Backup:', backup, flush=True)
    print('Existing publication records, captions, comments and frozen media are unchanged. No upload started by this installer.', flush=True)
