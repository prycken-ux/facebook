import contextlib
import io
import tempfile
import time
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import fb_upload as upload
import safe_video_comments as comments


HTML='''<html lang="en-US"><main><a href="https://www.facebook.com/profile.php?id=1001">Example Page</a>
<div id="compose"><div id="field" role="textbox" contenteditable="true" aria-label="Write a comment..."></div>
<button aria-label="Comment" onclick="const f=document.querySelector('#field');window.sent=(window.sent||0)+1;
const article=document.createElement('div');article.setAttribute('role','article');article.setAttribute('aria-label','Comment by Example Page');
const author=document.createElement('a');author.href='https://www.facebook.com/profile.php?id=1001';author.textContent='Example Page';
article.append(author);const body=document.createElement('span');body.textContent=f.innerText;article.append(body);
document.body.append(article);f.innerText='';">Comment</button></div></main></html>'''


class VideoCommentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)

    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir()
        self.stack=contextlib.ExitStack();self.stack.enter_context(patch.object(upload,'ROOT',self.root))
        self.stack.enter_context(patch.object(upload,'recheck_publish_identity'));self.stack.enter_context(patch.object(upload,'page_actor_matches',return_value=True))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.context=self.browser.new_context();self.page=self.context.new_page();self.html=HTML
        self.context.route('https://www.facebook.com/**',lambda route:route.fulfill(body=self.html,content_type='text/html'))
        self.page.goto('https://www.facebook.com/reel/9001')
        self.entry=dict(account='fb01',target='page01',name='Example Page',type='page',url='https://www.facebook.com/profile.php?id=1001')
        self.text='Get your own copy:\nhttps://www.amazon.com/s?maas=example&ref_=aa_maas&tag=maas&me=SHOP&marketplaceID=ATVPDKIKX0DER'
        self.key='a'*64;self.record={'status':'published'}

    def tearDown(self):self.context.close();self.stack.close();self.temp.cleanup()

    def send(self):return comments.after_publication(self.page,self.context,self.entry,{},self.key,self.record,self.text,None)

    def test_exact_top_level_comment_preserves_tracking_url_and_sends_only_once(self):
        result=self.send();self.assertEqual(result['status'],'sent')
        self.assertEqual(self.page.evaluate('window.sent'),1)
        self.assertIn(self.text,self.page.get_by_role('article').text_content())
        self.assertEqual(self.send()['status'],'sent')
        self.assertEqual(self.page.evaluate('window.sent'),1)

    def test_existing_matching_own_comment_is_not_sent_again(self):
        self.page.evaluate('''({text})=>{const a=document.createElement('div');a.role='article';a.setAttribute('aria-label','Comment by Example Page');
          const author=document.createElement('a');author.href='/profile.php?id=1001';author.textContent='Example Page';a.append(author);
          const p=document.createElement('span');p.textContent=text;a.append(p);document.body.append(a)}''',dict(text=self.text))
        self.assertEqual(self.send()['status'],'already_present');self.assertIsNone(self.page.evaluate('window.sent'))

    def test_reply_composer_never_receives_or_sends_top_level_comment(self):
        self.page.locator('#compose').evaluate("e=>{e.setAttribute('role','article');e.setAttribute('aria-label','Comment by Example Viewer')}")
        result=self.send();self.assertEqual(result['status'],'manual_required')
        self.assertIsNone(self.page.evaluate('window.sent'));self.assertEqual(self.page.locator('#field').inner_text(),'')

    def test_unknown_security_modal_does_not_submit_underlying_comment(self):
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=\"alertdialog\">Confirm identity</div>')")
        self.assertEqual(self.send()['status'],'manual_required');self.assertIsNone(self.page.evaluate('window.sent'))

    def test_multiple_comment_boxes_are_not_guessed(self):
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<textarea aria-label=\"Write a comment...\"></textarea>')")
        self.assertEqual(self.send()['status'],'manual_required');self.assertIsNone(self.page.evaluate('window.sent'))

    def test_existing_sending_intent_cannot_be_reused(self):
        key=comments.hashlib.sha256((self.key+'\0'+comments.text_hash(self.text)).encode()).hexdigest()
        upload.save_json(self.root/'logs/video_comments.json',{key:dict(status='sending')})
        with self.assertRaises(RuntimeError):self.send()
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_video_not_successfully_published_cannot_comment(self):
        self.record['status']='needs_review'
        with self.assertRaises(ValueError):self.send()
        self.assertIsNone(self.page.evaluate('window.sent'))

    def test_generic_old_view_reel_link_is_not_used_to_target_another_video(self):
        self.page.goto(self.entry['url']);self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<a href=\"/reel/123\">View reel</a>')")
        with self.assertRaises(RuntimeError):comments.resolve_published_link(self.page,self.context,None)

    def test_conflicting_new_receipt_and_publish_data_links_require_manual_review(self):
        self.page.goto(self.entry['url'])
        self.page.evaluate("window.__fbUploadWatch={receiptLinks:['https://www.facebook.com/reel/123']}")
        collector=type('Collector',(),{'links':{'https://www.facebook.com/reel/456'}})()
        with self.assertRaises(RuntimeError):comments.resolve_published_link(self.page,self.context,collector)

    def test_view_reel_button_is_used_only_inside_fresh_success_area(self):
        self.page.goto(self.entry['url'])
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=\"dialog\" id=\"receipt\"><h2 id=\"message\">Preparing</h2><button onclick=\"location.href=\\\"/reel/9001\\\"\">View reel</button></div>')")
        self.page.locator('#receipt button').evaluate("e=>e.onclick=()=>location.href='/reel/9001'")
        upload.install_receipt_watch(self.page);self.page.evaluate("window.__fbUploadWatch.armed=true;document.querySelector('#message').textContent='Your reel is published.'")
        self.page.wait_for_timeout(20)
        link,method=comments.resolve_published_link(self.page,self.context,None)
        self.assertEqual(link,'https://www.facebook.com/reel/9001')
        self.assertEqual(method,'fresh_success_view_reel_button')

    def test_wrong_page_comment_actor_never_sends(self):
        with patch.object(upload,'page_actor_matches',return_value=False):
            self.assertEqual(self.send()['status'],'manual_required')
        self.assertIsNone(self.page.evaluate('window.sent'))


    def test_explicit_enter_to_post_instruction_allows_top_level_send_with_intent_guard(self):
        self.page.evaluate("""()=>{const f=document.querySelector('#field'),b=document.querySelector('#compose button');
          const send=b.onclick;b.remove();f.setAttribute('aria-description','Press Enter to post.');
          f.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();send()}})}""")
        self.assertEqual(self.send()['status'],'sent');self.assertEqual(self.page.evaluate('window.sent'),1)

    def test_missing_send_button_without_explicit_enter_instruction_does_not_send(self):
        self.page.locator('#compose button').evaluate('e=>e.remove()')
        self.assertEqual(self.send()['status'],'manual_required');self.assertIsNone(self.page.evaluate('window.sent'))

    def test_comment_as_owner_label_is_supported(self):
        self.page.locator('#field').evaluate("e=>e.setAttribute('aria-label','Write a comment as Example Page')")
        self.assertEqual(self.send()['status'],'sent')


    def test_same_video_link_and_text_under_another_job_key_is_not_sent_again(self):
        self.assertEqual(self.send()['status'],'sent')
        self.key='b'*64
        self.assertEqual(self.send()['status'],'sent')
        self.assertEqual(self.page.evaluate('window.sent'),1)

    def test_unknown_send_under_another_job_key_blocks_duplicate_on_same_video(self):
        comment_key=comments.hashlib.sha256(('b'*64+'\0'+comments.text_hash(self.text)).encode()).hexdigest()
        upload.save_json(self.root/'logs/video_comments.json',{comment_key:dict(account='fb01',target='page01',permalink=self.page.url,text_sha256=comments.text_hash(self.text),status='sending')})
        self.assertEqual(self.send()['status'],'manual_required');self.assertIsNone(self.page.evaluate('window.sent'))

    def test_reel_toolbar_comment_opens_panel_without_submitting_comment(self):
        self.page.locator('#compose').evaluate("e=>e.hidden=true")
        self.page.evaluate("""()=>{
          const toolbar=document.createElement('div');toolbar.id='toolbar';
          for(const label of ['Like','Comment','Share']){
            const button=document.createElement('button');button.textContent=label;
            if(label==='Comment')button.onclick=()=>document.querySelector('#compose').hidden=false;
            toolbar.append(button);
          }document.querySelector('main').prepend(toolbar);
        }""")
        self.assertEqual(self.send()['status'],'sent');self.assertEqual(self.page.evaluate('window.sent'),1)

    def test_scoped_post_button_can_send_but_unrelated_main_post_never_can(self):
        self.page.locator('#compose button').evaluate("e=>{e.setAttribute('aria-label','Post');e.textContent='Post'}")
        self.assertEqual(self.send()['status'],'sent');self.assertEqual(self.page.evaluate('window.sent'),1)


    def test_unrelated_main_post_button_never_submits_comment(self):
        self.page.locator('#compose button').evaluate('e=>e.remove()')
        self.page.evaluate("""()=>{const b=document.createElement('button');b.textContent='Post';
          b.onclick=()=>window.wrongPostClicked=true;document.querySelector('main').append(b)}""")
        self.assertEqual(self.send()['status'],'manual_required');self.assertIsNone(self.page.evaluate('window.wrongPostClicked'))


    def test_reload_verification_mode_does_not_mark_optimistic_dom_as_final_success(self):
        result=comments.after_publication(self.page,self.context,self.entry,{},self.key,self.record,self.text,None,require_reload_verification=True)
        self.assertEqual(result['status'],'verifying')
        with self.assertRaises(RuntimeError):self.send()
        self.assertEqual(self.page.evaluate('window.sent'),1)


