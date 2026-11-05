import contextlib,copy,io,unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch
import continue_nov04_comments_automatic_20261105 as run
import test_retry_nov04_after_local_file_fix_20261105 as fixture
import fb_upload as upload
import daily_publish_and_comments as daily
import safe_video_comments as comments


class CommentContinuationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.RepairedNov04Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        clock=self.stack.enter_context(patch.object(run,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,5,4,tzinfo=timezone.utc)
        self.state=copy.deepcopy(self.f.state)
        for i,job in enumerate(self.f.jobs):
            self.state[job['key']]['status']='published' if i<15 else 'failed_before_post' if i<17 else 'needs_review'
            if i<15:self.state[job['key']].update(published_at='2026-11-05T10:00:00+08:00',comment_status='manual_required')
        upload.save_json(self.f.state_path,self.state)
        self.stack.enter_context(patch.object(upload,'run_entry',side_effect=AssertionError('comments must never upload')))
        self.stack.enter_context(patch('builtins.input',side_effect=AssertionError('must not prompt')))
    def assert_preserved(self):
        state=upload.read_json(self.f.state_path,{})
        for key,row in self.state.items():
            self.assertEqual({k:v for k,v in state[key].items() if not k.startswith('comment_') and k!='permalink'},
                             {k:v for k,v in row.items() if not k.startswith('comment_') and k!='permalink'})
        self.assertEqual(upload.CONFIG.read_bytes(),self.f.config);self.assertEqual(self.f.auto_path.read_bytes(),self.f.auto)
        report=upload.read_json(self.f.path.with_name(self.f.path.stem+'-results.json'),{})
        self.assertEqual(report['attempts'],self.f.attempts)
    def test_fifteen_successes_only_keep_video_status_and_all_retry_claims(self):
        def backfill(work,output_dir,**kwargs):
            self.assertEqual(len(work['payload']['jobs']),15);self.assertTrue(kwargs['future_only'])
            for job in work['payload']['jobs']:
                kwargs['rows'].append(dict(account=job['account'],target=job['target'],filename=job['filename'],key=job['key'],status='manual_required',error='自动定位暂未完成：缺少匹配',permalink=''))
                kwargs['reporter']()
        with patch.object(daily,'backfill',side_effect=backfill):self.assertEqual(run.execute(),3)
        self.assert_preserved();state=upload.read_json(self.f.state_path,{})
        self.assertTrue(all(state[j['key']]['comment_status']=='lookup_pending' for j in self.f.jobs[:15]))
        report=upload.read_json(upload.ROOT/'logs'/(run.STEM+'.json'),{})
        self.assertFalse(report['video_upload_started']);self.assertFalse(report['interactive_selection'])
        self.assertTrue(all(r['status']=='lookup_pending' for r in report['rows']))
    def test_real_backfill_continues_past_unresolved_video_and_never_resends_protected_comment(self):
        job=self.f.jobs[0];self.state[job['key']]['comment_status']='sent';upload.save_json(self.f.state_path,self.state)
        browser=MagicMock();browser.pages=[MagicMock()];self.f.launch.return_value.return_value=browser
        with patch('playwright.sync_api.sync_playwright'),patch.object(daily,'close_selected_window'),patch.object(upload,'ensure_identity'),patch.object(run.actual,'collect_links',return_value=[]),patch.object(comments,'after_publication',side_effect=AssertionError('no unbound comment')),patch.object(comments,'capture_failure'):
            self.assertEqual(run.execute(),3)
        self.assert_preserved();self.assertEqual(self.f.launch.return_value.call_count,14)
        rows=upload.read_json(upload.ROOT/'logs'/(run.STEM+'.json'),{})['rows']
        self.assertEqual([r['status'] for r in rows],['sent']+['lookup_pending']*14)
    def test_recover_only_a_verified_same_job_unsent_link(self):
        job=self.f.jobs[0];row=copy.deepcopy(self.state[job['key']])
        item=dict(video_job=job['key'],account=job['account'],target=job['target'],status='manual_required',link_method='verified_owner_caption_time',text_sha256=comments.text_hash(daily.COMMENT),permalink='https://www.facebook.com/reel/9001')
        self.assertTrue(run.restore_link(job,row,item));self.assertEqual(row['comment_link_job_key'],job['key'])
        for change in [dict(status='sending'),dict(video_job='other'),dict(text_sha256='other'),dict(link_method='unverified')]:
            self.assertFalse(run.restore_link(job,copy.deepcopy(self.state[job['key']]),dict(item,**change)))
    def test_active_worker_stops_before_writes(self):
        lock=upload.ROOT/'logs/upload.lock';lock.write_text('12345');before=self.f.state_path.read_bytes()
        with self.assertRaises(RuntimeError):run.execute()
        self.assertEqual(self.f.state_path.read_bytes(),before);self.assertEqual(lock.read_text(),'12345')
