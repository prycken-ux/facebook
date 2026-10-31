import contextlib,io,tempfile,time,unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
import fb_upload as upload

class MediaReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context();self.page=self.context.new_page();self.silent=contextlib.redirect_stdout(io.StringIO());self.silent.__enter__()
        self.context.route('https://www.facebook.com/**',lambda r:r.fulfill(content_type='text/html',body='<main><h1>Create reel</h1><div id=empty>Upload a video in order to see a preview here</div><input type=file accept="video/*" onchange="window.selected=this.files[0].name;window.selections=(window.selections||0)+1;document.querySelector(\'#empty\').remove();document.body.insertAdjacentHTML(\'beforeend\',\'<textarea aria-label=&quot;Describe your reel...&quot;></textarea>\')"><button disabled>Next</button></main>'))
        self.page.goto('https://www.facebook.com/reels/create')
        self.temp=tempfile.TemporaryDirectory();self.video=Path(self.temp.name)/'exact.mp4';self.video.write_bytes(b'fixture media')
    def tearDown(self):self.context.close();self.temp.cleanup();self.silent.__exit__(None,None,None)
    def test_visibly_discarded_file_is_reattached_once_to_same_empty_editor(self):
        self.assertTrue(upload.recover_empty_modern_editor(self.page,self.video,timeout_ms=1000,recovery_after_ms=0))
        self.assertEqual(self.page.evaluate('window.selected'),'exact.mp4');self.assertEqual(self.page.evaluate('window.selections'),1)
        self.assertFalse(upload.recover_empty_modern_editor(self.page,self.video,timeout_ms=200,recovery_after_ms=0));self.assertEqual(self.page.evaluate('window.selections'),1)
    def test_empty_add_video_native_picker_receives_only_same_exact_file(self):
        self.page.locator('input').evaluate("e=>{e.accept='';e.hidden=true;const b=document.createElement('button');b.textContent='Add video';b.onclick=()=>e.click();e.after(b)}")
        self.assertTrue(upload.recover_empty_modern_editor(self.page,self.video,timeout_ms=1000,recovery_after_ms=0))
        self.assertEqual(self.page.evaluate('window.selected'),'exact.mp4');self.assertEqual(self.page.evaluate('window.selections'),1)
    def test_named_caption_variant_cannot_match_a_different_actor(self):
        self.page.set_content("<h1>Create reel</h1><span>What's on your mind, Other Person?</span><div contenteditable=true></div>")
        self.assertEqual(self.page.evaluate(upload.MODERN_CAPTION_JS,dict(name='Example Page')),0)

    def test_two_file_inputs_unknown_dialog_or_already_selected_file_never_reselect(self):
        for mode in ['duplicate','dialog','selected']:
            self.page.reload()
            if mode=='duplicate':self.page.locator('input').evaluate("e=>e.after(e.cloneNode())")
            elif mode=='dialog':self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=dialog>Unknown</div>')")
            else:self.page.locator('input').evaluate("e=>{const d=new DataTransfer();d.items.add(new File(['x'],'other.mp4',{type:'video/mp4'}));e.files=d.files}")
            with self.assertRaises(RuntimeError):upload.recover_empty_modern_editor(self.page,self.video,timeout_ms=300,recovery_after_ms=0)
            self.assertIsNone(self.page.evaluate('window.selections'))
    def test_upload_53_percent_must_finish_before_publish_readiness(self):
        self.page.set_content('<main><div id=progress>Uploading 53%</div><button onclick="window.sent=true">Post</button></main>')
        button=self.page.get_by_role('button',name='Post',exact=True)
        self.page.evaluate("setTimeout(()=>document.querySelector('#progress').textContent='Uploading 100%',200)")
        start=time.monotonic();upload.wait_prepost_upload(self.page,button,timeout_ms=1000,stable_ms=20)
        self.assertGreaterEqual(time.monotonic()-start,.19);self.assertIsNone(self.page.evaluate('window.sent'))
    def test_upload_stall_disabled_button_and_preexisting_posting_never_click_post(self):
        for markup in ['<span>Uploading 53%</span><button>Post</button>','<button disabled>Post</button>','<span>Posting</span><button>Post</button>']:
            self.page.set_content('<main>'+markup+'</main>')
            with self.assertRaises(RuntimeError):upload.wait_prepost_upload(self.page,self.page.get_by_role('button',name='Post'),timeout_ms=120,stable_ms=20)
