import contextlib,copy,io,os,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
import add_fb_accounts
import fb_upload as upload
import scheduled_material_batch as batch
import retry_nov02_six_20261103 as retry


class SixRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack()
        for module,name,value in [(upload,'ROOT',self.root),(upload,'CONFIG',self.root/'upload_config.json'),(add_fb_accounts,'ROOT',self.root)]:
            self.stack.enter_context(patch.object(module,name,value))
        self.output=self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        clock=self.stack.enter_context(patch.object(retry,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,3,3,tzinfo=timezone.utc)
        self.entries=[];self.jobs=[];self.state={};spec={}
        for i,(pair,(_,filename)) in enumerate(retry.SPEC.items()):
            entry=dict(account=pair[0],target=pair[1],type='personal' if pair[1]=='personal' else 'page',name='Example '+str(i),url='https://www.facebook.com/profile.php?id='+str(1001+i),enabled=False)
            if entry['type']=='personal':entry['workflow']='personal_recording_v1'
            video=upload.inbox_for(entry)/filename;video.parent.mkdir(parents=True);video.write_bytes(('original video '+str(i)).encode());caption=video.with_suffix('.txt');caption.write_text('Exact original caption '+str(i))
            for f in (video,caption):os.utime(f,(time.time()-180,time.time()-180))
            key=upload.job_key(entry,video);spec[pair]=(key[:12],filename)
            job=dict(account=pair[0],target=pair[1],filename=filename,key=key,url=entry['url'],entry_sha256=batch.digest(entry),caption_text=caption.read_text(),caption_sha256=batch.file_hash(caption),video_size=video.stat().st_size)
            self.jobs.append(job);self.entries.append(entry)
            self.state[key]=dict(account=pair[0],target=pair[1],url=entry['url'],video=str(video),caption=str(caption),created='2026-11-02T10:00:00+08:00',status='failed_before_post',ai_label_requested=False,uploader_version='2.47',error='original before-Post failure')
        self.stack.enter_context(patch.object(retry,'SPEC',spec))
        self.state['protected-fb07']=dict(account='fb07',target='personal',status='needs_review',post_intent_at='existing intent',today_first_retry_used=True)
        self.state['protected-success']=dict(account='fb09',target='personal',status='published',comment_status='manual_required')
        self.state['protected-unknown']=dict(account='fb08',target='personal',status='needs_review',post_intent_at='existing intent')
        self.state['protected-notstarted-blocker']=dict(account='fb02',target='page01',status='posting',post_intent_at='old unresolved submission')
        payload=dict(schema=batch.SCHEMA,date='2026-11-02',ai_label=False,include_fb10_pages=True,excluded_accounts=['fb16','fb18','fb21'],comment_text=retry.daily.COMMENT,jobs=self.jobs+[dict(account='extra',target=str(i),key='x'+str(i)) for i in range(24)])
        value=dict(payload=payload,sha256=batch.digest(payload));self.stack.enter_context(patch.object(retry,'PREFIX',value['sha256'][:8]))
        self.path=self.root/'logs'/('frozen-material-2026-11-02-'+value['sha256'][:16]+'.json');upload.save_json(self.path,value)
        upload.save_json(self.path.with_name(self.path.stem+'-results.json'),dict(manifest=self.path.name,rows=[dict(j,video_status='failed_before_post') for j in self.jobs]))
        upload.save_json(upload.CONFIG,dict(targets=self.entries));self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state)
        self.original=copy.deepcopy(self.state);self.config_before=upload.CONFIG.read_bytes()
    def tearDown(self):self.stack.close();self.temp.cleanup()

    def test_source_exact_six_and_report_checksum_scope_are_required(self):
        path,value,jobs=retry.load_source();self.assertEqual(len(jobs),6);self.assertEqual({(j['account'],j['target']) for j in jobs},set(retry.SPEC))
        self.assertNotIn(('fb07','personal'),retry.SPEC);self.assertNotIn(('fb02','page01'),retry.SPEC)
        report=upload.read_json(path.with_name(path.stem+'-results.json'),{});report['rows'][0]['video_status']='needs_review';upload.save_json(path.with_name(path.stem+'-results.json'),report)
        with self.assertRaises(ValueError):retry.load_source()

    def test_all_submit_success_retry_or_active_account_proof_blocks_before_claim(self):
        job=self.jobs[0]
        for changes in [dict(status='needs_review'),dict(status='posting'),dict(post_intent_at='intent'),dict(permalink='https://www.facebook.com/reel/1'),dict(success_message='receipt'),dict(today_first_retry_used=True),dict(ai_label_requested=True)]:
            state=copy.deepcopy(self.state);state[job['key']].update(changes)
            with self.assertRaises(ValueError):retry.validate(job,state)
        state=copy.deepcopy(self.state);state['active']=dict(account=job['account'],status='preparing')
        with self.assertRaises(ValueError):retry.validate(job,state)
        upload.save_json(self.root/'logs/automatic_before_post_retry_claims.json',dict(schema='automatic-before-post-retry-claims-v1',jobs={job['key']:{}}))
        with self.assertRaises(ValueError):retry.validate(job,self.state)
        self.assertFalse((self.root/'logs'/(retry.GRANT+'-claims.json')).exists())

    def test_changed_video_caption_and_config_are_not_replaced(self):
        job=self.jobs[0];entry=self.entries[0];video=upload.inbox_for(entry)/job['filename'];caption=video.with_suffix('.txt')
        for file in (video,caption,upload.CONFIG):
            original=file.read_bytes();file.write_bytes(b'changed')
            with self.assertRaises((ValueError,KeyError)):retry.validate(job,self.state)
            file.write_bytes(original)

    def test_claim_is_durable_before_preflight_failure_and_no_upload_or_other_state_change(self):
        def close(account):
            claims=upload.read_json(self.root/'logs'/(retry.GRANT+'-claims.json'),{})
            self.assertTrue(any(c['account']==account for c in claims['jobs'].values()))
        with patch.object(retry,'close_selected_window',side_effect=close),patch.object(retry,'preflight',side_effect=RuntimeError('proxy still unavailable')),patch.object(upload,'run_entry') as send:
            self.assertEqual(retry.execute(),3);self.assertEqual(retry.execute(),3)
        send.assert_not_called();self.assertEqual(upload.read_json(self.state_path,{}),self.original)
        self.assertEqual(len(retry.claims_document()[1]['jobs']),6)
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)

    def test_real_core_intent_archive_and_one_retry_only_for_the_six_exact_jobs(self):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock()
        with patch.object(retry,'close_selected_window'),patch.object(retry,'preflight'),patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser),patch.object(upload,'prepare_reel',return_value=(button,{})),patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',return_value='Your reel is published.'),patch('safe_video_comments.resolve_published_link',side_effect=[('https://www.facebook.com/reel/'+str(9000+i),'fresh_success_view_reel_link') for i in range(6)]),patch.object(retry.daily,'backfill') as comment:
            self.assertEqual(retry.execute(),0);self.assertEqual(button.click.call_count,6);self.assertEqual(retry.execute(),0)
        self.assertEqual(button.click.call_count,6);self.assertEqual(comment.call_count,1)
        self.assertEqual(comment.call_args.kwargs['only_keys'],{j['key'] for j in self.jobs});self.assertTrue(comment.call_args.kwargs['future_only'])
        state=upload.read_json(self.state_path,{})
        for job in self.jobs:
            row=state[job['key']];self.assertEqual(row['status'],'published');self.assertTrue(row['post_intent_at']);self.assertTrue(row['today_first_retry_used']);self.assertTrue(Path(row['archived_video']).is_file())
        for key,row in self.original.items():
            if key.startswith('protected'):self.assertEqual(state[key],row)
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before);self.assertFalse(list(self.root.rglob('*.csv')))

    def test_post_timeout_is_kept_unknown_and_never_submitted_again(self):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock()
        with patch.object(retry,'close_selected_window'),patch.object(retry,'preflight'),patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser),patch.object(upload,'prepare_reel',return_value=(button,{})),patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',side_effect=RuntimeError('receipt timed out')),patch.object(retry.daily,'backfill') as comment:
            self.assertEqual(retry.execute(),3);self.assertEqual(retry.execute(),3)
        self.assertEqual(button.click.call_count,6);comment.assert_not_called()
        state=upload.read_json(self.state_path,{})
        self.assertTrue(all(state[j['key']]['status']=='needs_review' for j in self.jobs))

    def test_proxy_preflight_retries_only_read_navigation_and_never_changes_proxy(self):
        browser=MagicMock();page=browser.new_page.return_value
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser),patch.object(upload,'navigate_profile',side_effect=RuntimeError('net::ERR_PROXY_CONNECTION_FAILED')) as navigate,patch.object(upload,'checkpoint'),patch.object(upload,'ensure_identity') as identity:
            with self.assertRaises(RuntimeError):retry.preflight(self.entries[0])
        self.assertEqual(navigate.call_count,2);identity.assert_not_called();page.wait_for_timeout.assert_called_once_with(2000);browser.close.assert_called_once()
