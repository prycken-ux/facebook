import copy
from datetime import datetime,timezone
from unittest.mock import patch
import unittest
import fb_upload as upload
import daily_publish_and_comments as daily
import scheduled_material_batch as batch
import confirm_verify_nov02_20261103 as confirm
import backfill_nov02_published_comments_20261103 as backfill
from test_confirm_verify_nov02_20261103 import ConfirmVerifyTests

REAL_BACKFILL=daily.backfill


class Nov02CommentBackfillTests(unittest.TestCase):
    job=ConfirmVerifyTests.job
    tearDown=ConfirmVerifyTests.tearDown
    def setUp(self):
        ConfirmVerifyTests.setUp(self)
        value=upload.read_json(self.source,{})
        value['payload'].update(comment_text=daily.COMMENT,excluded_accounts=['fb16','fb18','fb21'])
        value['sha256']=batch.digest(value['payload'])
        self.source=self.root/'logs'/('frozen-material-2026-11-02-'+value['sha256'][:16]+'.json')
        upload.save_json(self.source,value)
        upload.save_json(self.source.with_name(self.source.stem+'-results.json'),dict(manifest=self.source.name,attempts=[]))
        self.stack.enter_context(patch.object(backfill,'PREFIX',value['sha256'][:8]))
        self.stack.enter_context(patch.object(backfill,'USER_CONFIRMED',dict(confirm.USER_CONFIRMED)))
        clock=self.stack.enter_context(patch.object(backfill,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,3,5,tzinfo=timezone.utc)
    def selected(self):return [j for j in self.jobs if (j['account'],j['target']) not in backfill.EXCLUDED]
    def test_all_26_successes_are_offered_for_comments_without_uploading_or_touching_four_exclusions(self):
        seen=[]
        def comment(work,*args,**kwargs):
            self.assertEqual(work['payload']['date'],'2026-11-02');self.assertTrue(kwargs['future_only']);self.assertTrue(kwargs['already_locked'])
            for job in work['payload']['jobs']:
                self.assertEqual(upload.read_json(self.state_path,{})[job['key']]['status'],'published')
                seen.append(job['key']);kwargs['rows'].append(dict(job,status='manual_required',error='fixture: not sent'))
                kwargs['reporter']()
        with patch.object(backfill.daily,'backfill',side_effect=comment):self.assertEqual(backfill.execute(),3)
        self.assertEqual(set(seen),{j['key'] for j in self.selected()});self.assertEqual(len(seen),26)
        state=upload.read_json(self.state_path,{})
        for pair in backfill.EXCLUDED:
            key=self.job(pair)['key'];self.assertEqual(state.get(key),self.original.get(key))
        self.assertEqual(sum(r['status']=='published' for r in state.values()),26)
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before);self.assertEqual((self.root/'logs/video_comments.json').read_bytes(),self.comment_before)
        self.assertEqual((self.root/'logs/automatic_before_post_retry_claims.json').read_bytes(),self.retry_before)
        self.assertFalse(list(self.root.rglob('*.csv')))
    def test_real_backfill_preserves_sent_and_unknown_ledgers_and_never_reopens_browser(self):
        ledger={};statuses=['sent','needs_review','sending','verifying']+['already_present']*22
        for job,status in zip(self.selected(),statuses):
            ledger[backfill.comment_key(job)]=dict(status=status,video_job=job['key'],account=job['account'],target=job['target'],permalink='https://www.facebook.com/reel/9001',text_sha256=backfill.comments.text_hash(daily.COMMENT),verification='own_comment_seen_after_reload')
        upload.save_json(self.root/'logs/video_comments.json',ledger);before=(self.root/'logs/video_comments.json').read_bytes()
        with patch.object(backfill.daily,'backfill',wraps=REAL_BACKFILL),patch.object(upload,'launch_context',side_effect=AssertionError('protected comments must not reopen browser')) as browser:
            self.assertEqual(backfill.execute(),3)
        browser.assert_not_called();self.assertEqual((self.root/'logs/video_comments.json').read_bytes(),before)
    def test_only_exact_unsent_ledger_proof_can_restore_a_missing_video_binding(self):
        job=self.selected()[0];row=copy.deepcopy(self.state[job['key']]);item=dict(status='manual_required',video_job=job['key'],account=job['account'],target=job['target'],permalink='https://www.facebook.com/reel/9001',text_sha256=backfill.comments.text_hash(daily.COMMENT),link_method='verified_owner_caption_time_reels_tabs')
        self.assertTrue(backfill.restore_verified_link(job,row,item));self.assertEqual(row['comment_link_job_key'],job['key'])
        for change in [dict(status='needs_review'),dict(video_job='other'),dict(target='other'),dict(text_sha256='other'),dict(link_method='unknown')]:
            original=copy.deepcopy(self.state[job['key']]);trial=copy.deepcopy(original)
            self.assertFalse(backfill.restore_verified_link(job,trial,dict(item,**change)));self.assertEqual(trial,original)
    def test_bad_source_comment_or_checksum_stops_before_any_confirmation_or_send(self):
        value=upload.read_json(self.source,{});value['payload']['comment_text']='different text';upload.save_json(self.source,value)
        with self.assertRaises(ValueError):backfill.execute()
        self.assertEqual(upload.read_json(self.state_path,{}),self.original)
