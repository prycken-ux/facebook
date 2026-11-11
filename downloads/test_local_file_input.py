import contextlib,hashlib,io,tempfile,unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
from unittest.mock import patch
import fb_upload as upload
import scheduled_material_batch as batch
import normal_chrome_batch as normal
import local_file_input as local
import publication_preferences as preferences


class LargeLocalFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.entry=dict(account='fb01',target='page01',type='page',name='Example',url='https://www.facebook.com/profile.php?id=1001',enabled=False)
        cls.video=cls.root/'videos/fb01/page01/inbox/large.mp4';cls.video.parent.mkdir(parents=True)
        with cls.video.open('wb') as f:
            for i in range(64):f.write(bytes([i])*1024*1024)
        cls.caption=cls.video.with_suffix('.txt');cls.caption.write_text('Original caption')
        cls.sha=batch.file_hash(cls.video)
        with patch.object(upload,'ROOT',cls.root):key=upload.job_key(cls.entry,cls.video)
        cls.job=dict(account='fb01',target='page01',url=cls.entry['url'],filename='large.mp4',key=key,
                     entry_sha256=batch.digest(cls.entry),caption_text='Original caption',caption_sha256=batch.file_hash(cls.caption),video_size=cls.video.stat().st_size)
        upload.save_json(cls.root/'upload_config.json',dict(targets=[cls.entry]))
        cls.pw=sync_playwright().start();cls.fixture=cls.pw.chromium.launch_persistent_context(str(cls.root/'profile'),executable_path='/usr/bin/chromium',headless=True,args=['--remote-debugging-address=127.0.0.1','--remote-debugging-port=0'])
        cls.browser=cls.pw.chromium.connect_over_cdp(normal.endpoint(cls.root/'profile/DevToolsActivePort'))
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.fixture.close();cls.pw.stop();cls.temp.cleanup()
    def setUp(self):
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.context=self.browser.contexts[0];self.page=self.context.new_page()
        self.page.route('https://www.facebook.com/**',lambda r:r.fulfill(content_type='text/html',body='<input type=file id=picker>'))
        self.page.goto(self.entry['url'])
        self.addCleanup(self.page.close);self.addCleanup(lambda:local.release(self.context))
    def authorize(self):local.authorize(self.context,self.entry,[self.job])
    def assert_bytes(self):
        value=self.page.evaluate('''async()=>{const f=document.querySelector('input').files[0];return {name:f.name,size:f.size,sha:[...new Uint8Array(await crypto.subtle.digest('SHA-256',await f.arrayBuffer()))].map(x=>x.toString(16).padStart(2,'0')).join('')}}''')
        self.assertEqual(value,dict(name=self.video.name,size=self.job['video_size'],sha=self.sha))
    def test_reproduces_old_50mb_cdp_failure_then_locator_and_element_select_full_64mb_unchanged(self):
        with self.assertRaises(Exception) as error:self.page.locator('input').set_input_files(str(self.video))
        self.assertIn('50Mb',str(error.exception))
        self.authorize();self.page.locator('input').set_input_files(str(self.video));self.assert_bytes()
        self.page.set_content('<input type=file>');self.page.query_selector('input').set_input_files(str(self.video));self.assert_bytes()
    def test_original_core_native_chooser_and_reels_form_both_select_large_original(self):
        self.authorize()
        self.page.set_content('<input type=file id=picker hidden><button onclick="document.querySelector(\'input\').click()">Reel</button>')
        self.assertEqual(upload.select_reel_video(self.page,self.page.get_by_role('button',name='Reel'),self.video,timeout_ms=3000),'native_file_chooser');self.assert_bytes()
        self.page.set_content('<button onclick="document.querySelector(\'form\').hidden=false">Reel</button><form role=form aria-label=Reels hidden><input type=file></form>')
        self.assertEqual(upload.select_reel_video(self.page,self.page.get_by_role('button',name='Reel'),self.video,timeout_ms=3000),'reels_form_file_input');self.assert_bytes()
    def test_out_of_scope_file_changed_caption_and_changed_video_stop_before_selection(self):
        self.authorize();wrong=self.video.parent/'other.mp4';wrong.write_bytes(b'other')
        with self.assertRaises(ValueError):self.page.locator('input').set_input_files(str(wrong))
        self.caption.write_text('Changed')
        try:
            with self.assertRaises(ValueError):self.page.locator('input').set_input_files(str(self.video))
        finally:self.caption.write_text('Original caption')
        with self.video.open('r+b') as f:f.write(b'X')
        try:
            with self.assertRaises(ValueError):self.page.locator('input').set_input_files(str(self.video))
        finally:
            with self.video.open('r+b') as f:f.write(b'\0')
        self.assertEqual(self.page.locator('input').evaluate('e=>e.files.length'),0)
    def test_unrelated_context_keeps_original_behavior_and_release_restores_api(self):
        from playwright.sync_api import Locator
        original=Locator.set_input_files;self.authorize();self.assertIsNot(Locator.set_input_files,original)
        extra=self.browser.new_context()
        try:
            page=extra.new_page();page.set_content('<input type=file>')
            with self.assertRaises(Exception) as error:page.locator('input').set_input_files(str(self.video))
            self.assertIn('50Mb',str(error.exception))
        finally:extra.close()
        local.release(self.context);self.assertIs(Locator.set_input_files,original)
    def test_windows_startup_selfcheck_uses_both_paths_and_removes_temporary_fixture(self):
        self.authorize();local.self_check(self.context,self.job)
        self.assertFalse(list((self.root/'logs').glob('*.html')))
    def test_new_content_revision_selfcheck_requires_and_uses_frozen_date(self):
        (self.root/'logs').mkdir(exist_ok=True)
        with patch.object(upload,'CONFIG',self.root/'upload_config.json'):
            preferences.save_authorized(resume_from='2026-11-11');revision=preferences.save_content_authorized()
            original=self.caption.read_bytes();self.caption.write_text(preferences.EVERYDAY_CAPTION)
            job=dict(self.job,caption_text=preferences.EVERYDAY_CAPTION,caption_sha256=batch.file_hash(self.caption),publication_content_sha256=revision['sha256'])
            try:
                # Reproduce the missing-date failure at the old file-check boundary.
                with self.assertRaises(TypeError):batch.validate_job(job)
                with self.assertRaisesRegex(ValueError,'缺少冻结批次日期'):local.authorize(self.context,self.entry,[job])
                local.authorize(self.context,self.entry,[job],date='2026-11-11')
                local.self_check(self.context,job)
                self.assertEqual(batch.file_hash(self.video),self.sha)
                local.release(self.context)
                local.authorize(self.context,self.entry,[job],date='2026-11-10')
                with self.assertRaises(ValueError):self.page.locator('input').set_input_files(str(self.video))
                self.assertEqual(self.page.locator('input').evaluate('e=>e.files.length'),0)
            finally:
                local.release(self.context);self.caption.write_bytes(original)
                (self.root/'publication_preferences.json').unlink(missing_ok=True)
                (self.root/'common_caption_today.txt').unlink(missing_ok=True)
