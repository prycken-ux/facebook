import copy,hashlib,unittest
from unittest.mock import patch
import test_confirm_verify_nov02_20261103 as fixture
import mark_all_nov02_published_20261103 as mark
import fb_upload as upload
import daily_publish_and_comments as daily


class MarkAllTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.ConfirmVerifyTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        value=upload.read_json(self.fx.source,{})
        value['payload'].update(comment_text=daily.COMMENT,excluded_accounts=['fb16','fb18','fb21'])
        value['sha256']=mark.batch.digest(value['payload'])
        self.source=self.fx.source.with_name('frozen-material-2026-11-02-'+value['sha256'][:16]+'.json')
        self.fx.source.unlink();upload.save_json(self.source,value)
        self.attempts=[dict(key=self.fx.jobs[0]['key'],action='manual_required',error='original failure')]
        upload.save_json(self.source.with_name(self.source.stem+'-results.json'),dict(manifest=self.source.name,attempts=self.attempts))
        self.fx.stack.enter_context(patch.object(mark,'PREFIX',value['sha256'][:8]))
        self.fx.stack.enter_context(patch.object(upload,'launch_context',side_effect=AssertionError('no browser')))
        state=upload.read_json(self.fx.state_path,{})
        key=hashlib.sha256(b'old-fb02-task-outside-original-batch').hexdigest()
        state[key]=dict(account='fb02',target='page01',status='posting',video='old.mp4')
        self.old_key=key
        successful=next(j['key'] for j in self.fx.jobs if state.get(j['key'],{}).get('status')=='published')
        state[successful].update(comment_status='sent',comment_error='',permalink='https://www.facebook.com/reel/9001')
        pending=next(j['key'] for j in self.fx.jobs if state.get(j['key'],{}).get('status')=='needs_review')
        state[pending].update(comment_status='needs_review',comment_error='ambiguous send')
        upload.save_json(self.fx.state_path,state);self.before=copy.deepcopy(state)
    def test_all_30_are_published_with_missing_record_created_and_other_data_preserved(self):
        self.assertEqual(mark.execute(),0)
        state=upload.read_json(self.fx.state_path,{})
        self.assertTrue(all(state[j['key']]['status']=='published' for j in self.fx.jobs))
        self.assertEqual(state[self.old_key],self.before[self.old_key])
        for job in self.fx.jobs:
            key=job['key'];old=self.before.get(key)
            if old and old['status']=='published':self.assertEqual(state[key],old)
            elif old:
                self.assertEqual(state[key]['confirmation_method'],mark.METHOD)
                self.assertEqual(state[key].get('comment_status'),old.get('comment_status'))
                self.assertEqual(state[key].get('comment_error'),old.get('comment_error'))
                self.assertEqual(state[key].get('post_intent_at'),old.get('post_intent_at'))
        missing=self.fx.job(('fb02','page01'))['key']
        self.assertEqual(state[missing]['record_origin'],'user_confirmation_from_frozen_manifest')
        self.assertNotIn('post_intent_at',state[missing]);self.assertNotIn('published_at',state[missing])
        self.assertEqual((self.fx.root/'logs/video_comments.json').read_bytes(),self.fx.comment_before)
        self.assertEqual((self.fx.root/'logs/automatic_before_post_retry_claims.json').read_bytes(),self.fx.retry_before)
        self.assertEqual(upload.CONFIG.read_bytes(),self.fx.config_before)
        report=upload.read_json(self.source.with_name(self.source.stem+'-results.json'),{})
        self.assertEqual(report['attempts'],self.attempts)
        self.assertEqual(sum(r['video_status']=='published' for r in report['rows']),30)
        audits=list((self.fx.root/'backups').glob('*/confirmation-audit.json'))
        audit=upload.read_json(audits[0],{})
        self.assertEqual(len(audit['changes']),sum(self.before.get(j['key'],{}).get('status')!='published' for j in self.fx.jobs))
        self.assertTrue(any(r['prior_record'] is None for r in audit['changes']))
        self.assertFalse(list(self.fx.root.rglob('*.csv')))
    def test_rerun_is_idempotent_and_does_not_replace_success_provenance(self):
        mark.execute();state=self.fx.state_path.read_bytes();mark.execute()
        self.assertEqual(self.fx.state_path.read_bytes(),state)
    def test_any_wrong_original_job_binding_aborts_before_any_state_change(self):
        state=copy.deepcopy(self.before);state[self.fx.jobs[-1]['key']]['video']='wrong.mp4'
        upload.save_json(self.fx.state_path,state);before=self.fx.state_path.read_bytes()
        with self.assertRaises(ValueError):mark.execute()
        self.assertEqual(self.fx.state_path.read_bytes(),before)
        self.assertFalse((self.fx.root/'backups').exists())
    def test_source_tamper_or_wrong_report_aborts_before_any_state_change(self):
        original=upload.read_json(self.source,{})
        changed=copy.deepcopy(original);changed['payload']['date']='2026-11-03';upload.save_json(self.source,changed)
        with self.assertRaises(ValueError):mark.execute()
        self.assertEqual(upload.read_json(self.fx.state_path,{}),self.before)
        upload.save_json(self.source,original)
        upload.save_json(self.source.with_name(self.source.stem+'-results.json'),dict(manifest='other.json',attempts=[]))
        with self.assertRaises(ValueError):mark.execute()
        self.assertEqual(upload.read_json(self.fx.state_path,{}),self.before)
    def test_live_task_lock_prevents_mutation(self):
        (self.fx.root/'logs/batch.lock').write_text('12345')
        with self.assertRaises(RuntimeError):mark.execute()
        self.assertEqual(upload.read_json(self.fx.state_path,{}),self.before)
        self.assertEqual((self.fx.root/'logs/batch.lock').read_text(),'12345')
    def test_report_error_keeps_saved_guard_and_rerun_refreshes_report(self):
        with patch.object(mark.batch,'results',side_effect=OSError('report write failed')):
            with self.assertRaises(OSError):mark.execute()
        state=upload.read_json(self.fx.state_path,{})
        self.assertTrue(all(state[j['key']]['status']=='published' for j in self.fx.jobs))
        mark.execute()
        self.assertEqual(upload.read_json(self.fx.state_path,{}),state)
