import contextlib,copy,io,os,tempfile,time,unittest,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import add_fb_accounts
import fb_upload as upload
import scheduled_material_batch as batch
import automatic_batch_retry as retry

class AutomaticRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'));self.stack.enter_context(patch.object(add_fb_accounts,'ROOT',self.root));self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.now=datetime.now(timezone.utc);self.jobs=[];self.entries=[];self.state={};self.attempts=[]
        cases=[('failed_before_post','net::ERR_CONNECTION_RESET'),('published',''),('needs_review','receipt timeout'),('failed_before_post','遇到安全验证 captcha'),(None,'fb05 的 Chrome 资料仍被占用'),('failed_before_post','unrecognized failure')]
        for i,(status,error) in enumerate(cases,1):
            entry=dict(account=f'fb{i:02}',target='page01',name=f'Example {i}',url='https://www.facebook.com/profile.php?id='+str(1000+i),type='page',enabled=False)
            video=upload.inbox_for(entry)/'original.mp4';video.parent.mkdir(parents=True);video.write_bytes(('video '+str(i)).encode());caption=video.with_suffix('.txt');caption.write_text('Exact custom caption '+str(i))
            for file in [video,caption]:os.utime(file,(time.time()-180,time.time()-180))
            key=upload.job_key(entry,video);job=dict(account=entry['account'],target=entry['target'],filename=video.name,key=key,url=entry['url'],entry_sha256=batch.digest(entry),caption_text=caption.read_text(),caption_sha256=batch.file_hash(caption),video_size=video.stat().st_size)
            self.jobs.append(job);self.entries.append(entry)
            self.attempts.append(dict(account=entry['account'],target=entry['target'],key=key,action='finished' if status=='published' else 'manual_required',error=error,started_at=(self.now-timedelta(seconds=5)).isoformat()))
            if status:
                self.state[key]=dict(account=entry['account'],target=entry['target'],url=entry['url'],video=str(video),caption=str(caption),created=(self.now-timedelta(seconds=4)).isoformat(),status=status,uploader_version='2.46',ai_label_requested=False,error=error,failure_stage='open_target_profile')
                if status=='published':self.state[key].update(permalink='https://www.facebook.com/reel/9002',comment_status='sent')
                if status=='needs_review':self.state[key]['post_intent_at']=self.now.isoformat()
        upload.save_json(upload.CONFIG,{'targets':self.entries});self.config_before=upload.CONFIG.read_bytes()
        self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state)
        payload=dict(schema=batch.SCHEMA,date=self.now.astimezone(batch.BJ).date().isoformat(),start=(self.now-timedelta(seconds=1)).isoformat(),ai_label=False,include_fb10_pages=True,excluded_accounts=['fb16','fb18','fb21'],jobs=self.jobs,comment_text='Get your own copy:\nhttps://www.amazon.com/s?tag=maas')
        self.value=dict(payload=payload,sha256=batch.digest(payload),created_at=(self.now-timedelta(seconds=10)).isoformat(),workflow='future-video-comments-v1',auto_retry_policy=retry.POLICY,report_format='text',issues=[])
        self.path=self.root/'logs'/('frozen-material-'+payload['date']+'-'+self.value['sha256'][:16]+'.json');upload.save_json(self.path,self.value)
        self.report_path=self.path.with_name(self.path.stem+'-results.json');upload.save_json(self.report_path,dict(manifest=self.path.name,attempts=self.attempts))
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def test_only_two_recoverable_failures_reenter_once_and_unknown_success_security_stay_untouched(self):
        calls=[];original=copy.deepcopy(self.state)
        def publish(entry,state,path,*args,**kwargs):
            key=kwargs['expected_job_key'];claims=upload.read_json(self.root/'logs/automatic_before_post_retry_claims.json',{})
            self.assertIn(key,claims['jobs']);calls.append(key)
            state[key]=dict(state.get(key,{}),account=entry['account'],target=entry['target'],status='published' if key==self.jobs[0]['key'] else 'failed_before_post',error='net::ERR_CONNECTION_RESET',uploader_version='2.46',ai_label_requested=False,created=datetime.now(timezone.utc).isoformat())
            upload.save_json(path,state)
        with patch.object(batch,'close_selected_window'),patch.object(upload,'run_entry',side_effect=publish):
            selected=retry.run(self.path);self.assertEqual({j['key'] for j in selected},{self.jobs[0]['key'],self.jobs[4]['key']})
            self.assertEqual(retry.run(self.path),[])
        self.assertEqual(len(calls),2)
        current=upload.read_json(self.state_path,{})
        for job in [self.jobs[1],self.jobs[2],self.jobs[3],self.jobs[5]]:self.assertEqual(current[job['key']],original[job['key']])
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before);self.assertFalse(list(self.root.rglob('*.csv')))
        report=upload.read_json(self.report_path,{});self.assertEqual(len(report['attempts']),8)
        self.assertEqual(next(r for r in report['rows'] if r['key']==self.jobs[0]['key'])['reason'],'')
    def test_real_core_post_intent_and_archive_are_used_for_only_the_retry_targets(self):
        from unittest.mock import MagicMock
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock()
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser),patch.object(upload,'prepare_reel',return_value=(button,{})),patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',return_value='Your reel is published.'),patch('safe_video_comments.resolve_published_link',side_effect=[('https://www.facebook.com/reel/9011','fresh_success_view_reel_link'),('https://www.facebook.com/reel/9055','fresh_success_view_reel_link')]),patch.object(batch,'close_selected_window'):
            retry.run(self.path)
        self.assertEqual(button.click.call_count,2)
        current=upload.read_json(self.state_path,{})
        self.assertTrue(current[self.jobs[0]['key']]['today_first_retry_used'])
        self.assertEqual(current[self.jobs[0]['key']]['previous_before_post_attempt']['status'],'failed_before_post')
        for job in [self.jobs[0],self.jobs[4]]:
            row=current[job['key']];self.assertEqual(row['status'],'published');self.assertTrue(row['post_intent_at']);self.assertTrue(Path(row['archived_video']).is_file())
            self.assertEqual(row['automatic_retry'],dict(source_manifest=self.path.name,source_sha256=self.value['sha256'],retry_number=1))
        text=self.path.with_name(self.path.stem+'-results.txt').read_text(encoding='utf-8-sig')
        self.assertIn('\n发布成功：',text);self.assertNotIn('\\n',text)
    def test_incomplete_first_pass_does_not_begin_retry_queue(self):
        upload.save_json(self.report_path,dict(manifest=self.path.name,attempts=self.attempts[:-1]))
        with self.assertRaises(ValueError):retry.run(self.path)
        self.assertFalse((self.root/'logs/automatic_before_post_retry_claims.json').exists())

    def test_claim_is_durable_even_when_browser_close_fails_before_upload(self):
        with patch.object(batch,'close_selected_window',side_effect=RuntimeError('profile still busy')),patch.object(upload,'run_entry') as post:
            retry.run(self.path);self.assertEqual(retry.run(self.path),[])
        post.assert_not_called();self.assertEqual(len(upload.read_json(self.root/'logs/automatic_before_post_retry_claims.json',{})['jobs']),2)
    def test_current_post_intent_or_success_proof_and_same_account_inflight_job_block_retry(self):
        job=self.jobs[0];attempt=self.attempts[0];claims={'schema':retry.CLAIMS_SCHEMA,'jobs':{}}
        for change in [dict(post_intent_at='intent'),dict(permalink='https://www.facebook.com/reel/1'),dict(status='needs_review'),dict(status='posting'),dict(status='published'),dict(today_first_retry_used=True)]:
            state=copy.deepcopy(self.state);state[job['key']].update(change)
            self.assertFalse(retry.decide(job,self.value,state,attempt,claims)[0])
        state=copy.deepcopy(self.state);state['another']=dict(account=job['account'],status='posting')
        self.assertFalse(retry.decide(job,self.value,state,attempt,claims)[0])
    def test_changed_video_caption_or_config_are_not_replaced_or_retried(self):
        for mode in ['video','caption','config']:
            job=self.jobs[0];entry=self.entries[0];video=upload.inbox_for(entry)/job['filename'];caption=video.with_suffix('.txt');before_video=video.read_bytes();before_caption=caption.read_bytes()
            if mode=='video':video.write_bytes(b'replaced media')
            if mode=='caption':caption.write_text('replaced caption')
            if mode=='config':upload.save_json(upload.CONFIG,{'targets':[dict(e,name='Changed') if e==entry else e for e in self.entries]})
            with self.assertRaises(ValueError):retry.checked_job(job)
            video.write_bytes(before_video);caption.write_bytes(before_caption);upload.CONFIG.write_bytes(self.config_before)
    def test_old_disabled_or_corrupt_batches_and_corrupt_claims_do_not_grant_retries(self):
        for modification in ['policy','checksum','yesterday']:
            value=copy.deepcopy(self.value)
            if modification=='policy':value.pop('auto_retry_policy')
            elif modification=='checksum':value['sha256']='0'*64
            else:value['payload']['date']='2026-10-31'
            upload.save_json(self.path,value)
            with self.assertRaises(ValueError):retry.load_source(self.path)
        upload.save_json(self.path,self.value);upload.save_json(self.root/'logs/automatic_before_post_retry_claims.json',{'schema':'unknown','jobs':{}})
        with self.assertRaises(ValueError):retry.run(self.path)
    def test_failure_outside_this_batch_or_already_claimed_under_another_batch_is_not_eligible(self):
        job=self.jobs[0];claims={'schema':retry.CLAIMS_SCHEMA,'jobs':{}}
        stale=dict(self.attempts[0],started_at=(self.now-timedelta(days=2)).isoformat())
        self.assertFalse(retry.decide(job,self.value,self.state,stale,claims)[0])
        claims['jobs'][job['key']]={'source_sha256':'another-batch'}
        self.assertFalse(retry.decide(job,self.value,self.state,self.attempts[0],claims)[0])
    def test_security_and_validation_errors_never_become_retry_candidates(self):
        job=self.jobs[0];claims={'schema':retry.CLAIMS_SCHEMA,'jobs':{}}
        for error in ['net::ERR_CONNECTION_RESET 登录验证','Advanced Protection','captcha','文案变化 net::ERR_TIMED_OUT','Reel 入口不唯一','原视频内容变化','operation temporarily restricted account']:
            state=copy.deepcopy(self.state);state[job['key']]['error']=error
            self.assertFalse(retry.decide(job,self.value,state,self.attempts[0],claims)[0])
