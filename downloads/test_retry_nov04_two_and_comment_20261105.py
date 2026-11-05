import contextlib,copy,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import retry_nov04_two_and_comment_20261105 as run
import test_retry_nov04_after_local_file_fix_20261105 as fixtures
import fb_upload as upload
import daily_publish_and_comments as daily


class TwoRetryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.RepairedNov04Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        clock=self.stack.enter_context(patch.object(run,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,5,4,tzinfo=timezone.utc)
        self.selected=[j for j in self.f.jobs if (j['account'],j['target']) in run.SPEC]
        names={(e['account'],e['target']):e['name'] for e in self.f.entries}
        self.stack.enter_context(patch.object(run,'SPEC',{(j['account'],j['target']):(j['key'][:12],j['filename'],names[(j['account'],j['target'])]) for j in self.selected}))
        self.state=copy.deepcopy(self.f.state);self.other=[j for j in self.f.jobs if j not in self.selected]
        for i,j in enumerate(self.other):
            self.state[j['key']].update(status='published' if i<15 else 'needs_review',post_intent_at='2026-11-05T09:00:00+08:00',comment_status='sent' if i<13 else 'not_started')
        for j in self.selected:
            self.state[j['key']].update(today_first_retry_used=True,previous_before_post_attempt=copy.deepcopy(self.f.state[j['key']]))
        upload.save_json(self.f.state_path,self.state)
        self.old_grant=run.base.GRANT;self.old_path=upload.ROOT/'logs'/(self.old_grant+'-claims.json')
        upload.save_json(self.old_path,dict(grant=self.old_grant,source_sha256=upload.read_json(self.f.path,{})['sha256'],jobs={j['key']:dict(phase='consumed') for j in self.f.jobs}));self.old_bytes=self.old_path.read_bytes()
        self.stack.enter_context(patch('builtins.input',side_effect=AssertionError('no prompts')))
    def pipeline(self,unknown=False,first_fails=False):
        events=[];browser=self.f.launch.return_value.return_value;browser.pages=[]
        from unittest.mock import MagicMock
        button=MagicMock();button.click.side_effect=lambda **_:events.append('post')
        def backfill(work,out,**kwargs):
            self.assertTrue(kwargs['future_only']);self.assertTrue(kwargs['already_locked'])
            self.assertEqual({j['key'] for j in work['payload']['jobs']},{j['key'] for j in (self.selected[1:] if first_fails else self.selected)})
            events.append('comments');state=upload.read_json(self.f.state_path,{})
            for j in work['payload']['jobs']:
                state[j['key']]['comment_status']='sent'
                kwargs['rows'].append(dict(account=j['account'],target=j['target'],filename=j['filename'],key=j['key'],status='sent',error=''))
            upload.save_json(self.f.state_path,state);kwargs['reporter']()
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'prepare_reel',return_value=(button,{}),side_effect=[RuntimeError('before-Post UI still unavailable'),(button,{})] if first_fails else None),patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',side_effect=upload.ReceiptNeedsReview('unknown') if unknown else None,return_value='Your reel is published.'),patch('safe_video_comments.resolve_published_link',return_value=('https://www.facebook.com/reel/9001','fresh_success_view_reel_link')),patch.object(daily,'backfill',side_effect=backfill) as comments:
            result=run.execute()
        return result,button,events,comments
    def assert_untouched(self):
        self.assertEqual(run.base.GRANT,self.old_grant);self.assertEqual(self.old_path.read_bytes(),self.old_bytes)
        self.assertEqual(self.f.auto_path.read_bytes(),self.f.auto);self.assertEqual(upload.CONFIG.read_bytes(),self.f.config)
        state=upload.read_json(self.f.state_path,{})
        self.assertEqual(state['old-paused'],self.state['old-paused']);self.assertEqual(state['old-unknown'],self.state['old-unknown'])
        for j in self.other[:15]:self.assertEqual(state[j['key']],self.state[j['key']])
    def test_real_core_posts_only_two_then_comments_preserving_other_28_and_prior_claims(self):
        result,button,events,comments=self.pipeline();self.assertEqual(result,0);self.assertEqual(button.click.call_count,2)
        self.assertEqual(events,['post','post','comments']);self.assert_untouched()
        state=upload.read_json(self.f.state_path,{})
        self.assertTrue(all(state[j['key']]['status']=='published' for j in self.f.jobs))
        for j in self.other[15:]:
            row=state[j['key']];self.assertEqual(row['confirmation_method'],'user_confirmed_nov04_all_except_two_20261105');self.assertTrue(Path(row['archived_video']).is_file())
        for j in self.selected:self.assertEqual(state[j['key']]['comment_status'],'sent')
        report=upload.read_json(self.f.path.with_name(self.f.path.stem+'-results.json'),{})
        self.assertEqual(report['attempts'][:30],self.f.attempts);self.assertEqual(len(report['attempts']),32)
        with patch.object(upload,'run_entry',side_effect=AssertionError('cannot post twice')),patch.object(daily,'backfill'):self.assertEqual(run.execute(),0)
    def test_new_unknown_consumes_grant_and_is_never_retried_or_commented(self):
        result,button,events,comments=self.pipeline(True);self.assertEqual(result,3);self.assertEqual(button.click.call_count,2);comments.assert_not_called()
        with patch.object(upload,'run_entry',side_effect=AssertionError('unknown cannot post')),patch.object(daily,'backfill') as backfill:self.assertEqual(run.execute(),3)
        backfill.assert_not_called();self.assert_untouched()
        claims=upload.read_json(upload.ROOT/'logs'/(run.GRANT+'-claims.json'),{})
        self.assertEqual({v['phase'] for v in claims['jobs'].values()},{'consumed'})
    def test_one_prepost_failure_does_not_block_the_other_video_and_its_comment(self):
        result,button,events,comments=self.pipeline(first_fails=True)
        self.assertEqual(result,3);self.assertEqual(button.click.call_count,1);self.assertEqual(events,['post','comments']);self.assert_untouched()
        state=upload.read_json(self.f.state_path,{})
        self.assertEqual(state[self.selected[0]['key']]['status'],'failed_before_post')
        self.assertEqual(state[self.selected[1]['key']]['status'],'published');self.assertEqual(state[self.selected[1]['key']]['comment_status'],'sent')
    def test_active_lock_writes_nothing(self):
        lock=upload.ROOT/'logs/upload.lock';lock.write_text('12345');before=self.f.state_path.read_bytes()
        with self.assertRaises(RuntimeError):run.execute()
        self.assertEqual(self.f.state_path.read_bytes(),before);self.assert_untouched()
    def test_changed_original_cannot_upload_and_other_confirmations_remain_durable(self):
        Path(self.state[self.selected[0]['key']]['caption']).write_text('changed caption')
        self.f.check.side_effect=RuntimeError('test stops before second upload')
        with patch.object(upload,'run_entry') as post:
            with self.assertRaises(RuntimeError):run.execute()
        post.assert_not_called();self.assert_untouched()
        self.assertTrue(all(upload.read_json(self.f.state_path,{})[j['key']]['status']=='published' for j in self.other))
    def test_a_new_failure_among_the_other_28_cannot_be_silently_confirmed(self):
        state=copy.deepcopy(self.state);state[self.other[20]['key']]['status']='failed_before_post';upload.save_json(self.f.state_path,state)
        with self.assertRaises(ValueError):run.execute()
        self.assertEqual(upload.read_json(self.f.state_path,{}),state)
    def test_mismatched_screenshot_name_and_filename_refuse_before_any_state_change(self):
        spec=copy.deepcopy(run.SPEC);pair=next(iter(spec));prefix,filename,name=spec[pair];spec[pair]=(prefix,filename,'another account')
        with patch.object(run,'SPEC',spec):
            with self.assertRaises(ValueError):run.execute()
        self.assertEqual(upload.read_json(self.f.state_path,{}),self.state)
