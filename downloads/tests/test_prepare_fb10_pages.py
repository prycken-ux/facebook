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
import fb_upload as upload
import prepare_fb10_pages as app


class PagePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.stack=contextlib.ExitStack()
        for module in (upload,add_fb_accounts,captions):
            self.stack.enter_context(patch.object(module,'ROOT',self.root))
        self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.personal=dict(account='fb10',target='personal',type='personal',workflow='personal_recording_v1',
            name='Original person',url='https://www.facebook.com/profile.php?id=1000',enabled=True,prepared_at='keep')
        self.other=dict(self.personal,account='fb03',name='Other person',url='https://www.facebook.com/profile.php?id=1003')
        self.entries=[self.page(n) for n in range(1,10)]
        self.config=dict(custom={'preserve':True},targets=[self.personal,self.other,*self.entries])
        upload.save_json(upload.CONFIG,self.config)
        self.state_path=self.root/'logs/publish_state.json'
        self.state=dict(historical_review=dict(account='fb03',target='personal',status='needs_review',
            url=self.other['url'],video='old.mp4'))
        upload.save_json(self.state_path,self.state)
        (self.root/'profiles/fb10').mkdir(parents=True)
        self.profile=self.root/'profiles/fb10/login-marker'
        self.profile.write_bytes(b'original profile contents')
        self.caption='Approved saved caption\nhttps://example.com/?a=1&b=2'
        (self.root/'common_caption_today.txt').write_text(self.caption)
        self.videos=[self.video(entry) for entry in self.entries[:2]]
        self.stack.enter_context(patch.object(app.time,'sleep',side_effect=self.age))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def page(self,n):
        entry=dict(account='fb10',target=f'page{n:02d}',type='page',name=f'Configured Page {n}',
            url=f'https://www.facebook.com/profile.php?id={6000+n}',enabled=n==1,ai_label=True,
            excluded_files=[],custom='keep')
        if n==1:
            entry['prepared_at']='previous preview'
        return entry

    def video(self,entry,filename='new.mp4',content=None):
        path=upload.inbox_for(entry)/filename
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content or entry['target'].encode())
        path.with_suffix('.txt').write_text(self.caption)
        for item in (path,path.with_suffix('.txt')):
            os.utime(item,(time.time()-120,time.time()-120))
        return path

    def age(self,seconds):
        for path in (self.root/'videos').rglob('*.txt'):
            os.utime(path,(time.time()-120,time.time()-120))

    def report(self):
        return upload.read_json(next((self.root/'logs').glob('fb10-pages-prepare-*.json')),{})

    def browser(self,repair=True,review=None):
        stack=contextlib.ExitStack()
        self.button=MagicMock()
        context=MagicMock()
        context.pages=[MagicMock()]
        self.identity=stack.enter_context(patch.object(app,'repair_identity',return_value=repair))
        stack.enter_context(patch('playwright.sync_api.sync_playwright'))
        stack.enter_context(patch.object(upload,'launch_context',return_value=context))
        self.prepare=stack.enter_context(patch.object(upload,'prepare_reel',return_value=(self.button,{})))
        self.receipt=stack.enter_context(patch.object(upload,'wait_for_receipt'))
        self.close=stack.enter_context(patch.object(app,'close_selected_window'))
        stack.enter_context(patch('builtins.input',return_value='',side_effect=review))
        return stack

    def test_initialization_reserves_ten_folders_without_registering_or_enabling_page_ten(self):
        config=upload.CONFIG.read_bytes()
        state=self.state_path.read_bytes()
        self.assertEqual(app.run(False,True),0)
        self.assertEqual(upload.CONFIG.read_bytes(),config)
        self.assertEqual(self.state_path.read_bytes(),state)
        self.assertEqual(self.profile.read_bytes(),b'original profile contents')
        for target in app.PAGES:
            for folder in ('inbox','completed','failed'):
                self.assertTrue((self.root/'videos/fb10'/target/folder).is_dir())
        rows=self.report()['final_rows']
        self.assertEqual(len(rows),10)
        self.assertEqual(rows[-1]['status'],'not_registered')
        self.assertFalse(rows[-1]['eligible'])

    def test_real_preview_pipeline_never_posts_or_writes_ledger_and_keeps_enabled_settings(self):
        state=self.state_path.read_bytes()
        with self.browser():
            self.assertEqual(app.run(True,False,'off',True,True),3) # only 2/10 have videos
            self.assertEqual(self.prepare.call_count,2)
            self.assertEqual(self.identity.call_count,2)
            self.assertTrue(all(call.kwargs=={'auto_first':True} for call in self.identity.call_args_list))
            self.close.assert_called_once_with('fb10')
            self.button.click.assert_not_called()
            self.receipt.assert_not_called()
            self.assertTrue(all(not call.args[1]['ai_label'] for call in self.prepare.call_args_list))
        self.assertEqual(self.state_path.read_bytes(),state)
        config=upload.read_json(upload.CONFIG,{})
        self.assertEqual(config['targets'][:2],self.config['targets'][:2])
        self.assertEqual(config['custom'],self.config['custom'])
        for n,entry in enumerate(config['targets'][2:],1):
            if n<=2:
                self.assertIn('preparation_video_key',entry)
                self.assertFalse(entry['preparation_ai_label'])
            else:
                self.assertEqual(entry,self.entries[n-1])
            self.assertEqual(entry['enabled'],n==1)
            self.assertTrue(entry['ai_label']) # only this batch's preview override

    def test_all_ten_pages_with_unique_material_complete_without_any_post(self):
        tenth=self.page(10)
        self.config['targets'].append(tenth)
        upload.save_json(upload.CONFIG,self.config)
        for entry in [*self.entries[2:],tenth]:
            self.video(entry)
        with self.browser():
            self.assertEqual(app.run(True,False,'off',False),0)
            self.assertEqual(self.identity.call_count,10)
            self.assertEqual(self.prepare.call_count,10)
            self.button.click.assert_not_called()
        self.assertEqual(sum(row['status']=='preview_ready' for row in self.report()['final_rows']),10)

    def test_repeated_preparation_reuses_only_unchanged_exact_preview_evidence(self):
        with self.browser():
            app.run(True,False,'off',False)
            self.assertEqual(self.prepare.call_count,2)
        with self.browser():
            app.run(True,False,'off',False)
            self.prepare.assert_not_called()
            self.identity.assert_not_called()
            self.button.click.assert_not_called()
        with self.browser():
            app.run(True,False,'on',False)
            self.assertEqual(self.prepare.call_count,2) # a different AI setting needs a fresh preview

    def test_caption_change_invalidates_existing_preview_proof(self):
        with self.browser():
            app.run(True,False,'off',False)
        self.videos[0].with_suffix('.txt').write_text('Different supplied caption')
        self.age(60)
        with self.browser():
            app.run(True,False,'off',False)
            self.assertEqual(self.prepare.call_count,1)
            self.assertEqual(self.prepare.call_args.args[3],'Different supplied caption')

    def test_failure_records_full_ui_error_and_continues_without_posting(self):
        error='Locator expected to be visible\nCall log: waiting for target Public radio'
        with self.browser(),patch.object(upload,'prepare_reel',side_effect=[RuntimeError(error),(self.button,{})]):
            self.assertEqual(app.run(True,False,'off',False),3)
            self.button.click.assert_not_called()
        failed=self.report()['results'][0]
        self.assertEqual(failed['status'],'needs_check')
        self.assertIn(error,Path(failed['detail_log']).read_text())
        self.assertEqual(self.report()['results'][1]['status'],'preview_ready')

    def test_cancelled_identity_step_releases_owned_locks_and_keeps_original_records(self):
        before=self.state_path.read_bytes()
        with self.browser(),patch.object(app,'repair_identity',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                app.run(True,False,'off',False)
        self.assertEqual(self.state_path.read_bytes(),before)
        self.assertFalse((self.root/'logs/batch.lock').exists())
        self.assertFalse((self.root/'logs/upload.lock').exists())
        self.assertEqual(self.report()['phase'],'interrupted')

    def test_known_material_is_skipped_and_old_review_blocks_new_material_without_reset(self):
        recorded_key=upload.job_key(self.entries[0],self.videos[0])
        old=self.video(self.entries[1],'unknown.mp4',b'older unknown video')
        old_key=upload.job_key(self.entries[1],old)
        state=copy.deepcopy(self.state)
        state[recorded_key]=dict(account='fb10',target='page01',url=self.entries[0]['url'],
            video=str(self.videos[0]),status='published')
        state[old_key]=dict(account='fb10',target='page02',url=self.entries[1]['url'],video=str(old),status='needs_review')
        rows=app.inventory(self.config,state)
        self.assertEqual(rows[0]['status'],'no_new_video')
        self.assertEqual(rows[0]['recorded_inbox'][0]['status'],'published')
        self.assertEqual(rows[1]['status'],'blocked_by_older_review')
        self.assertEqual(rows[1]['blocking_keys'],[old_key])

    def test_wrong_identity_skip_does_not_select_video_or_mark_prepared(self):
        before=upload.CONFIG.read_bytes()
        with self.browser(repair=False):
            self.assertEqual(app.run(True,False,'off',False),3)
            self.prepare.assert_not_called()
            self.button.click.assert_not_called()
        self.assertEqual(upload.CONFIG.read_bytes(),before)
        self.assertTrue(all(row['status']=='manual_skipped' for row in self.report()['results']))

    def test_changed_video_after_identity_check_is_rejected_without_other_file_substitution(self):
        def repair(entry,**options):
            if entry['target']=='page01':
                self.videos[0].write_bytes(b'replacement after manual switch')
            return True
        with self.browser(),patch.object(app,'repair_identity',side_effect=repair):
            self.assertEqual(app.run(True,False,'off',False),3)
            self.assertEqual(self.prepare.call_count,1)
        config=upload.read_json(upload.CONFIG,{})
        first=next(e for e in config['targets'] if (e['account'],e['target'])==('fb10','page01'))
        self.assertEqual(first['prepared_at'],'previous preview')

    def test_source_change_during_preview_does_not_save_preparation_proof(self):
        def review(prompt):
            self.videos[0].write_bytes(b'changed during preview')
            return ''
        with self.browser(review=review):
            self.assertEqual(app.run(True,False,'off',False),3)
            self.button.click.assert_not_called()
        first=next(e for e in upload.read_json(upload.CONFIG,{})['targets'] if
                   (e['account'],e['target'])==('fb10','page01'))
        self.assertNotIn('preparation_video_key',first)

    def test_duplicate_links_or_multiple_new_files_are_not_guessed(self):
        config=copy.deepcopy(self.config)
        config['targets'][-1]['url']=self.entries[0]['url']
        rows=app.inventory(config,self.state)
        self.assertEqual(rows[0]['status'],'needs_check')
        self.video(self.entries[1],'another.mp4',b'another new video')
        rows=app.inventory(self.config,self.state)
        self.assertEqual(rows[1]['status'],'needs_check')
        self.assertFalse(rows[1]['eligible'])

    def test_new_batch_ai_classification_required_before_any_changes(self):
        before=upload.CONFIG.read_bytes()
        with self.assertRaisesRegex(ValueError,'本批'):
            app.run(True,True,None,True)
        self.assertEqual(upload.CONFIG.read_bytes(),before)
        self.assertFalse((self.root/'videos/fb10/page10').exists())

    def test_missing_profile_or_owner_does_not_create_new_login_profile(self):
        self.profile.unlink()
        (self.root/'profiles/fb10').rmdir()
        with self.assertRaisesRegex(ValueError,'浏览器资料'):
            app.run(False,True)
        self.assertFalse((self.root/'profiles/fb10').exists())

    def test_existing_task_lock_is_preserved_and_no_folders_or_browser_are_created(self):
        lock=self.root/'logs/batch.lock'
        lock.write_bytes(b'active task')
        with patch.object(upload,'run_entry') as run,self.assertRaises(RuntimeError):
            app.run(True,True,'off',True)
        run.assert_not_called()
        self.assertEqual(lock.read_bytes(),b'active task')
        self.assertFalse((self.root/'videos/fb10/page10').exists())


if __name__=='__main__':
    unittest.main()
