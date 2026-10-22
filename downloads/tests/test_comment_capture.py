import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import fb_upload as upload
import record_comment_flow as recording


class CaptureBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(upload,'ROOT',self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.html = '''<h1>Example Page</h1><article aria-label="Comment by Example Viewer">
        <p>Where can I buy this book?</p><button>Reply</button>
        <textarea aria-label="Write a reply..."></textarea></article>'''
        self.page.route('https://www.facebook.com/**', lambda route: route.fulfill(
            content_type='text/html',body=self.html))
        self.entry = dict(account='fb12',target='page01',type='page',name='Example Page',
                          url='https://www.facebook.com/profile.php?id=123')

    def test_actual_browser_saves_reply_controls_and_png_without_cookies(self):
        self.entry['url'] += '&access_token=FIXTURE-SECRET'
        self.page.goto('https://www.facebook.com/reel/456?comment_id=789&access_token=FIXTURE-SECRET#ignored')
        folder = recording.save_comment_view(self.page,self.entry)
        text = (folder/'comments.aria.txt').read_text()
        self.assertIn('Write a reply...',text)
        self.assertIn('Where can I buy this book?',text)
        self.assertTrue((folder/'comments.png').read_bytes().startswith(b'\x89PNG'))
        context = (folder/'context.json').read_text()
        self.assertNotIn('FIXTURE-SECRET',context)
        self.assertEqual(upload.read_json(folder/'context.json',{})['view_url'],
                         'https://www.facebook.com/reel/456?comment_id=789')
        self.assertEqual({p.name for p in folder.iterdir()},
                         {'comments.aria.txt','comments.png','context.json'})

    def test_actual_login_form_is_not_saved(self):
        self.html = '<h1>Log in</h1><input type="password" value="FIXTURE-PASSWORD">'
        self.page.goto('https://www.facebook.com/')
        with self.assertRaisesRegex(RuntimeError,'登录页面'):
            recording.save_comment_view(self.page,self.entry)
        self.assertFalse((self.root/'logs/comment-recordings').exists())

    def test_external_site_is_not_saved(self):
        self.page.route('https://example.com/**',lambda route:route.fulfill(body=self.html))
        self.page.goto('https://example.com/')
        with self.assertRaisesRegex(RuntimeError,'Facebook 评论页面'):
            recording.save_comment_view(self.page,self.entry)
        self.assertFalse((self.root/'logs/comment-recordings').exists())

class TopLevelCaptureTests(CaptureBrowserTests):
    def test_top_level_capture_keeps_mode_and_direct_video_identity(self):
        self.html = '<h1>Example Page</h1><div role="textbox" contenteditable="true" aria-label="Write a comment..."></div>'
        self.page.goto('https://www.facebook.com/reel/456?locale=en_US&access_token=FIXTURE-SECRET')
        folder = recording.save_comment_view(self.page, self.entry, mode='top-level')
        context = upload.read_json(folder / 'context.json', {})
        self.assertEqual(context['mode'], 'top-level')
        self.assertEqual(context['purpose'], 'top_level_comment_ui_adaptation_only')
        self.assertNotIn('FIXTURE-SECRET', (folder / 'context.json').read_text())
        self.assertIn('Write a comment...', (folder / 'comments.aria.txt').read_text())
        from zipfile import ZipFile
        with ZipFile(folder / 'top-level-comment-capture.zip') as archive:
            self.assertEqual(set(archive.namelist()), {'comments.aria.txt', 'comments.png', 'context.json'})
            self.assertNotIn('FIXTURE-SECRET', archive.read('context.json').decode())

    def test_profile_page_is_not_accepted_as_the_top_level_video_view(self):
        self.page.goto(self.entry['url'])
        with self.assertRaisesRegex(ValueError, '直接视频链接'):
            recording.save_comment_view(self.page, self.entry, mode='top-level')
        self.assertFalse((self.root / 'logs/comment-recordings').exists())
