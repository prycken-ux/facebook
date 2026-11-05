import contextlib,copy,io,os,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
import retry_nov04_after_local_file_fix_20261105 as run
import fb_upload as upload
import add_fb_accounts as legacy
import scheduled_material_batch as batch
import daily_publish_and_comments as daily


class RepairedNov04Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        for mod,key,val in [(upload,'ROOT',self.root),(upload,'CONFIG',self.root/'upload_config.json'),(legacy,'ROOT',self.root)]:self.stack.enter_context(patch.object(mod,key,val))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()));clock=self.stack.enter_context(patch.object(run,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,5,4,tzinfo=timezone.utc)
        self.entries=[];self.jobs=[];self.state={}
        for i,(account,target) in enumerate(sorted(daily.EXPECTED_PAIRS)):
            entry=dict(account=account,target=target,type='personal' if target=='personal' else 'page',name='Example '+str(i),url='https://www.facebook.com/profile.php?id='+str(1000+i),enabled=False)
            if target=='personal':entry['workflow']='personal_recording_v1'
            video=upload.inbox_for(entry)/'original.mp4';video.parent.mkdir(parents=True);video.write_bytes(('original-'+account+target).encode());caption=video.with_suffix('.txt');caption.write_text('Original custom caption '+str(i))
            for file in (video,caption):os.utime(file,(time.time()-180,time.time()-180))
            key=upload.job_key(entry,video);self.entries.append(entry)
            self.jobs.append(dict(account=account,target=target,url=entry['url'],filename=video.name,key=key,entry_sha256=batch.digest(entry),caption_text=caption.read_text(),caption_sha256=batch.file_hash(caption),video_size=video.stat().st_size))
            row=dict(account=account,target=target,url=entry['url'],video=str(video),caption=str(caption),created='2026-11-04T19:00:00+08:00',status='failed_before_post',uploader_version='2.47',ai_label_requested=False,error='local file selection failed')
            if account in {'fb06','fb07','fb08'}:row.update(today_first_retry_used=True,previous_before_post_attempt=copy.deepcopy(row))
            self.state[key]=row
        self.state['old-paused']=dict(account='fb02',target='page01',status='paused',post_intent_at='keep old intent')
        self.state['old-unknown']=dict(account='fb03',target='personal',url=self.entries[2]['url'],status='needs_review',post_intent_at='keep old unknown')
        # Use an unrelated account to keep the old-unknown row out of core actor comparisons.
        self.state['old-unknown']['account']='fb99'
        self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state);upload.save_json(upload.CONFIG,dict(targets=self.entries));self.config=upload.CONFIG.read_bytes()
        value=dict(payload=dict(schema=batch.SCHEMA,date='2026-11-04',ai_label=False,include_fb10_pages=True,excluded_accounts=['fb16','fb18','fb21'],comment_text=daily.COMMENT,jobs=self.jobs),report_format='text');value['sha256']=batch.digest(value['payload'])
        self.stack.enter_context(patch.object(run,'PREFIX',value['sha256'][:8]));self.path=self.root/'logs'/('frozen-material-2026-11-04-'+value['sha256'][:16]+'.json');upload.save_json(self.path,value)
        self.attempts=[dict(key=j['key'],action='manual_required',error='original selection error') for j in self.jobs]
        upload.save_json(self.path.with_name(self.path.stem+'-results.json'),dict(manifest=self.path.name,attempts=self.attempts))
        self.auto_path=self.root/'logs/automatic_before_post_retry_claims.json';upload.save_json(self.auto_path,dict(schema='automatic-before-post-retry-claims-v1',jobs={j['key']:dict(used=True) for j in self.jobs if j['account'] in {'fb06','fb07','fb08'}}));self.auto=self.auto_path.read_bytes()
        self.close=self.stack.enter_context(patch.object(run,'close_selected_window'));self.check=self.stack.enter_context(patch.object(run,'self_check'))
        self.launch=self.stack.enter_context(patch.object(run.normal,'launcher_for_jobs',return_value=MagicMock()))
    def core(self,unknown=False):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock();self.launch.return_value.return_value=browser;events=[]
        button.click.side_effect=lambda **kwargs:events.append('post')
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'prepare_reel',return_value=(button,{})),patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',side_effect=upload.ReceiptNeedsReview('unknown') if unknown else None,return_value='Your reel is published.'),patch('safe_video_comments.resolve_published_link',side_effect=lambda *a,**k:('https://www.facebook.com/reel/9001','fresh_success_view_reel_link')),patch.object(daily,'backfill',side_effect=lambda *a,**k:events.append('comments')) as comments:
            result=run.execute()
        return result,button,events,comments
    def test_all_30_real_core_retries_preserve_prior_auto_claims_and_finish_uploads_before_comments(self):
        result,button,events,comments=self.core();self.assertEqual(result,0);self.assertEqual(button.click.call_count,30)
        self.assertEqual(events,['post']*30+['comments']);self.check.assert_called_once();self.assertTrue(comments.call_args.kwargs['future_only'])
        state=upload.read_json(self.state_path,{})
        for job in self.jobs:
            row=state[job['key']];self.assertEqual(row['status'],'published');self.assertTrue(row['post_intent_at']);self.assertTrue(Path(row['archived_video']).is_file())
            self.assertEqual(row['previous_before_post_attempt']['repair_previous_attempt'],self.state[job['key']])
        self.assertEqual(state['old-paused'],self.state['old-paused']);self.assertEqual(state['old-unknown'],self.state['old-unknown'])
        self.assertEqual(self.auto_path.read_bytes(),self.auto);self.assertEqual(upload.CONFIG.read_bytes(),self.config)
        self.assertEqual(len(upload.read_json(self.path.with_name(self.path.stem+'-results.json'),{})['attempts']),60)
        with patch.object(upload,'run_entry',side_effect=AssertionError('no second post')),patch.object(daily,'backfill'):self.assertEqual(run.execute(),0)
    def test_receipt_unknown_consumes_this_repair_grant_and_is_not_retried(self):
        result,button,events,comments=self.core(True);self.assertEqual(result,3);self.assertEqual(button.click.call_count,30);comments.assert_not_called()
        with patch.object(upload,'run_entry',side_effect=AssertionError('unknown must not post')):self.assertEqual(run.execute(),3)
        self.assertTrue(all(upload.read_json(self.state_path,{})[j['key']]['status']=='needs_review' for j in self.jobs))
    def test_failed_windows_selfcheck_changes_no_state_or_claims(self):
        self.check.side_effect=RuntimeError('selfcheck failed')
        with patch.object(upload,'run_entry') as post:
            with self.assertRaises(RuntimeError):run.execute()
        post.assert_not_called();self.assertEqual(upload.read_json(self.state_path,{}),self.state)
        self.assertFalse((self.root/'logs'/(run.GRANT+'-claims.json')).exists())
    def test_post_proof_in_previous_attempt_changed_media_and_active_worker_remain_protected(self):
        job=self.jobs[0];state=copy.deepcopy(self.state);state[job['key']]['previous_before_post_attempt']=dict(post_intent_at='old submitted')
        ledger=run.claims(upload.read_json(self.path,{}))[1]
        with self.assertRaises(ValueError):run.validate(job,state,ledger)
        Path(self.state[job['key']]['caption']).write_text('Changed')
        with self.assertRaises(ValueError):run.validate(job,self.state,ledger)
        lock=self.root/'logs/upload.lock';lock.write_text('12345')
        with self.assertRaises(RuntimeError):run.execute()
        self.assertEqual(lock.read_text(),'12345')
    def test_reserved_guard_before_new_task_can_resume_and_settle_restores_old_record(self):
        path,value,jobs=run.source();ledger_path,ledger=run.claims(value);job=jobs[0];state=copy.deepcopy(self.state)
        entry,replacement=run.reserve(job,state,ledger_path,ledger)
        self.assertEqual(run.validate(job,state,ledger)[1],'ready')
        run.settle(job,replacement,ledger_path,ledger)
        self.assertEqual(upload.read_json(self.state_path,{})[job['key']],self.state[job['key']])
        self.assertEqual(ledger['jobs'][job['key']]['phase'],'not_started')
    def test_source_tamper_does_not_reach_selfcheck_or_post(self):
        value=upload.read_json(self.path,{});value['payload']['date']='2026-11-05';upload.save_json(self.path,value)
        with self.assertRaises(ValueError):run.execute()
        self.check.assert_not_called();self.assertEqual(upload.read_json(self.state_path,{}),self.state)
