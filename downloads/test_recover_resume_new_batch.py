import contextlib,copy,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import add_fb_accounts
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import publish_new_with_comments as fresh
import recover_resume_new_batch as recover

class LockRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack();self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def run_recovery(self,probe):return recover.recover_locks(self.root,probe=probe,mutex=contextlib.nullcontext())
    def test_both_confirmed_dead_pid_locks_are_preserved_in_backup_without_touching_state(self):
        for name,pid in [('batch.lock','123'),('upload.lock','456')]: (self.root/'logs'/name).write_text(pid)
        state=self.root/'logs/publish_state.json';state.write_text('{"unchanged":"original"}');before=state.read_bytes()
        backup=self.run_recovery(lambda pid:False)
        for name,pid in [('batch.lock','123'),('upload.lock','456')]:self.assertFalse((self.root/'logs'/name).exists());self.assertEqual((backup/name).read_text(),pid)
        self.assertEqual(state.read_bytes(),before)
    def test_live_second_owner_or_unknown_pid_stops_before_moving_any_lock(self):
        for unknown in [False,True]:
            (self.root/'logs/batch.lock').write_text('123');(self.root/'logs/upload.lock').write_text('456')
            def probe(pid):
                if pid==456 and unknown:raise PermissionError('cannot query')
                return pid==456
            with self.assertRaises((RuntimeError,PermissionError)):self.run_recovery(probe)
            self.assertTrue((self.root/'logs/batch.lock').exists());self.assertTrue((self.root/'logs/upload.lock').exists());self.assertFalse((self.root/'backups').exists())
    def test_malformed_lock_is_never_deleted_and_no_lock_is_a_noop(self):
        self.assertIsNone(self.run_recovery(lambda pid:False))
        for blob in [b'',b'old worker',b'0',b'4294967296']:
            file=self.root/'logs/batch.lock';file.write_bytes(blob)
            with self.assertRaises(ValueError):self.run_recovery(lambda pid:False)
            self.assertEqual(file.read_bytes(),blob)
    def test_owner_becomes_live_before_move_so_lock_is_retained(self):
        file=self.root/'logs/batch.lock';file.write_text('123');calls=[]
        def probe(pid):calls.append(pid);return len(calls)>1
        with self.assertRaises(RuntimeError):self.run_recovery(probe)
        self.assertEqual(file.read_text(),'123')

class CurrentResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(add_fb_accounts,'ROOT',self.root));self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.jobs=[];self.state={}
        for i,status in enumerate(['published','posting','preparing','failed_before_post','missing'],1):
            key=str(i)*64;name=f'{i}.mp4';job=dict(key=key,filename=name,account='fb10',target=f'page{i:02}',url='https://www.facebook.com/profile.php?id='+str(1000+i),caption_text='Original caption')
            self.jobs.append(job)
            if status!='missing':
                row=dict(status=status,created='2026-10-31T10:00:01+00:00',account=job['account'],target=job['target'],url=job['url'],video='E:\\FB-AutoUpload\\videos\\'+name,caption=name+'.txt')
                if status=='posting':row['post_intent_at']='2026-10-31T10:00:10+00:00'
                if status=='published':row.update(permalink='https://www.facebook.com/reel/9001',success_message='success',comment_status='sent')
                self.state[key]=row
        self.state['unrelated-old']=dict(status='preparing',account='fb14',target='personal',created='2026-10-29T10:00:00+00:00')
        self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state)
        payload=dict(schema=batch.SCHEMA,date='2026-10-31',start='2026-10-31T10:00:00+00:00',jobs=self.jobs,ai_label=False,include_fb10_pages=True,excluded_accounts=['fb16','fb18','fb21'],comment_text=daily.COMMENT)
        self.value=dict(payload=payload,sha256=batch.digest(payload),created_at='2026-10-31T10:00:00+00:00',workflow='future-video-comments-v1')
        self.path=self.root/'logs'/('frozen-material-2026-10-31-'+self.value['sha256'][:16]+'.json');upload.save_json(self.path,self.value)
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def test_only_never_started_and_interrupted_before_intent_jobs_resume(self):
        source_before=self.path.read_bytes();view_path=recover.prepare_resume(self.root,self.path,self.value);view=upload.read_json(view_path,{})
        self.assertEqual({j['key'] for j in view['payload']['jobs']},{self.jobs[2]['key'],self.jobs[4]['key']})
        current=upload.read_json(self.state_path,{})
        self.assertEqual(current[self.jobs[0]['key']],self.state[self.jobs[0]['key']]);self.assertEqual(current['unrelated-old'],self.state['unrelated-old'])
        self.assertEqual(current[self.jobs[1]['key']]['status'],'posting');self.assertEqual(current[self.jobs[2]['key']]['status'],'failed_before_post')
        self.assertEqual(self.path.read_bytes(),source_before)
        # A retry that actually started is never granted twice, even before Post.
        current[self.jobs[2]['key']]['today_first_retry_used']=True;upload.save_json(self.state_path,current)
        again=upload.read_json(recover.prepare_resume(self.root,self.path,self.value),{})
        self.assertEqual([j['key'] for j in again['payload']['jobs']],[self.jobs[4]['key']])
    def test_unsubmitted_grant_survives_stop_before_browser_launch_without_resetting_known_failure(self):
        first=recover.prepare_resume(self.root,self.path,self.value)
        again=recover.prepare_resume(self.root,self.path,self.value)
        self.assertEqual(first,again)
        self.assertEqual(upload.read_json(self.state_path,{})[self.jobs[3]['key']],self.state[self.jobs[3]['key']])
    def test_unique_current_manifest_only_old_retry_files_are_not_selected(self):
        upload.save_json(self.root/'logs/retry-oct30-eight-authorized-20261031.json',self.value)
        self.assertEqual(recover.choose_manifest(self.root,'2026-10-31')[0],self.path)
        changed=copy.deepcopy(self.value);changed['payload']['start']='2026-10-31T10:00:02+00:00';changed['sha256']=batch.digest(changed['payload'])
        upload.save_json(self.root/'logs'/('frozen-material-2026-10-31-'+changed['sha256'][:16]+'.json'),changed)
        with self.assertRaises(ValueError):recover.choose_manifest(self.root,'2026-10-31')
    def test_existing_batch_is_resumed_before_its_comments_without_freezing_new_files(self):
        events=[]
        with patch.object(fresh,'execute',side_effect=AssertionError('no rescan')),patch.object(batch,'run',side_effect=lambda *a,**k:events.append('resume-uploads')) as run,patch.object(daily,'backfill',side_effect=lambda *a,**k:events.append('current-comments')) as comment,patch.object(batch,'results',return_value=[]):
            self.assertEqual(recover.resume(self.root,'2026-10-31'),0)
        self.assertEqual(events,['resume-uploads','current-comments']);self.assertTrue(run.call_args.kwargs['retry_before_post']);self.assertTrue(comment.call_args.kwargs['future_only']);self.assertEqual(comment.call_args.args[0],self.value)
    def test_unknown_post_intent_keeps_its_account_browser_open_and_blocks_other_page_uploads(self):
        view=recover.prepare_resume(self.root,self.path,self.value)
        with patch.object(batch,'close_selected_window') as close,patch.object(upload,'run_entry') as publish:
            self.assertEqual(batch.run(view,self.root,defer_comments=True,retry_before_post=True),3)
        close.assert_not_called();publish.assert_not_called()
        self.assertEqual(upload.read_json(self.state_path,{})[self.jobs[1]['key']]['status'],'posting')

    def test_no_current_batch_starts_fresh_only_after_verified_lock_recovery(self):
        self.path.unlink()
        with patch.object(fresh,'execute',return_value=0) as start:
            self.assertEqual(recover.resume(self.root,'2026-10-31'),0)
        start.assert_called_once_with('2026-10-31',True,None)
