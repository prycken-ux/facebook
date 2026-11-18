import contextlib,io,json,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import MagicMock,patch
import publication_response_finish_guard as app

class FakeContext:
    def __init__(self):self.handlers={}
    def on(self,event,callback):self.handlers.setdefault(event,[]).append(callback);return self
    def remove_listener(self,event,callback):
        if callback in self.handlers.get(event,[]):self.handlers[event].remove(callback)
    def emit(self,event,value):
        for callback in list(self.handlers.get(event,[])):callback(value)
class FakePage:
    def screenshot(self,**kwargs):self.last=kwargs;return b'image'

def passive(out):
    def callback(response):out.append(response.text())
    callback.__module__='safe_video_comments';return callback

class FinishGuardTests(unittest.TestCase):
    def test_header_does_not_read_body_finished_does_remove_and_restore_exactly(self):
        context=FakeContext();seen=[];callback=passive(seen);response=MagicMock();response.text.return_value='finished body';request=MagicMock();request.response.return_value=response
        on=FakeContext.on;remove=FakeContext.remove_listener
        with app.installed(FakeContext,FakePage):
            context.on('response',callback);context.emit('response',response);response.text.assert_not_called()
            context.emit('requestfinished',request);self.assertEqual(seen,['finished body'])
            context.remove_listener('response',callback);context.emit('requestfinished',request);self.assertEqual(len(seen),1)
        self.assertIs(FakeContext.on,on);self.assertIs(FakeContext.remove_listener,remove)
    def test_unrelated_callbacks_and_nonresponse_events_keep_original_behavior(self):
        context=FakeContext();seen=[]
        def ordinary(value):seen.append(value)
        with app.installed(FakeContext,FakePage):
            context.on('response',ordinary);context.emit('response','headers');context.on('page',ordinary);context.emit('page','page')
        self.assertEqual(seen,['headers','page'])
    def test_pending_request_and_bad_response_do_not_fake_receipt_or_block(self):
        context=FakeContext();seen=[];request=MagicMock();request.response.side_effect=RuntimeError('body not retained')
        with app.installed(FakeContext,FakePage):
            context.on('response',passive(seen));context.emit('requestfinished',request)
            self.assertEqual(seen,[])
        self.assertEqual(context.handlers['requestfinished'],[])
    def test_diagnostic_screenshot_budget_and_receipt_exception_preserved(self):
        page=FakePage()
        with patch.object(app.upload,'wait_for_receipt',side_effect=app.upload.ReceiptNeedsReview('original timeout')):
            with app.installed(FakeContext,FakePage),contextlib.redirect_stdout(io.StringIO()) as out:
                for requested,expected in [(None,3000),(0,3000),(90000,3000),(250,250)]:
                    page.screenshot(path='diagnostic.png',timeout=requested);self.assertEqual(page.last['timeout'],expected)
                with self.assertRaisesRegex(app.upload.ReceiptNeedsReview,'original timeout'):app.upload.wait_for_receipt(None,None)
                self.assertIn('转待核实',out.getvalue())

class NativeStreamingResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def test_unfinished_body_does_not_hold_up_receipt_timeout_then_complete_evidence_is_kept(self):
        done=threading.Event();headers=threading.Event();body=b'{"published":true}'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path=='/stream':
                    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.flush();headers.set();done.wait(5);self.wfile.write(body);self.wfile.flush()
                else:
                    data=b'<button id="post">Post</button>'
                    self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        context=self.browser.new_context();page=context.new_page();seen=[];origin='http://127.0.0.1:'+str(server.server_port)
        try:
            page.goto(origin);app.upload.install_receipt_watch(page);page.evaluate('window.__fbUploadWatch.armed=true')
            callback=passive(seen)
            with app.installed():
                context.on('response',callback);page.evaluate("() => {fetch('/stream').then(r=>r.text()).then(x=>window.streamResult=x);return true}")
                self.assertTrue(headers.wait(1));start=time.monotonic()
                with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(app.upload.ReceiptNeedsReview):app.upload.wait_for_receipt(page,page.locator('#post'),timeout_ms=100,poll_ms=25)
                self.assertLess(time.monotonic()-start,1.5);self.assertFalse(seen)
                with context.expect_event('requestfinished',predicate=lambda r:r.url.endswith('/stream')):
                    done.set();page.wait_for_function('window.streamResult!==undefined',timeout=5000)
                self.assertEqual(seen,[body.decode()])
                context.remove_listener('response',callback)
        finally:
            done.set();context.close();server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__':unittest.main()
