import copy
import os
import time
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock,patch

import fb_upload as upload
import finalize_verified_twenty as final
import test_retry_failed_with_switch as fixture


class FinalizeTests(unittest.TestCase):
    tearDown=fixture.RetryTests.tearDown

    def age_captions(self,seconds):
        for path in (self.root/'videos').rglob('*.txt'):
            os.utime(path,(time.time()-120,time.time()-120))

    def setUp(self):
        fixture.RetryTests.setUp(self)
        self.new_entries={}
        self.new_videos={}
        self.new_keys={}
        rows=[]
        caption=(self.root/'common_caption_today.txt').read_text()
        for n in (14,15,17,19,20,22,23):
            account=f'fb{n:02d}'
            prepared=n not in {17,23}
            entry=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',
                name='Name '+account,url=f'https://www.facebook.com/profile.php?id={20000+n}',
                enabled=prepared,ai_label=True,custom_setting='keep')
            if prepared:
                entry['prepared_at']='previous preview'
            (self.root/'profiles'/account).mkdir(parents=True)
            video=upload.inbox_for(entry)/f'原视频{n}.mp4'
            video.parent.mkdir(parents=True)
            video.write_bytes(f'actual original material {n}'.encode())
            video.with_suffix('.txt').write_text(caption)
            key=upload.job_key(entry,video)
            row=dict(account=account,target='personal',url=entry['url'],filename=video.name,key=key,
                status='ready',eligible=True,reason='original batch material')
            rows.append(row)
            if prepared:
                self.state[key]=dict(account=account,target='personal',url=entry['url'],video=str(video),
                    created='2026-10-26T18:23:00+08:00',status='needs_review',error='old receipt missing')
            self.config['targets'].append(entry)
            self.new_entries[account]=entry
            self.new_videos[account]=video
            self.new_keys[account]=key
        upload.save_json(upload.CONFIG,self.config)
        upload.save_json(self.state_path,self.state)
        self.expanded=dict(schema='available-current-publication-v1',created='2026-10-26T18:22:38+08:00',
            phase='attempts_finished',rows=rows,results=[],caption_text=caption,ai_label='off')
        self.expanded_path=self.root/'logs'/final.EXPANDED
        upload.save_json(self.expanded_path,self.expanded)
        for video in self.new_videos.values():
            for path in (video,video.with_suffix('.txt')):
                os.utime(path,(time.time()-120,time.time()-120))
        self.claims_path=self.root/'logs/verified-twenty-user-check.json'

    def browser(self,receipts=None,prepare_error=None):
        stack=ExitStack()
        context=MagicMock()
        context.pages=[MagicMock()]
        self.button=MagicMock()
        self.prepared=[]
        def prepare(page,entry,video,text):
            self.prepared.append(entry['account'])
            if prepare_error and entry['account']=='fb17':
                raise RuntimeError(prepare_error)
            self.assertFalse(entry['ai_label'])
            return self.button,{}
        stack.enter_context(patch('playwright.sync_api.sync_playwright'))
        stack.enter_context(patch.object(upload,'launch_context',return_value=context))
        stack.enter_context(patch.object(upload,'prepare_reel',side_effect=prepare))
        stack.enter_context(patch.object(upload,'install_receipt_watch'))
        stack.enter_context(patch.object(upload,'recheck_publish_identity'))
        stack.enter_context(patch.object(upload,'wait_for_receipt',return_value='Your reel is published.',side_effect=receipts))
        stack.enter_context(patch.object(upload,'check_identity'))
        stack.enter_context(patch.object(final,'close_selected_window'))
        stack.enter_context(patch.object(final.available.time,'sleep',side_effect=self.age_captions))
        stack.enter_context(patch('builtins.input',return_value=''))
        return stack

    def test_real_ledger_pipeline_confirms_eighteen_and_posts_only_two_then_repeats_safely(self):
        historical=copy.deepcopy(self.state['historical_review'])
        with self.browser():
            self.assertEqual(final.run(True,True,True),0)
            self.assertEqual(self.button.click.call_count,2)
            self.assertEqual(self.prepared,['fb15','fb17','fb17'])
        report=final.status.collect(final.DATE)
        self.assertEqual(report['counts'],dict(published=20))
        state=upload.read_json(self.state_path,{})
        self.assertEqual(state['historical_review'],historical)
        manual=state[self.new_keys['fb23']]
        self.assertEqual(manual['confirmation_method'],'user_confirmed_existing_post_no_link')
        self.assertEqual(manual['status_before_user_confirmation'],'unrecorded')
        self.assertFalse(self.new_videos['fb23'].exists())
        self.assertTrue((self.new_videos['fb23'].parent.parent/'completed'/self.new_videos['fb23'].name).exists())
        config=upload.read_json(upload.CONFIG,{})
        self.assertTrue(next(e for e in config['targets'] if e['account']=='fb17')['enabled'])
        self.assertFalse(next(e for e in config['targets'] if e['account']=='fb23')['enabled'])
        before=self.state_path.read_bytes()
        with self.browser():
            self.assertEqual(final.run(True,True,True),0)
            self.button.click.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(),before)

    def test_fb15_unknown_retry_is_once_only_and_keeps_new_unknown_on_repeat(self):
        with self.browser([upload.ReceiptNeedsReview('new uncertain receipt'),'Your reel is published.']):
            self.assertEqual(final.run(True,True),3)
            self.assertEqual(self.button.click.call_count,2)
        self.assertEqual(upload.read_json(self.state_path,{})[self.new_keys['fb15']]['status'],'needs_review')
        with self.browser():
            self.assertEqual(final.run(True,True),3)
            self.button.click.assert_not_called()
        self.assertEqual(final.status.collect(final.DATE)['counts'],dict(published=19,needs_review=1))

    def test_fb17_initially_unrecorded_unknown_cannot_reuse_initial_absence_assertion(self):
        with self.browser(['Your reel is published.',upload.ReceiptNeedsReview('new unknown')]):
            self.assertEqual(final.run(True,True),3)
        self.assertEqual(upload.read_json(self.state_path,{})[self.new_keys['fb17']]['status'],'needs_review')
        with self.browser():
            self.assertEqual(final.run(True,True),3)
            self.button.click.assert_not_called()
        self.assertTrue(all(c['phase']=='consumed' for c in upload.read_json(self.claims_path,{}).values()))

    def test_prepare_failure_leaves_fb17_disabled_and_can_resume_before_any_post(self):
        with self.browser(prepare_error='missing visible control'):
            self.assertEqual(final.run(True,True),3)
            self.assertEqual(self.button.click.call_count,1)
        self.assertNotIn(self.new_keys['fb17'],upload.read_json(self.state_path,{}))
        self.assertFalse(next(e for e in upload.read_json(upload.CONFIG,{})['targets'] if e['account']=='fb17')['enabled'])
        with self.browser():
            self.assertEqual(final.run(True,True),0)
            self.assertEqual(self.button.click.call_count,1)

    def test_wrong_manual_source_hash_stops_before_any_confirmation_or_post(self):
        self.new_videos['fb23'].write_bytes(b'new different file reusing old name')
        before=self.state_path.read_bytes()
        with patch.object(upload,'run_entry') as publish,self.assertRaisesRegex(ValueError,'指纹一致'):
            final.run(True,True)
        publish.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(),before)

    def test_unverified_run_or_plan_never_mutates_ledger_config_or_media(self):
        before=self.state_path.read_bytes()
        config=upload.CONFIG.read_bytes()
        with self.assertRaises(ValueError):
            final.run(True,False)
        self.assertEqual(final.run(False),0)
        self.assertEqual(self.state_path.read_bytes(),before)
        self.assertEqual(upload.CONFIG.read_bytes(),config)
        self.assertTrue(self.new_videos['fb23'].exists())

    def test_reserved_original_guard_is_restored_if_process_died_before_new_task(self):
        key=self.new_keys['fb15']
        old=copy.deepcopy(self.state[key])
        state=copy.deepcopy(self.state)
        del state[key]
        upload.save_json(self.state_path,state)
        claim_id=final.EXPANDED+':'+key+':'+final.VERIFICATION
        upload.save_json(self.claims_path,{claim_id:dict(phase='reserved',original_record=old)})
        with patch.object(upload,'check_identity',side_effect=RuntimeError('profile busy')):
            with self.assertRaisesRegex(RuntimeError,'profile busy'):
                final.retry_once(('fb15','personal'))
        self.assertEqual(upload.read_json(self.state_path,{})[key],old)
        self.assertEqual(upload.read_json(self.claims_path,{})[claim_id]['phase'],'not_started')

    def test_reserved_unrecorded_claim_with_new_task_is_consumed_without_repeating(self):
        key=self.new_keys['fb17']
        state=copy.deepcopy(self.state)
        state[key]=dict(account='fb17',target='personal',url=self.new_entries['fb17']['url'],
            video=str(self.new_videos['fb17']),status='needs_review')
        upload.save_json(self.state_path,state)
        claim_id=final.EXPANDED+':'+key+':'+final.VERIFICATION
        upload.save_json(self.claims_path,{claim_id:dict(phase='reserved',original_record=None)})
        with patch.object(upload,'run_entry') as publish:
            self.assertFalse(final.retry_once(('fb17','personal')))
        publish.assert_not_called()
        self.assertEqual(upload.read_json(self.claims_path,{})[claim_id]['phase'],'consumed')

    def test_existing_lock_is_not_removed(self):
        lock=self.root/'logs/batch.lock'
        lock.write_bytes(b'active task')
        with self.assertRaises(RuntimeError):
            final.run(True,True)
        self.assertEqual(lock.read_bytes(),b'active task')


if __name__=='__main__':
    unittest.main()
