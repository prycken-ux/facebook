import contextlib,copy,io,os,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import add_fb_accounts
import fb_upload as upload
import scheduled_material_batch as batch
import retry_two_confirmed_absent as retry

class TwoRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'));self.stack.enter_context(patch.object(add_fb_accounts,'ROOT',self.root));self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        specs=copy.deepcopy(retry.SPEC);self.entries=[];self.jobs=[];self.state={}
        for pair,spec in specs.items():
            entry=dict(account=pair[0],target=pair[1],name=spec['name'],url=spec['url'],type='personal' if pair[1]=='personal' else 'page',enabled=True)
            if entry['type']=='personal':entry['workflow']='personal_recording_v1'
            folder=upload.inbox_for(entry);folder.mkdir(parents=True);video=folder/spec['filename'];video.write_bytes(('original-'+pair[0]).encode());caption=video.with_suffix('.txt');caption.write_text('Original custom caption')
            for p in [video,caption]:os.utime(p,(time.time()-120,time.time()-120))
            key=upload.job_key(entry,video);spec['key']=key
            self.entries.append(entry);self.jobs.append(dict(account=pair[0],target=pair[1],filename=video.name,key=key,url=entry['url'],caption_text=caption.read_text(),caption_sha256=batch.file_hash(caption)))
            self.state[key]=dict(account=pair[0],target=pair[1],url=entry['url'],video=str(video),caption=str(caption),created='2026-10-30T09:00:00+00:00',status='needs_review',post_intent_at='old-attempt',ai_label_requested=False)
        self.stack.enter_context(patch.object(retry,'SPEC',specs))
        upload.save_json(upload.CONFIG,{'targets':self.entries});self.config_before=upload.CONFIG.read_bytes();self.state['untouched-fb14']=dict(account='fb14',target='personal',status='failed_before_post',error='old');self.state['untouched-fb17']=dict(account='fb17',target='personal',status='published',success_message='confirmed')
        self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state)
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def test_one_absence_grant_preserves_original_post_intent_and_never_touches_cancelled_accounts(self):
        job=self.jobs[0];old=copy.deepcopy(self.state[job['key']])
        with patch.object(retry,'close_selected_window'):
            entry,ready=retry.reserve(job,self.state,self.state_path)
            self.assertTrue(ready);self.assertEqual(self.state[job['key']]['verified_absent_prior_attempt'],old)
            self.assertNotIn('post_intent_at',self.state[job['key']]);self.assertEqual(self.state['untouched-fb14']['error'],'old');self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
            with self.assertRaises(ValueError):retry.reserve(job,self.state,self.state_path)
    def test_success_proof_changed_media_or_caption_and_live_tasks_block_reset(self):
        job=self.jobs[0];base=copy.deepcopy(self.state)
        for change in [dict(success_message='success'),dict(permalink='https://www.facebook.com/reel/5'),dict(status='posting')]:
            state=copy.deepcopy(base);state[job['key']].update(change)
            with self.assertRaises(ValueError):retry.validate_retry(job,state)
        state=copy.deepcopy(base);state[job['key']]['status']='published';self.assertIsNone(retry.validate_retry(job,state)[1])
        Path(base[job['key']]['caption']).write_text('Changed caption')
        with self.assertRaises(ValueError):retry.validate_retry(job,base)
    def test_only_two_exact_jobs_run_and_all_uploads_precede_their_comments(self):
        events=[]
        def run(entry,state,path,*args,**kwargs):
            events.append('upload-'+entry['account']);key=kwargs['expected_job_key'];previous=copy.deepcopy(state[key]);state[key]=dict(previous,status='published',previous_before_post_attempt=previous,comment_status='deferred');upload.save_json(path,state)
        now=datetime(2026,10,31,10,tzinfo=timezone.utc)
        with patch.object(retry,'datetime',wraps=datetime) as clock,patch.object(retry,'source_jobs',return_value=self.jobs),patch.object(retry,'close_selected_window'),patch.object(upload,'run_entry',side_effect=run),patch.object(retry.daily,'backfill',side_effect=lambda *a,**k:events.append('comments')) as comment:
            clock.now.return_value=now;self.assertEqual(retry.execute(self.root),0)
            self.assertEqual(retry.execute(self.root),0)
        self.assertEqual(events,['upload-fb10','upload-fb09','comments']);self.assertTrue(comment.call_args.kwargs['future_only']);self.assertEqual(len(comment.call_args.args[0]['payload']['jobs']),2)
        current=upload.read_json(self.state_path,{});self.assertEqual(current['untouched-fb14'],self.state['untouched-fb14']);self.assertEqual(current['untouched-fb17'],self.state['untouched-fb17'])
