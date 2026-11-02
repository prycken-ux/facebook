import contextlib,copy,io,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import add_fb_accounts
import fb_upload as upload
import scheduled_material_batch as batch
import retry_oct31_failed_thirteen as retry

class ThirteenRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'));self.stack.enter_context(patch.object(add_fb_accounts,'ROOT',self.root));self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        specs=copy.deepcopy(retry.SPEC);self.jobs=[];self.entries=[];self.state={}
        for pair,spec in specs.items():
            entry=dict(account=pair[0],target=pair[1],name='Example '+pair[0],url='https://www.facebook.com/profile.php?id='+str(1000+len(self.jobs)),type='personal' if pair[1]=='personal' else 'page',enabled=True)
            if entry['type']=='personal':entry['workflow']='personal_recording_v1'
            video=upload.inbox_for(entry)/spec['filename'];video.parent.mkdir(parents=True);video.write_bytes(('original '+pair[0]).encode());caption=video.with_suffix('.txt');caption.write_text('Original custom caption '+pair[0])
            for file in [video,caption]:os.utime(file,(time.time()-120,time.time()-120))
            key=upload.job_key(entry,video);spec['key']=key
            job=dict(account=pair[0],target=pair[1],key=key,filename=video.name,url=entry['url'],caption_text=caption.read_text(),caption_sha256=batch.file_hash(caption))
            self.entries.append(entry);self.jobs.append(job)
            if spec['original_status']=='failed_before_post':self.state[key]=dict(account=pair[0],target=pair[1],url=entry['url'],video=str(video),caption=str(caption),created='2026-10-31T09:00:00+00:00',status='failed_before_post',ai_label_requested=False,uploader_version='2.44',today_first_retry_used=True,error='old before Post')
        self.stack.enter_context(patch.object(retry,'SPEC',specs));upload.save_json(upload.CONFIG,{'targets':self.entries});self.config_before=upload.CONFIG.read_bytes()
        # These represent protected successful and unknown submissions outside the 13.
        self.state['protected-success']=dict(account='fb01',target='page01',status='published',success_message='success')
        self.state['protected-unknown']=dict(account='fb14',target='personal',status='needs_review',post_intent_at='unknown')
        self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state)
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def test_scope_and_source_status_counts_are_exactly_eleven_failures_and_two_not_started(self):
        self.assertEqual(len(retry.SPEC),13);self.assertEqual(sum(s['original_status']=='not_started' for s in retry.SPEC.values()),2)
        self.assertFalse(any(pair[0] in {'fb16','fb18','fb21'} for pair in retry.SPEC))
    def test_missing_record_allowed_only_for_two_not_started_and_exact_files_and_captions_required(self):
        new=self.jobs[0];entry,old,action=retry.validate_retry(new,self.state);self.assertIsNone(old);self.assertEqual(action,'ready')
        failed=self.jobs[2];del self.state[failed['key']]
        with self.assertRaises(ValueError):retry.validate_retry(failed,self.state)
        Path(upload.inbox_for(entry)/new['filename']).with_suffix('.txt').write_text('new caption')
        with self.assertRaises(ValueError):retry.validate_retry(new,self.state)
    def test_current_submission_or_success_proof_cannot_be_reset(self):
        job=self.jobs[2]
        for change in [dict(status='needs_review'),dict(status='posting'),dict(post_intent_at='intent'),dict(success_message='receipt'),dict(permalink='https://www.facebook.com/reel/999')]:
            state=copy.deepcopy(self.state);state[job['key']].update(change)
            with self.assertRaises(ValueError):retry.validate_retry(job,state)
        state=copy.deepcopy(self.state);state[job['key']]['status']='published';self.assertEqual(retry.validate_retry(job,state)[2],'already_published')
    def test_old_preparation_without_intent_may_be_retired_but_unknown_post_is_preserved(self):
        job=self.jobs[0];prior=dict(account=job['account'],target='old',status='preparing',uploader_version='2.44',created='2026-10-30T00:00:00+00:00')
        self.state['old-preparation']=copy.deepcopy(prior);upload.save_json(self.state_path,self.state)
        with patch.object(retry,'close_selected_window'):
            retry.reserve(job,self.state,self.state_path)
            self.assertEqual(self.state['old-preparation']['status'],'failed_before_post');self.assertEqual(self.state['old-preparation']['abandoned_preparation_prior_record'],prior)
            with self.assertRaises(ValueError):retry.reserve(job,self.state,self.state_path)
        state=copy.deepcopy(self.state);state['old-preparation'].update(status='posting',post_intent_at='unknown')
        with self.assertRaises(ValueError):retry.abandoned_preparations(job['account'],job['key'],state)
    def test_exact_thirteen_uploads_then_only_their_comments_no_tables_or_duplicate_run(self):
        events=[];original=copy.deepcopy(self.state)
        def run(entry,state,path,*args,**kwargs):
            events.append(entry['account']);key=kwargs['expected_job_key'];state[key]=dict(state.get(key,{}),status='published',account=entry['account'],target=entry['target'],comment_status='deferred');upload.save_json(path,state)
        with patch.object(retry,'source_jobs',return_value=self.jobs),patch.object(retry,'close_selected_window'),patch.object(upload,'run_entry',side_effect=run),patch.object(retry.daily,'backfill',side_effect=lambda *a,**k:events.append('comments')) as comment:
            self.assertEqual(retry.execute(self.root),0);self.assertEqual(retry.execute(self.root),0)
        self.assertEqual(len(events),14);self.assertEqual(events[-1],'comments');self.assertEqual(len(comment.call_args.args[0]['payload']['jobs']),13)
        self.assertTrue(comment.call_args.kwargs['future_only']);self.assertIn('reporter',comment.call_args.kwargs)
        current=upload.read_json(self.state_path,{});self.assertEqual(current['protected-success'],original['protected-success']);self.assertEqual(current['protected-unknown'],original['protected-unknown'])
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before);self.assertFalse(list(self.root.rglob('*.csv')))
        self.assertTrue(list(self.root.glob('*.txt')))
