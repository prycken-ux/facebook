import contextlib,copy,hashlib,html,io,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
import add_fb_accounts
import fb_upload as upload
import safe_video_comments as comments
import scheduled_material_batch as batch
import comment_exact_reel_1500593451890233 as single


class ExactReelCommentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack()
        for module,name,value in [(upload,'ROOT',self.root),(upload,'CONFIG',self.root/'upload_config.json'),(add_fb_accounts,'ROOT',self.root)]:self.stack.enter_context(patch.object(module,name,value))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()));clock=self.stack.enter_context(patch.object(single,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,3,7,tzinfo=timezone.utc)
        self.stack.enter_context(patch.object(single,'close_selected_window'));self.stack.enter_context(patch.object(upload,'ensure_identity',return_value={'method':'page_actor_id_match'}));self.stack.enter_context(patch.object(upload,'recheck_publish_identity'));self.stack.enter_context(patch.object(upload,'page_actor_matches',return_value=True))
        self.stack.enter_context(patch.object(upload,'run_entry',side_effect=AssertionError('no video upload')));self.stack.enter_context(patch('published_video_lookup.find_published',side_effect=AssertionError('no timeline lookup')))
        self.entry=dict(account=single.PAIR[0],target=single.PAIR[1],type='page',name=single.NAME,url=single.OWNER,enabled=False);upload.save_json(upload.CONFIG,dict(targets=[self.entry]));self.config_before=upload.CONFIG.read_bytes()
        self.key=hashlib.sha256(b'exact-nov02-fb10-page02').hexdigest();self.job=dict(account=single.PAIR[0],target=single.PAIR[1],key=self.key,filename=single.FILENAME,url=single.OWNER)
        jobs=[self.job]+[dict(account='fb99',target=str(i),key=hashlib.sha256(str(i).encode()).hexdigest(),filename=str(i)+'.mp4',url='https://www.facebook.com/profile.php?id=9999') for i in range(29)]
        payload=dict(schema=batch.SCHEMA,date='2026-11-02',comment_text=single.daily.COMMENT,jobs=jobs);value=dict(payload=payload,sha256=batch.digest(payload),report_format='text')
        self.stack.enter_context(patch.object(single,'PREFIX',value['sha256'][:8]));self.source=self.root/'logs'/('frozen-material-2026-11-02-'+value['sha256'][:16]+'.json');upload.save_json(self.source,value);upload.save_json(self.source.with_name(self.source.stem+'-results.json'),dict(manifest=self.source.name,attempts=[]))
        self.state={self.key:dict(account=single.PAIR[0],target=single.PAIR[1],url=single.OWNER,video='E:\\original\\'+single.FILENAME,status='published',comment_status='manual_required'),'old-video':dict(account='fb06',target='page01',status='published')}
        self.path=self.root/'logs/publish_state.json';upload.save_json(self.path,self.state)
        self.old=dict(account='fb06',target='page01',status='needs_review',text_sha256=comments.text_hash(single.daily.COMMENT),permalink='https://www.facebook.com/reel/1009711495487891')
        upload.save_json(self.root/'logs/video_comments.json',{'protected-old':self.old})
        self.saved=[];self.calls=0;self.persist=True;self.owner=single.OWNER;self.visited=[]
        self.context=self.browser.new_context();self.context.expose_function('persistComment',self.save);self.context.route('https://www.facebook.com/**',self.route)
    def tearDown(self):
        try:self.context.close()
        except Exception:pass
        self.stack.close();self.temp.cleanup()
    def save(self,text):
        ledger=upload.read_json(self.root/'logs/video_comments.json',{});self.assertTrue(any(r.get('video_job')==self.key and r['status']=='sending' for r in ledger.values()));self.calls+=1
        if self.persist:self.saved.append(text)
    def route(self,r):
        self.visited.append(r.request.url)
        if urlparse(r.request.url).path.startswith('/reel/'):
            existing=''.join('<article role=article aria-label="Comment by '+single.NAME+'"><a href="'+self.owner+'">'+single.NAME+'</a><span>'+html.escape(t)+'</span></article>' for t in self.saved)
            body='''<main><a href="OWNER" aria-label="NAME, see owner profile">NAME</a>EXISTING<div><div id=field role=textbox contenteditable=true aria-label="Comment as NAME"></div><button aria-label="Post comment" onclick="send()">Post comment</button></div></main><script>async function send(){let f=document.querySelector('#field'),t=f.innerText;await window.persistComment(t);let a=document.createElement('article');a.role='article';a.setAttribute('aria-label','Comment by NAME');a.innerHTML='<a href="OWNER">NAME</a>';let s=document.createElement('span');s.textContent=t;a.append(s);document.querySelector('main').append(a);f.innerText=''}</script>'''.replace('OWNER',self.owner).replace('NAME',single.NAME).replace('EXISTING',existing)
        else:body='<h1>'+single.NAME+'</h1><article role=article><div role=status>Loading...</div></article>'
        r.fulfill(content_type='text/html',body=body)
    def run_one(self):
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=self.context):return single.execute(verify_timeout_ms=250)
    def test_exact_link_comments_despite_loading_profile_and_refreshes_before_success(self):
        self.assertEqual(self.run_one(),0);self.assertEqual(self.calls,1);self.assertEqual(self.saved,[single.daily.COMMENT])
        row=upload.read_json(self.path,{})[self.key];self.assertEqual(row['status'],'published');self.assertEqual(row['comment_status'],'sent');self.assertEqual(row['permalink'],single.LINK);self.assertEqual(row['comment_link_job_key'],self.key)
        self.assertEqual(sum(urlparse(u).path=='/profile.php' for u in self.visited),1)
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before);self.assertEqual(upload.read_json(self.path,{})['old-video'],self.state['old-video']);self.assertEqual(upload.read_json(self.root/'logs/video_comments.json',{})['protected-old'],self.old)
        with patch.object(upload,'launch_context',side_effect=AssertionError('already sent must not reopen')):self.assertEqual(single.execute(),0)
        self.assertEqual(self.calls,1)
    def test_optimistic_comment_keeps_unknown_send_protected_and_never_resends(self):
        self.persist=False;self.assertEqual(self.run_one(),3);self.assertEqual(self.calls,1)
        row=upload.read_json(self.path,{})[self.key];self.assertEqual(row['comment_status'],'needs_review');self.assertEqual(row['status'],'published')
        with patch.object(upload,'launch_context',side_effect=AssertionError('unknown must not reopen')):self.assertEqual(single.execute(),3)
        self.assertEqual(self.calls,1)
    def test_wrong_author_never_binds_or_comments(self):
        self.owner='https://www.facebook.com/profile.php?id=9999';original=comments.require_video_author
        with patch.object(comments,'require_video_author',side_effect=lambda *a,**k:original(*a,**dict(k,timeout_ms=150))):self.assertEqual(self.run_one(),3)
        self.assertEqual(self.calls,0);self.assertNotIn('permalink',upload.read_json(self.path,{})[self.key])
    def test_wrong_comment_actor_does_not_send(self):
        with patch.object(upload,'page_actor_matches',return_value=False):self.assertEqual(self.run_one(),3)
        self.assertEqual(self.calls,0)
    def test_source_or_config_mismatch_stops_before_browser(self):
        config=upload.read_json(upload.CONFIG,{});config['targets'][0]['url']='https://www.facebook.com/profile.php?id=9999';upload.save_json(upload.CONFIG,config)
        with self.assertRaises(ValueError),patch.object(upload,'launch_context',side_effect=AssertionError('wrong source must not open')):single.execute()
