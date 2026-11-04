import contextlib,copy,hashlib,io,os,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
import publish_fb02_nov03_20261104 as run
import add_fb_accounts as legacy
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily


class Fb02YesterdayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        for mod,key,value in [(upload,'ROOT',self.root),(upload,'CONFIG',self.root/'upload_config.json'),(legacy,'ROOT',self.root)]:self.stack.enter_context(patch.object(mod,key,value))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        clock=self.stack.enter_context(patch.object(run,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,4,4,tzinfo=timezone.utc)
        self.entries=[];jobs=[]
        for i,(account,target) in enumerate(sorted(daily.EXPECTED_PAIRS)):
            entry=dict(account=account,target=target,type='personal' if target=='personal' else 'page',name='Example '+str(i),url='https://www.facebook.com/profile.php?id='+str(1000+i),enabled=False)
            if target=='personal':entry['workflow']='personal_recording_v1'
            self.entries.append(entry);filename='2.mp4' if account=='fb02' else 'original.mp4'
            key=hashlib.sha256((account+target).encode()).hexdigest()
            if account=='fb02':
                self.entry=entry;video=upload.inbox_for(entry)/filename;video.parent.mkdir(parents=True);video.write_bytes(b'original yesterday fb02 video')
                caption=video.with_suffix('.txt');caption.write_text('Original yesterday caption')
                for file in (video,caption):os.utime(file,(time.time()-180,time.time()-180))
                key=upload.job_key(entry,video);self.video=video
            jobs.append(dict(account=account,target=target,filename=filename,key=key,url=entry['url'],entry_sha256=batch.digest(entry),caption_text='Original yesterday caption',caption_sha256=batch.file_hash(caption) if account=='fb02' else '0'*64))
        self.job=next(j for j in jobs if j['account']=='fb02')
        value=dict(payload=dict(schema=batch.SCHEMA,date='2026-11-03',ai_label=False,include_fb10_pages=True,excluded_accounts=['fb16','fb18','fb21'],comment_text=daily.COMMENT,jobs=jobs),report_format='text')
        value['sha256']=batch.digest(value['payload']);self.stack.enter_context(patch.object(run,'PREFIX',value['sha256'][:8]))
        self.path=self.root/'logs'/('frozen-material-2026-11-03-'+value['sha256'][:16]+'.json');upload.save_json(self.path,value)
        self.attempts=[dict(key=self.job['key'],action='manual_required',error='historical blocker')]
        upload.save_json(self.path.with_name(self.path.stem+'-results.json'),dict(manifest=self.path.name,attempts=self.attempts))
        upload.save_json(upload.CONFIG,dict(targets=self.entries));self.config=upload.CONFIG.read_bytes()
        self.old=dict(account='fb02',target='page01',url=self.entry['url'],video='old.mp4',status='posting',created='2026-10-31T12:00:00+08:00',post_intent_at='2026-10-31T12:05:00+08:00',error='old unknown publication')
        self.state={'old-fb02':self.old,'other-unknown':dict(account='fb03',target='personal',status='needs_review',post_intent_at='keep'),'other-published':dict(account='fb10',target='page01',status='published')}
        self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state)
        self.close=self.stack.enter_context(patch.object(run,'close_selected_window'))
        self.preflight=self.stack.enter_context(patch.object(run,'preflight'))
    def core(self,unknown=False):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock()
        patches=[patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser),patch.object(upload,'prepare_reel',return_value=(button,{})),patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',side_effect=upload.ReceiptNeedsReview('receipt timeout') if unknown else None,return_value='Your reel is published.'),patch('safe_video_comments.resolve_published_link',return_value=('https://www.facebook.com/reel/9002','fresh_success_view_reel_link')),patch.object(daily,'backfill',side_effect=AssertionError('no comments'))]
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            if unknown:
                with self.assertRaises(upload.ReceiptNeedsReview):run.execute()
            else:self.assertEqual(run.execute(),0)
        return button
    def test_real_core_pauses_only_fb02_old_task_and_publishes_exact_yesterday_video_once(self):
        button=self.core();self.assertEqual(button.click.call_count,1)
        state=upload.read_json(self.state_path,{});old=state['old-fb02']
        self.assertEqual(old['status'],'paused');self.assertEqual(old['paused_previous_status'],'posting');self.assertEqual(old['post_intent_at'],self.old['post_intent_at'])
        self.assertEqual(state['other-unknown'],self.state['other-unknown']);self.assertEqual(state['other-published'],self.state['other-published'])
        row=state[self.job['key']];self.assertEqual(row['status'],'published');self.assertTrue(row['post_intent_at']);self.assertEqual(row['comment_status'],'deferred');self.assertTrue(Path(row['archived_video']).is_file())
        self.assertEqual(upload.CONFIG.read_bytes(),self.config)
        report=upload.read_json(self.path.with_name(self.path.stem+'-results.json'),{})
        self.assertEqual(report['attempts'][0],self.attempts[0]);self.assertEqual(len(report['attempts']),2)
        with patch.object(upload,'run_entry',side_effect=AssertionError('no second Post')):self.assertEqual(run.execute(),0)
    def test_unknown_receipt_is_never_retried_and_old_pause_keeps_submission_evidence(self):
        button=self.core(True);self.assertEqual(button.click.call_count,1)
        state=upload.read_json(self.state_path,{});self.assertEqual(state[self.job['key']]['status'],'needs_review')
        with patch.object(upload,'run_entry') as post:
            with self.assertRaises(ValueError):run.execute()
        post.assert_not_called()
    def test_network_preflight_failure_keeps_old_tasks_paused_but_grants_no_post(self):
        self.preflight.side_effect=RuntimeError('net::ERR_PROXY_CONNECTION_FAILED')
        with patch.object(upload,'run_entry') as post:
            with self.assertRaises(RuntimeError):run.execute()
        post.assert_not_called();self.assertEqual(upload.read_json(self.state_path,{})['old-fb02']['status'],'paused')
        self.assertFalse((self.root/'logs'/(run.GRANT+'-claim.json')).exists())
    def test_changed_media_caption_or_source_stops_before_pausing_or_closing(self):
        self.video.with_suffix('.txt').write_text('changed caption')
        with self.assertRaises(ValueError):run.execute()
        self.close.assert_not_called();self.assertEqual(upload.read_json(self.state_path,{}),self.state)
    def test_other_recent_fb02_task_and_live_lock_are_not_cleared(self):
        changed=copy.deepcopy(self.state);changed['recent']=dict(account='fb02',target='page01',status='posting',created='2026-11-04T09:00:00+08:00')
        upload.save_json(self.state_path,changed)
        with self.assertRaises(ValueError):run.execute()
        self.assertEqual(upload.read_json(self.state_path,{}),changed);self.close.assert_not_called()
        lock=self.root/'logs/upload.lock';lock.write_text('12345')
        with self.assertRaises(RuntimeError):run.execute()
        self.assertEqual(lock.read_text(),'12345')
    def test_browser_failure_before_new_task_can_resume_without_losing_old_guard(self):
        with patch.object(upload,'run_entry',side_effect=RuntimeError('browser failed before record')):
            with self.assertRaises(RuntimeError):run.execute()
        claim=upload.read_json(self.root/'logs'/(run.GRANT+'-claim.json'),{});self.assertEqual(claim['phase'],'not_started')
        self.core()
