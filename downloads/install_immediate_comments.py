import ast, hashlib, importlib.util, io, shutil, ssl, subprocess, sys, tempfile, urllib.request, zipfile
from datetime import datetime
from pathlib import Path

expected = 'b3ebc56b696d501eec4e5a99895a0f6652fc889ed6b4bc5642a6e8c6a3a12fea'
urls = [
    'https://raw.githubusercontent.com/prycken-ux/facebook/cb1505dfc66679391214f580052c48596ce9cd15/downloads/immediate-verified-comments-v1.zip',
    'https://github.com/prycken-ux/facebook/raw/cb1505dfc66679391214f580052c48596ce9cd15/downloads/immediate-verified-comments-v1.zip'
]
VERIFY_CODE = (
    "import sys;sys.path.insert(0,sys.argv[1]);"
    "import fb_upload as u,safe_video_comments as c,publish_new_with_comments as p,automatic_batch_retry as r;"
    "assert u.VERSION=='2.47';assert u.IMMEDIATE_COMMENT_VERSION=='1.0-receipt-first-reload';"
    "assert p.PUBLISH_WORKFLOW_VERSION=='2.3-immediate-comments';"
    "assert r.AUTO_RETRY_VERSION=='1.1-immediate-aware';assert callable(c.immediate_verified_comment);"
    "print('INSTALL VERIFIED: immediate comment then reload, one safe video retry. No task started.',flush=True)"
)


def write_atomic(root,path,content):
    with tempfile.NamedTemporaryFile(dir=root,delete=False) as handle:
        temporary=Path(handle.name);handle.write(content)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def clear_caches(root,names):
    for name in names:
        cache=Path(importlib.util.cache_from_source(str(root/name)))
        if cache.is_file():
            cache.resolve().relative_to(root.resolve());cache.unlink()


def recover_locks(root):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    expected='2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3'
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            url=base+'d8c998c705801c948a230c0504fcb65653ae8086/downloads/recover_resume_new_batch.py'
            with urllib.request.urlopen(url,context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Lock helper checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));break
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    else:raise RuntimeError('锁核验组件下载失败，未改动发布记录')
    namespace={'__name__':'verified_lock_cleanup_library','__file__':'verified_lock_cleanup.py'}
    exec(compile(data,'verified-lock-cleanup','exec'),namespace);namespace['recover_locks'](root)



def install(root,recover=recover_locks):
    root=Path(root).resolve()
    if not (root/'upload_config.json').is_file():raise ValueError('Original uploader config not found; no files changed.')
    sys.path.insert(0,str(root))
    from add_fb_accounts import locked
    recover(root)
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

        names = ['fb_upload.py','safe_video_comments.py','scheduled_material_batch.py','publish_new_with_comments.py','automatic_batch_retry.py']
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            updates = {name: archive.read(name) for name in names}
        for content in updates.values():
            ast.parse(content.decode('utf-8-sig'))
        backup = root / 'backups' / ('immediate-comments-install-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
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
                write_atomic(root, root / name, updates[name])
                changed.append(name)
            clear_caches(root,names)
            subprocess.run([sys.executable,'-c',VERIFY_CODE,str(root)],check=True)
        except BaseException:
            for name in reversed(changed):
                if originals[name] is None:
                    (root / name).unlink(missing_ok=True)
                else:
                    write_atomic(root, root / name, originals[name])
            clear_caches(root,names)
            raise
        print('Installed new-batch workflow 2.3 / immediate verified comments / retry 1.1 on uploader 2.47. Backup:', backup, flush=True)
        print('INSTALL ONLY: no videos or comments sent. Old publication/comment records, captions and browser profiles are unchanged. Each new video now comments immediately in its publishing browser and verifies after reload before the next video. The one recoverable before-Post retry also uses immediate comments. No bulk historical comment pass is run. No historical task is started. No batch was started. Existing records and retry claims are preserved; no old job was requeued.', flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:install(Path(sys.argv[1]))
    except KeyboardInterrupt:print('Installation stopped; preserve output.',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP:',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
