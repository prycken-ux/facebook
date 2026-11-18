"""Read passive GraphQL bodies only after request completion, within this run."""
import contextlib,weakref
from unittest.mock import patch
import fb_upload as upload

VERSION='1.0-completed-response-capture-bounded-diagnostics'
PASSIVE_MODULES={'safe_video_comments','capture_current_publication','published_video_lookup','actual_reels_comment_lookup'}
SCREENSHOT_TIMEOUT_MS=3000


@contextlib.contextmanager
def installed(context_class=None,page_class=None):
    if context_class is None or page_class is None:
        from playwright.sync_api import BrowserContext,Page
        context_class=context_class or BrowserContext;page_class=page_class or Page
    original_on=context_class.on;original_remove=context_class.remove_listener;original_shot=page_class.screenshot;original_receipt=upload.wait_for_receipt
    bindings=weakref.WeakKeyDictionary()
    def on(context,event,callback):
        if event!='response' or getattr(callback,'__module__','') not in PASSIVE_MODULES:return original_on(context,event,callback)
        def finished(request):
            try:
                response=request.response()
                if response is not None:callback(response)
            except Exception:
                # Missing/evicted response evidence never establishes success
                # and cannot prevent the pending job from being preserved.
                pass
        result=original_on(context,'requestfinished',finished)
        bindings.setdefault(context,[]).append((callback,finished));return result
    def remove(context,event,callback):
        if event=='response':
            rows=bindings.get(context,[])
            for i,(saved,finished) in enumerate(rows):
                if saved==callback:
                    rows.pop(i);return original_remove(context,'requestfinished',finished)
        return original_remove(context,event,callback)
    def screenshot(page,*args,**kwargs):
        timeout=kwargs.get('timeout')
        kwargs['timeout']=min(timeout,SCREENSHOT_TIMEOUT_MS) if isinstance(timeout,(int,float)) and timeout>0 else SCREENSHOT_TIMEOUT_MS
        return original_shot(page,*args,**kwargs)
    def receipt(*args,**kwargs):
        try:return original_receipt(*args,**kwargs)
        except upload.ReceiptNeedsReview:
            print('本条回执等待已到上限：转待核实，不重复点击发布。接下来限时保存诊断并关闭本账号窗口，再继续其他目标。',flush=True)
            raise
    with patch.object(context_class,'on',on),patch.object(context_class,'remove_listener',remove),patch.object(page_class,'screenshot',screenshot),patch.object(upload,'wait_for_receipt',side_effect=receipt):
        try:yield
        finally:
            for context,rows in list(bindings.items()):
                for _,finished in list(rows):
                    try:original_remove(context,'requestfinished',finished)
                    except Exception:pass
            bindings.clear()
