import copy
import unittest
from datetime import datetime,timezone
from unittest.mock import patch

import automatic_comment_retry as retry
import publication_preferences as prefs
import publish_priority_batch as priority
import fb_upload as upload
import test_scheduled_material_batch as fixtures


class AutomaticCommentRetryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ScheduledMaterialTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        prefs.save_authorized(resume_from='2026-11-11');prefs.save_content_authorized()
        with patch.object(priority,'datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,11,11,8,tzinfo=timezone.utc);self.path,self.value=priority.prepare('2026-11-11')
        self.clock=self.f.stack.enter_context(patch.object(retry,'datetime',wraps=datetime));self.clock.now.return_value=datetime(2026,11,11,8,tzinfo=timezone.utc)
        self.f.stack.enter_context(patch.object(upload,'run_entry',side_effect=AssertionError('comment retry must never upload a video')))
        self.jobs=self.value['payload']['jobs'];self.claims=self.f.root/'logs/automatic_comment_retry_claims.json'
        self.state={j['key']:dict(status='published',comment_status='sent',account=j['account'],target=j['target']) for j in self.jobs}
        self.state[self.jobs[0]['key']].update(comment_status='manual_required',comment_error='展开评论入口不唯一，未猜选')
        self.state[self.jobs[1]['key']].update(comment_status='needs_review')
        self.state[self.jobs[3]['key']].update(status='needs_review',comment_status='not_started')
        self.state[self.jobs[4]['key']].update(comment_status='manual_required',comment_error='captcha security checkpoint')
        upload.save_json(self.f.state_path,self.state)
        self.text=self.value['payload']['comment_text'];self.pending_key=self.key(self.jobs[1])
        upload.save_json(self.f.root/'logs/video_comments.json',{self.pending_key:dict(status='needs_review')})

    def key(self,job):return retry.comments.hashlib.sha256((job['key']+'\0'+retry.comments.text_hash(self.value['payload']['comment_text'])).encode()).hexdigest()

    def test_safe_failures_retry_once_and_unknown_submissions_only_reconcile(self):
        source=self.path.read_bytes();config=upload.CONFIG.read_bytes();state_before=self.f.state_path.read_bytes()
        def backfill(value,*args,**kwargs):
            claims=upload.read_json(self.claims,{})
            self.assertEqual(claims['jobs'][self.key(self.jobs[0])]['mode'],'retry_before_send')
            self.assertEqual(claims['jobs'][self.pending_key]['mode'],'verify_only')
            self.assertEqual(kwargs['only_keys'],{j['key'] for j in self.jobs[:2]})
            self.assertTrue(kwargs['already_locked']);self.assertTrue(kwargs['reconcile_pending']);self.assertTrue(kwargs['future_only'])
            kwargs['rows'].append(dict(key=self.jobs[0]['key'],status='sent'))
        with patch.object(retry.daily,'backfill',side_effect=backfill) as send:
            self.assertEqual(retry.run(self.path)[0]['status'],'sent')
            self.assertEqual(retry.run(self.path),[])
        self.assertEqual(send.call_count,1)
        self.assertEqual(self.path.read_bytes(),source);self.assertEqual(upload.CONFIG.read_bytes(),config);self.assertEqual(self.f.state_path.read_bytes(),state_before)

    def test_interruption_keeps_consumed_attempts_and_does_not_resend_on_resume(self):
        with patch.object(retry.daily,'backfill',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):retry.run(self.path)
        with patch.object(retry.daily,'backfill') as send:self.assertEqual(retry.run(self.path),[])
        send.assert_not_called();self.assertEqual(len(upload.read_json(self.claims,{})['jobs']),2)

    def test_old_batch_without_explicit_new_policy_is_not_backfilled(self):
        value=copy.deepcopy(self.value);value['payload'].pop('comment_retry_policy');checksum=retry.batch.digest(value['payload']);value['sha256']=checksum
        path=self.path.parent/('frozen-material-2026-11-11-'+checksum[:16]+'.json');upload.save_json(path,value)
        with patch.object(retry.daily,'backfill') as send:
            with self.assertRaisesRegex(ValueError,'不补历史评论'):retry.run(path)
        send.assert_not_called();self.assertFalse(self.claims.exists())

    def test_corrupt_claims_or_active_lock_do_not_reset_opportunities(self):
        self.claims.write_text('{"schema":"wrong","jobs":{}}');before=self.claims.read_bytes()
        with self.assertRaises(ValueError):retry.run(self.path)
        self.assertEqual(self.claims.read_bytes(),before)
        lock=self.f.root/'logs/upload.lock';lock.write_bytes(b'active')
        with self.assertRaises(RuntimeError):retry.run(self.path)
        self.assertEqual(lock.read_bytes(),b'active');self.assertEqual(self.claims.read_bytes(),before)

    def test_pending_ledger_is_verified_even_if_video_row_says_presend_failure(self):
        self.state[self.jobs[0]['key']]['comment_status']='manual_required';upload.save_json(self.f.state_path,self.state)
        ledger={self.key(self.jobs[0]):dict(status='sending')}
        selected,_=retry.candidates(self.value,self.state,ledger,dict(schema=retry.SCHEMA,jobs={}))
        self.assertEqual(next(mode for job,key,mode in selected if job['key']==self.jobs[0]['key']),'verify_only')

    def test_new_batch_runner_enters_comment_retry_after_first_comment_pass(self):
        value=copy.deepcopy(self.value);value['payload']['start']='2026-11-11T08:00:00+00:00';events=[]
        with patch.object(priority,'datetime',wraps=datetime) as clock,patch.object(priority,'prepare',return_value=(self.path,value)),patch.object(priority.batch,'run',side_effect=lambda *a,**k:events.append('videos')),patch.object(priority.retry,'run',side_effect=lambda *a:events.append('video-retry')),patch.object(priority.daily,'backfill',side_effect=lambda *a,**k:events.append('comments')),patch.object(priority.comment_retry,'run',side_effect=lambda *a,**k:events.append('comment-retry')),patch.object(priority.batch,'results',return_value=[]),patch.object(priority.actual,'make_finder',return_value=object()):
            clock.now.return_value=datetime(2026,11,11,9,tzinfo=timezone.utc);priority.execute('2026-11-11',True)
        self.assertEqual(events,['videos','video-retry','comments','comment-retry'])


if __name__=='__main__':unittest.main()
