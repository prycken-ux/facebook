import contextlib,io,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
import browser_background_mode as mode
import browser_background_mode_installer as installer
import fb_upload as upload
import normal_chrome_batch as normal
from test_normal_chrome_batch import NormalChromeTests
from test_scheduled_material_batch import ScheduledMaterialTests


class BackgroundUnitTests(unittest.TestCase):
    def setUp(self):
        self.fx=NormalChromeTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root
    def save(self,value):upload.save_json(self.root/mode.SETTINGS,value)
    def test_background_uses_original_profile_without_any_visible_window_fallback(self):
        self.save(dict(schema=mode.SCHEMA,mode='background'))
        wrapper=normal.launch_normal(self.fx.pw,self.fx.entry)
        args=self.fx.popen.call_args.args[0]
        self.assertIn('--headless=new',args);self.assertNotIn('--new-window',args)
        self.assertIn('--user-data-dir='+str(self.fx.profile),args)
        self.assertFalse(any(arg.startswith(('--disable-extensions','--proxy-server','--no-sandbox','--user-agent')) for arg in args))
        wrapper.close()
        self.fx.popen.reset_mock();self.fx.pw.chromium.connect_over_cdp.side_effect=RuntimeError('unsupported background')
        with self.assertRaises(RuntimeError):normal.launch_normal(self.fx.pw,self.fx.entry)
        self.assertEqual(self.fx.popen.call_count,1)
        self.assertIn('--headless=new',self.fx.popen.call_args.args[0])
    def test_corrupt_setting_stops_before_starting_any_browser_and_missing_setting_keeps_foreground(self):
        self.save(dict(schema=mode.SCHEMA,mode='typo'))
        with self.assertRaises(ValueError):normal.launch_normal(self.fx.pw,self.fx.entry)
        self.fx.popen.assert_not_called()
        (self.root/mode.SETTINGS).unlink();wrapper=normal.launch_normal(self.fx.pw,self.fx.entry)
        self.assertIn('--new-window',self.fx.popen.call_args.args[0]);wrapper.close()


class RealBackgroundTests(unittest.TestCase):
    def test_real_chrome_headless_profile_cookie_persistence_and_exact_original_file_picker(self):
        import local_file_input as local
        import scheduled_material_batch as batch
        with tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack,sync_playwright() as pw:
            root=Path(tmp);profile=root/'profiles/fb02';profile.mkdir(parents=True)
            entry=dict(account='fb02',target='page01',type='page',name='Example',url='https://www.facebook.com/profile.php?id=1002',enabled=False)
            video=root/'videos/fb02/page01/inbox/original.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'original-media-'+bytes(range(256))*2048)
            caption=video.with_suffix('.txt');caption.write_text('Original text')
            upload.save_json(root/'upload_config.json',dict(targets=[entry]));upload.save_json(root/mode.SETTINGS,dict(schema=mode.SCHEMA,mode='background'))
            stack.enter_context(patch.object(upload,'ROOT',root));stack.enter_context(patch.object(upload,'CONFIG',root/'upload_config.json'))
            stack.enter_context(patch.object(normal,'find_chrome',return_value=Path('/usr/bin/chromium')))
            stack.enter_context(patch.object(normal,'close_selected_window'))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            # Linux fixture only: existing Chrome tests run in an unprivileged
            # container without OS sandbox support. Production flags stay intact.
            real_popen=subprocess.Popen;processes=[]
            def fixture_popen(args,**kwargs):
                process=real_popen([*args[:-1],'--no-sandbox',args[-1]],**kwargs);processes.append(process);return process
            stack.enter_context(patch.object(normal.subprocess,'Popen',side_effect=fixture_popen))
            key=upload.job_key(entry,video)
            job=dict(account='fb02',target='page01',url=entry['url'],filename=video.name,key=key,entry_sha256=batch.digest(entry),caption_text='Original text',caption_sha256=batch.file_hash(caption),video_size=video.stat().st_size)
            cookie=dict(name='fixture',value='preserved-session',domain='example.com',path='/',expires=2000000000)
            for attempt in range(2):
                context=normal.launch_normal(pw,dict(entry,_local_file_selfcheck=True))
                try:
                    if not attempt:context.add_cookies([cookie])
                    else:self.assertEqual([c['value'] for c in context.cookies(['https://example.com/']) if c['name']=='fixture'],['preserved-session'])
                    local.authorize(context._context,entry,[job]);local.self_check(context,job)
                finally:
                    context.close()
                    for process in processes:process.wait(timeout=10)
            self.assertEqual(video.read_bytes(),b'original-media-'+bytes(range(256))*2048)


class BackgroundInstallerTests(unittest.TestCase):
    def setUp(self):
        self.fx=ScheduledMaterialTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.root=self.fx.root;self.code=Path(__file__).resolve().parent
        self.updates={name:(self.code/name).read_bytes() for name in installer.NAMES}
    def test_failed_import_rolls_back_mode_and_modules_without_touching_receipts(self):
        original=b'# original launcher\n';(self.root/'normal_chrome_batch.py').write_bytes(original)
        upload.save_json(self.root/mode.SETTINGS,dict(schema=mode.SCHEMA,mode='foreground'))
        setting=(self.root/mode.SETTINGS).read_bytes();state=self.fx.state_path.read_bytes()
        with patch.object(installer.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['probe'])):
            with self.assertRaises(subprocess.CalledProcessError):installer.install(self.root,self.updates)
        self.assertEqual((self.root/mode.SETTINGS).read_bytes(),setting)
        self.assertEqual((self.root/'normal_chrome_batch.py').read_bytes(),original)
        self.assertEqual(self.fx.state_path.read_bytes(),state)
        self.assertTrue(all(not (self.root/name).exists() for name in installer.NAMES if name!='normal_chrome_batch.py'))
    def test_successful_install_imports_in_fresh_interpreter_and_keeps_all_video_state(self):
        for path in self.code.glob('*.py'):shutil.copy2(path,self.root/path.name)
        before=self.fx.state_path.read_bytes();installer.install(self.root,self.updates)
        self.assertEqual(mode.mode(self.root),'background');self.assertEqual(self.fx.state_path.read_bytes(),before)
    def test_child_uses_closed_stdin_and_refuses_active_publisher_before_install(self):
        import zipfile
        from datetime import datetime,timezone
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for name,data in self.updates.items():z.writestr(name,data)
        resume=b"if __name__=='__main__':\n import sys\n assert len(sys.argv)==2\n try:input()\n except EOFError:pass\n else:raise AssertionError('stdin must be closed')\n"
        with patch.object(installer.sys,'platform','win32'),patch.object(installer,'datetime',wraps=datetime) as clock,patch.object(installer,'install'):
            clock.now.return_value=datetime(2026,11,14,4,tzinfo=timezone.utc)
            with patch.object(installer,'download',side_effect=[stream.getvalue(),resume,b'def recover_locks(root):pass\n']):
                self.assertEqual(installer.start(self.root),0)
            with patch.object(installer,'download',side_effect=[stream.getvalue(),resume,b'def recover_locks(root):raise RuntimeError("active publisher")\n']),patch.object(installer.subprocess,'run') as run:
                with self.assertRaisesRegex(RuntimeError,'active publisher'):installer.start(self.root)
                run.assert_not_called()


if __name__=='__main__':unittest.main()
