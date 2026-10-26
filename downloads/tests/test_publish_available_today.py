import contextlib
import copy
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

import add_fb_accounts
import apply_common_caption as captions
import diagnose_personal_identity as diagnostic
import fb_upload as upload
import publish_available_today as today


class AvailableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.stack=contextlib.ExitStack()
        for module in (upload,add_fb_accounts,captions,diagnostic):
            self.stack.enter_context(patch.object(module,'ROOT',self.root))
        self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.ready=self.entry('fb01','page01',1001,True)
        self.new=self.entry('fb14','personal',1014,False)
        self.empty=self.entry('fb10','page02',1002,False)
        self.busy=self.entry('fb22','personal',1022,False)
        self.paused=self.entry('fb16','personal',1016,False)
        self.config=dict(custom_setting='keep',targets=[self.ready,self.new,self.empty,self.busy,self.paused])
        upload.save_json(upload.CONFIG,self.config)
        self.state_path=self.root/'logs/publish_state.json'
        upload.save_json(self.state_path,{})
        (self.root/'common_caption_today.txt').write_text('Approved caption\nhttps://example.com/?x=1&y=2')
        self.videos={}
        for entry in (self.ready,self.new,self.busy,self.paused):
            self.videos[entry['account']]=self.video(entry,'today.mp4',entry['account'].encode())
        self.sleep=self.stack.enter_context(patch.object(today.time,'sleep',side_effect=self.age))

    def entry(self,account,target,number,enabled):
        result=dict(account=account,target=target,type='personal' if target=='personal' else 'page',
            name='Name '+account,url='https://www.facebook.com/profile.php?id='+str(number),enabled=enabled,
            ai_label=True,custom_field='preserve')
        if target=='personal':
            result['workflow']='personal_recording_v1'
        if enabled:
            result['prepared_at']='previous preparation'
        (self.root/'profiles'/account).mkdir(parents=True,exist_ok=True)
        upload.inbox_for(result).mkdir(parents=True,exist_ok=True)
        return result

    def video(self,entry,name,content):
        path=upload.inbox_for(entry)/name
        path.write_bytes(content)
        os.utime(path,(time.time()-120,time.time()-120))
        return path

    def age(self,seconds):
        for path in (self.root/'videos').rglob('*.txt'):
            os.utime(path,(time.time()-120,time.time()-120))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def report(self):
        return upload.read_json(next((self.root/'logs').glob('available-today-*.json')), {})

    def run_pipeline(self,prepare_new=True,input_action=None,receipt_error=None):
        browser=MagicMock()
        browser.pages=[MagicMock()]
        button=MagicMock()
        closed=[]
        def close(account):
            closed.append(account)
            if account=='fb22':
                raise RuntimeError('profile busy')
        with patch('playwright.sync_api.sync_playwright'), \
             patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'prepare_reel',return_value=(button,{})) as prepare, \
             patch.object(upload,'recheck_publish_identity'), \
             patch.object(upload,'install_receipt_watch'), \
             patch.object(upload,'wait_for_receipt',return_value='Your reel is published.',side_effect=receipt_error), \
             patch.object(diagnostic,'close_selected_window',side_effect=close), \
             patch('builtins.input',return_value='',side_effect=input_action) as review:
            result=today.run(True,'off',prepare_new,True)
        return result,closed,prepare,review,button

    def test_old_and_new_real_pipeline_with_first_preview_enable_and_exact_archival(self):
        result,closed,prepare,review,button=self.run_pipeline()
        self.assertEqual(result,3) # busy fb22 remains unresolved
        self.assertEqual(closed,['fb14','fb22','fb01'])
        review.assert_called_once()
        self.assertEqual(button.click.call_count,2)
        self.assertEqual(prepare.call_count,3) # new prepare + new publish + old publish
        for call in prepare.call_args_list:
            self.assertFalse(call.args[1]['ai_label'])
        config=upload.read_json(upload.CONFIG,{})
        self.assertEqual(config['custom_setting'],'keep')
        by_account={e['account']:e for e in config['targets']}
        self.assertTrue(by_account['fb14']['enabled'])
        self.assertIn('prepared_at',by_account['fb14'])
        self.assertTrue(by_account['fb14']['ai_label']) # per-run override only
        for account in ('fb22','fb16','fb10'):
            self.assertFalse(by_account[account]['enabled'])
        state=upload.read_json(self.state_path,{})
        self.assertEqual(len(state),2)
        self.assertTrue(all(r['status']=='published' and not r['ai_label_requested'] for r in state.values()))
        for account in ('fb01','fb14'):
            video=self.videos[account]
            self.assertFalse(video.exists())
            self.assertTrue((video.parent.parent/'completed'/video.name).exists())
        self.assertFalse(self.videos['fb16'].with_suffix('.txt').exists())
        rows={r['account']:r for r in self.report()['final_rows']}
        self.assertEqual(rows['fb22']['status'],'needs_check')
        self.assertEqual(rows['fb10']['status'],'no_new_video')

    def test_previous_failed_material_remains_untouched_beside_new_video(self):
        old=self.video(self.ready,'old.mp4',b'previous failed video')
        old.with_suffix('.txt').write_text('Old caption')
        key=upload.job_key(self.ready,old)
        record=dict(account='fb01',target='page01',url=self.ready['url'],video=str(old),status='failed_before_post')
        upload.save_json(self.state_path,{key:record})
        self.run_pipeline()
        self.assertEqual(upload.read_json(self.state_path,{})[key],record)
        self.assertTrue(old.is_file())
        self.assertEqual(old.with_suffix('.txt').read_text(),'Old caption')
        self.assertNotIn(key,{row['key'] for row in self.report()['rows']})

    def test_multiple_new_material_is_skipped_without_enabling_or_picking(self):
        self.video(self.new,'second.mp4',b'another new video')
        result,closed,prepare,review,button=self.run_pipeline()
        self.assertNotIn('fb14',closed)
        review.assert_not_called()
        self.assertEqual(button.click.call_count,1)
        config=upload.read_json(upload.CONFIG,{})
        self.assertFalse(next(e for e in config['targets'] if e['account']=='fb14')['enabled'])

    def test_preview_changes_to_source_stop_before_enabling_or_posting_new_target(self):
        def change(prompt):
            self.videos['fb14'].write_bytes(b'changed source during preparation')
            return ''
        result,closed,prepare,review,button=self.run_pipeline(input_action=change)
        self.assertEqual(button.click.call_count,1)
        config=upload.read_json(upload.CONFIG,{})
        self.assertFalse(next(e for e in config['targets'] if e['account']=='fb14')['enabled'])
        self.assertEqual(len(upload.read_json(self.state_path,{})),1)

    def test_failed_first_prepare_does_not_enable_target_and_other_targets_continue(self):
        def fail(prompt):
            raise RuntimeError('preview cannot be completed')
        result,closed,prepare,review,button=self.run_pipeline(input_action=fail)
        self.assertEqual(button.click.call_count,1)
        self.assertFalse(next(e for e in upload.read_json(upload.CONFIG,{})['targets'] if e['account']=='fb14')['enabled'])
        self.assertTrue(self.videos['fb14'].exists())

    def test_ambiguous_receipt_stays_unknown_not_archived_or_retried(self):
        self.run_pipeline(receipt_error=upload.ReceiptNeedsReview('no receipt'))
        state=upload.read_json(self.state_path,{})
        self.assertEqual(len(state),2)
        self.assertTrue(all(r['status']=='needs_review' for r in state.values()))
        self.assertTrue(self.videos['fb01'].exists())
        self.assertTrue(self.videos['fb14'].exists())
        _,closed,_,review,button=self.run_pipeline()
        self.assertNotIn('fb01',closed)
        self.assertNotIn('fb14',closed)
        review.assert_not_called()
        button.click.assert_not_called()
        self.assertEqual(upload.read_json(self.state_path,{}),state)

    def test_plan_is_read_only_and_does_not_generate_caption_or_enable(self):
        before_config=upload.CONFIG.read_bytes()
        before_state=self.state_path.read_bytes()
        with patch.object(upload,'run_entry') as run:
            self.assertEqual(today.run(False,None,True),0)
        run.assert_not_called()
        self.sleep.assert_not_called()
        self.assertEqual(upload.CONFIG.read_bytes(),before_config)
        self.assertEqual(self.state_path.read_bytes(),before_state)
        self.assertFalse(self.videos['fb14'].with_suffix('.txt').exists())

    def test_duplicate_targets_or_links_are_not_selected(self):
        config=copy.deepcopy(self.config)
        config['targets'].append(dict(self.new,account='fb15'))
        rows=today.plan(config,{},True)
        invalid={r['account'] for r in rows if r['status']=='invalid'}
        self.assertTrue({'fb14','fb15'}<=invalid)
        config=copy.deepcopy(self.config)
        config['targets'].append(dict(self.new))
        rows=today.plan(config,{},True)
        self.assertTrue(all(not r['eligible'] for r in rows if r['account']=='fb14'))

    def test_without_prepare_new_disabled_targets_are_not_enabled(self):
        result,closed,prepare,review,button=self.run_pipeline(prepare_new=False)
        self.assertEqual(result,0)
        self.assertEqual(closed,['fb01'])
        review.assert_not_called()
        self.assertEqual(button.click.call_count,1)
        self.assertFalse(next(e for e in upload.read_json(upload.CONFIG,{})['targets'] if e['account']=='fb14')['enabled'])

    def test_ai_classification_is_required_before_any_mutation(self):
        before=upload.CONFIG.read_bytes()
        with self.assertRaisesRegex(ValueError,'明确'):
            today.run(True,None,True)
        self.assertEqual(upload.CONFIG.read_bytes(),before)
        self.assertFalse(self.videos['fb14'].with_suffix('.txt').exists())

    def test_existing_worker_lock_is_preserved_and_no_browser_or_caption_is_created(self):
        lock=self.root/'logs/batch.lock'
        lock.write_bytes(b'existing worker')
        before=upload.CONFIG.read_bytes()
        with patch.object(upload,'run_entry') as run,self.assertRaisesRegex(RuntimeError,'上传任务或遗留锁'):
            today.run(True,'off',True)
        run.assert_not_called()
        self.assertEqual(lock.read_bytes(),b'existing worker')
        self.assertEqual(upload.CONFIG.read_bytes(),before)
        self.assertFalse(self.videos['fb14'].with_suffix('.txt').exists())

    def test_original_live_unknown_video_remains_blocked_without_resetting_its_record(self):
        old=self.video(self.ready,'unknown.mp4',b'unknown prior publication')
        old.with_suffix('.txt').write_text('Keep old caption')
        key=upload.job_key(self.ready,old)
        record=dict(account='fb01',target='page01',url=self.ready['url'],video=str(old),status='needs_review')
        upload.save_json(self.state_path,{key:record})
        result,closed,prepare,review,button=self.run_pipeline()
        self.assertEqual(button.click.call_count,1) # fb14 succeeds; old target remains blocked
        self.assertEqual(upload.read_json(self.state_path,{})[key],record)
        self.assertTrue(self.videos['fb01'].exists())
        self.assertTrue(old.exists())

    def test_config_save_failure_restores_new_target_in_memory_and_does_not_publish_it(self):
        save=upload.save_json
        def fail_config(path,value):
            if path==upload.CONFIG and any(e.get('account')=='fb14' and e.get('enabled') for e in value['targets']):
                raise OSError('config disk error')
            return save(path,value)
        with patch.object(upload,'save_json',side_effect=fail_config):
            result,closed,prepare,review,button=self.run_pipeline()
        self.assertEqual(button.click.call_count,1)
        config=upload.read_json(upload.CONFIG,{})
        self.assertEqual(next(e for e in config['targets'] if e['account']=='fb14'),self.new)
        self.assertTrue(self.videos['fb14'].exists())


if __name__=='__main__':
    unittest.main()
