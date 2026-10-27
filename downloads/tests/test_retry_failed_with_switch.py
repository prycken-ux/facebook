import copy
from unittest.mock import MagicMock,patch
import unittest

import fb_upload as upload
import publish_current_inbox as current
import retry_failed_with_switch as retry
import test_publish_fourteen_current as fixtures


TARGETS=[('fb02','page01'),('fb05','page01'),('fb06','page01'),('fb09','personal'),('fb10','personal'),('fb13','page01')]
ROUND='2026-10-26T17:53:46'


class RetryTests(unittest.TestCase):
    def setUp(self):
        fixtures.FourteenTests.setUp(self)
        self.rows=[]
        for entry,key,video in zip(self.entries,self.keys,self.videos):
            pair=(entry['account'],entry['target'])
            video.with_suffix('.txt').write_text((self.root/'common_caption_today.txt').read_text())
            if pair in TARGETS:
                status='failed_before_post'
            elif pair in {('fb01','page01'),('fb12','page01')}:
                status='published'
            else:
                status='needs_review'
            self.state[key]=dict(account=pair[0],target=pair[1],status=status,url=entry['url'],
                video=str(video),error='previous error')
            self.rows.append(dict(account=pair[0],target=pair[1],filename=video.name,key=key,status='unrecorded',eligible=True))
        self.rows[-1].update(key=None,status='inbox_empty',filename='',eligible=False)
        self.path=self.root/'logs/current-audit-20261026-175346-955500.json'
        self.payload=dict(schema='fourteen-current-publication-v1',created=ROUND+'+08:00',phase='attempts_finished',
            ai_label='off',caption_text=(self.root/'common_caption_today.txt').read_text(),rows=self.rows,results=[])
        upload.save_json(self.path,self.payload)
        upload.save_json(self.state_path,self.state)
        self.age_captions(1)

    def tearDown(self):
        fixtures.FourteenTests.tearDown(self)

    age_captions=fixtures.FourteenTests.age_captions

    def test_retries_only_selected_exact_failures_and_preserves_all_other_records(self):
        calls=[]
        original=current.publish_current
        def publish(account,target,label,**kwargs):
            calls.append((account,target,label,kwargs))
            return original(account,target,label,**kwargs)
        browser=MagicMock()
        browser.pages=[MagicMock()]
        with patch.object(retry,'repair_identity',return_value=True) as repair, \
             patch.object(retry,'close_selected_window') as close, \
             patch.object(retry,'publish_current',side_effect=publish), \
             patch('playwright.sync_api.sync_playwright'), \
             patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'prepare_reel',return_value=(MagicMock(),{})), \
             patch.object(upload,'recheck_publish_identity'), \
             patch.object(upload,'install_receipt_watch'), \
             patch.object(upload,'wait_for_receipt',return_value='Your reel is published.'):
            self.assertEqual(retry.retry(ROUND,TARGETS,True,True,[('fb09','personal')]),0)
        self.assertEqual([(a,t) for a,t,_,_ in calls],TARGETS)
        self.assertEqual(repair.call_count,6)
        self.assertEqual(close.call_count,6)
        self.assertTrue(next(kw for a,t,l,kw in calls if a=='fb09')['pause_before_reel'])
        actual=upload.read_json(self.state_path,{})
        retried={kw['expected_key'] for a,t,l,kw in calls}
        for key,record in self.state.items():
            if key not in retried:
                self.assertEqual(actual[key],record)
        self.assertTrue(all(actual[key]['status']=='published' for key in retried))
        self.assertEqual(len(upload.read_json(self.path,{})['final_rows']),14)

    def test_ambiguous_result_is_preserved_and_never_selected_on_second_run(self):
        calls=[]
        def unknown(account,target,label,**kw):
            calls.append(kw['expected_key'])
            state=upload.read_json(self.state_path,{})
            state[kw['expected_key']]['status']='needs_review'
            upload.save_json(self.state_path,state)
            raise upload.ReceiptNeedsReview('no receipt')
        with patch.object(retry,'repair_identity',return_value=True),patch.object(retry,'publish_current',side_effect=unknown):
            self.assertEqual(retry.retry(ROUND,TARGETS,True),3)
            self.assertEqual(retry.retry(ROUND,TARGETS,True),3)
        self.assertEqual(len(calls),6)

    def test_wrong_round_source_change_and_success_evidence_stop_before_identity_or_publish(self):
        with patch.object(retry,'repair_identity') as repair,patch.object(retry,'publish_current') as publish:
            with self.assertRaises(ValueError):
                retry.retry('2026-10-25T17:53:46',TARGETS,True)
            self.videos[1].write_bytes(b'changed source')
            with self.assertRaises(ValueError):
                retry.retry(ROUND,TARGETS,True)
            repair.assert_not_called()
            publish.assert_not_called()

    def test_skip_preserves_before_post_record_without_clearing_anything(self):
        before=copy.deepcopy(self.state)
        with patch.object(retry,'repair_identity',return_value=False),patch.object(retry,'publish_current') as publish:
            self.assertEqual(retry.retry(ROUND,TARGETS,True),3)
        publish.assert_not_called()
        self.assertEqual(upload.read_json(self.state_path,{}),before)

    def test_read_only_plan_and_existing_lock_leave_state_unchanged(self):
        before=self.state_path.read_bytes()
        with patch.object(retry,'repair_identity') as repair,patch.object(retry,'publish_current') as publish:
            self.assertEqual(retry.retry(ROUND,TARGETS),0)
            (self.root/'logs/batch.lock').write_text('existing worker')
            with self.assertRaises(RuntimeError):
                retry.retry(ROUND,TARGETS,True)
        repair.assert_not_called()
        publish.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(),before)

    def test_manual_ready_rechecks_identity_and_skip_cancel_are_not_confirmation(self):
        browser=MagicMock()
        browser.pages=[MagicMock()]
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'ensure_identity',side_effect=[RuntimeError('wrong actor'),{'method':'exact actor'}]) as check:
            values=iter(['not a command','READY','READY'])
            self.assertTrue(retry.repair_identity(self.entries[1],read=lambda prompt:next(values)))
            self.assertEqual(check.call_count,2)
            self.assertFalse(retry.repair_identity(self.entries[1],read=lambda prompt:'SKIP'))
            with self.assertRaises(KeyboardInterrupt):
                retry.repair_identity(self.entries[1],read=lambda prompt:'CANCEL')
        self.assertEqual(browser.close.call_count,3)

    def test_automatic_identity_pass_needs_no_ready_input(self):
        browser=MagicMock()
        browser.pages=[MagicMock()]
        read=MagicMock(side_effect=AssertionError('automatic success must not prompt'))
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'ensure_identity',return_value={'method':'exact actor'}) as check:
            self.assertTrue(retry.repair_identity(self.entries[1],read=read,auto_first=True))
        check.assert_called_once()
        read.assert_not_called()
        browser.close.assert_called_once()
        proof=upload.read_json(self.root/'logs'/('identity-'+self.entries[1]['account']+'-'+self.entries[1]['target']+'.json'),{})
        self.assertEqual(proof['method'],'exact actor')

    def test_automatic_failure_falls_back_without_skipping_identity_proof(self):
        browser=MagicMock()
        browser.pages=[MagicMock()]
        before=self.state_path.read_bytes()
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'ensure_identity',side_effect=[RuntimeError('unknown avatar'),{'method':'exact actor'}]) as check, \
             patch('capture_profile_switch_ui.capture',side_effect=RuntimeError('no capture')):
            self.assertTrue(retry.repair_identity(self.entries[1],read=lambda prompt:'READY',auto_first=True))
        self.assertEqual(check.call_count,2)
        self.assertEqual(self.state_path.read_bytes(),before)
        browser.close.assert_called_once()

    def test_automatic_failure_can_be_skipped_without_post_or_state_change(self):
        browser=MagicMock()
        browser.pages=[MagicMock()]
        before=self.state_path.read_bytes()
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'ensure_identity',side_effect=RuntimeError('unknown avatar')), \
             patch('capture_profile_switch_ui.capture',side_effect=RuntimeError('no capture')):
            self.assertFalse(retry.repair_identity(self.entries[1],read=lambda prompt:'SKIP',auto_first=True))
        self.assertEqual(self.state_path.read_bytes(),before)
        browser.close.assert_called_once()


if __name__=='__main__':
    unittest.main()