class PublicVideoLinkTests(unittest.TestCase):
    def test_only_new_published_owned_video_with_exact_caption_can_supply_link(self):
        now=time.time();video=dict(__typename='Video',id='9001',owner={'id':'1001'},description={'text':'Exact caption'},creation_time=now,is_published=True)
        self.assertEqual(comments.public_nodes(video,'1001','Exact caption',now-10),['https://www.facebook.com/reel/9001'])
        for change in [dict(owner={'id':'999'}),dict(description={'text':'Other caption'}),dict(creation_time=now-3600),dict(is_published=False)]:
            self.assertEqual(comments.public_nodes(dict(video,**change),'1001','Exact caption',now-10),[])


class CommentIntentTests(VideoCommentTests):
    def test_sending_intent_is_persisted_before_click_and_unknown_result_is_not_retried(self):
        from unittest.mock import MagicMock
        control=MagicMock()
        def fail_after_intent():
            ledger=upload.read_json(self.root/'logs/video_comments.json',{})
            self.assertEqual(next(iter(ledger.values()))['status'],'sending')
            raise RuntimeError('browser disconnected during send')
        control.click.side_effect=fail_after_intent
        with patch.object(comments,'send_control',return_value=control):
            self.assertEqual(self.send()['status'],'needs_review')
            with self.assertRaises(RuntimeError):self.send()
        control.click.assert_called_once()
        self.assertIsNone(self.page.evaluate('window.sent'))
