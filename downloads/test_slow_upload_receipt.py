"""Verify the hard publication deadline, including active upload and dismissal."""
import contextlib
import io
import inspect
import time
import unittest
from unittest.mock import MagicMock

from playwright.sync_api import sync_playwright
import fb_upload as upload


class SlowUploadReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.page=self.browser.new_page()
        self.page.set_content('''<div role="dialog" aria-label="Create reel"><div id="busy"><span>Posting</span>
        <span>Uploading 50%</span></div><button id="post" disabled>Post</button></div>''')
        self.button=self.page.get_by_role('button',name='Post',exact=True)
        self.silence=contextlib.redirect_stdout(io.StringIO());self.silence.__enter__()
        upload.install_receipt_watch(self.page)
        self.page.evaluate('window.__fbUploadWatch.armed=true')

    def tearDown(self):
        self.silence.__exit__(None,None,None);self.page.close()

    def later_finish(self,delay=300,receipt=True,keep_button=False):
        self.page.evaluate('''({delay,receipt,keepButton})=>setTimeout(()=>{
            document.querySelector('#busy').remove();
            if(!keepButton) document.querySelector('#post').hidden=true;
            if(receipt){const status=document.createElement('div');status.role='alert';
              status.textContent='Your reel is published.';document.body.append(status)}
        },delay)''',dict(delay=delay,receipt=receipt,keepButton=keep_button))

    def test_upload_finishes_inside_budget_without_second_post(self):
        self.later_finish(delay=100)
        message=upload.wait_for_receipt(self.page,self.button,timeout_ms=1500,poll_ms=100)
        self.assertEqual(message,'Your reel is published.')
        self.assertFalse(self.page.is_closed())
        self.assertTrue(self.button.is_hidden())
        self.assertFalse(self.page.is_closed())

    def test_completed_upload_without_fresh_success_is_not_marked_published(self):
        self.later_finish(delay=100,receipt=False)
        with self.assertRaises(upload.ReceiptNeedsReview):
            upload.wait_for_receipt(self.page,self.button,timeout_ms=80,poll_ms=25,completion_grace_ms=50)
        self.assertIsNone(self.page.evaluate('window.__fbUploadWatch.message'))

    def test_hidden_or_outside_composer_progress_does_not_extend_wait(self):
        self.page.locator('#busy').evaluate('e=>e.hidden=true')
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=\"banner\">Uploading 50%</div>')")
        self.assertIsNone(upload.visible_upload_activity(self.page,self.button))
        with self.assertRaises(upload.ReceiptNeedsReview):
            upload.wait_for_receipt(self.page,self.button,timeout_ms=80,poll_ms=25)

    def test_fresh_success_cannot_close_browser_while_composer_still_uploading(self):
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=\"alert\">Your reel is published.</div>')")
        self.later_finish(delay=200,receipt=False)
        self.assertEqual(upload.wait_for_receipt(self.page,self.button,timeout_ms=1500,poll_ms=100),'Your reel is published.')
        self.assertTrue(self.button.is_hidden())
        self.assertFalse(self.page.is_closed())

    def test_old_success_message_and_new_progress_do_not_count_as_fresh_success(self):
        self.page.set_content('''<div role="alert">Your reel is published.</div><div role="dialog" aria-label="Create reel">
            <div id="busy">Uploading 50%</div><button id="post">Post</button></div>''')
        self.button=self.page.get_by_role('button',name='Post',exact=True)
        upload.install_receipt_watch(self.page);self.page.evaluate('window.__fbUploadWatch.armed=true')
        self.later_finish(delay=100,receipt=False)
        with self.assertRaises(upload.ReceiptNeedsReview):
            upload.wait_for_receipt(self.page,self.button,timeout_ms=80,poll_ms=25,completion_grace_ms=50)

    def test_receipt_and_open_idle_composer_remain_unknown(self):
        self.page.locator('#busy').evaluate('e=>e.remove()')
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=\"alert\">Your reel is published.</div>')")
        with self.assertRaises(upload.ReceiptNeedsReview):
            upload.wait_for_receipt(self.page,self.button,timeout_ms=80,poll_ms=25)

    def test_default_deadline_is_three_minutes(self):
        self.assertEqual(inspect.signature(upload.wait_for_receipt).parameters['timeout_ms'].default,180000)

    def test_active_upload_does_not_extend_hard_deadline_even_with_legacy_grace(self):
        started=time.monotonic()
        with self.assertRaisesRegex(upload.ReceiptNeedsReview,'最多 3 分钟'):
            upload.wait_for_receipt(self.page,self.button,timeout_ms=100,poll_ms=30,completion_grace_ms=120000)
        self.assertLess(time.monotonic()-started,2)
        self.assertFalse(self.page.is_closed())
        self.assertEqual(self.page.locator('#busy').count(),1)

    def test_success_receipt_does_not_extend_deadline_for_stuck_composer(self):
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=\"alert\">Your reel is published.</div>')")
        with self.assertRaises(upload.ReceiptNeedsReview):
            upload.wait_for_receipt(self.page,self.button,timeout_ms=100,poll_ms=30)
        self.assertTrue(self.button.is_visible())

    def test_post_click_elapsed_time_is_counted_and_larger_timeout_cannot_exceed_three_minutes(self):
        started=time.monotonic()
        with self.assertRaises(upload.ReceiptNeedsReview):
            upload.wait_for_receipt(self.page,self.button,timeout_ms=900000,started_at=started-181)
        self.assertLess(time.monotonic()-started,1)

    def test_fake_or_unstructured_activity_is_never_treated_as_active_upload(self):
        button=MagicMock()
        for value in [MagicMock(),True,'Posting',{'active':True},{'active':False,'label':'Posting'}]:
            button.evaluate.return_value=value
            self.assertIsNone(upload.visible_upload_activity(self.page,button))
