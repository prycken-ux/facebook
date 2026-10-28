import copy
import os
import unittest
from unittest.mock import MagicMock,patch

import fb_upload as upload
import retry_fb10_page as retry
import test_prepare_fb10_pages as fixtures


class RetryDirectPageTests(unittest.TestCase):
    setUpBase=fixtures.PagePreparationTests.setUp
    tearDown=fixtures.PagePreparationTests.tearDown
    page=fixtures.PagePreparationTests.page
    video=fixtures.PagePreparationTests.video
    age=fixtures.PagePreparationTests.age

    def setUp(self):
        self.setUpBase()
        self.entry=self.entries[3]
        self.video_path=self.video(self.entry,'original.mp4')
        self.key=upload.job_key(self.entry,self.video_path)
        self.old=dict(account='fb10',target='page04',url=self.entry['url'],video=str(self.video_path),
                      status='needs_review',ai_label_requested=False,created='original attempt')
        self.state[self.key]=copy.deepcopy(self.old)
        self.rows=[]
        for n in range(1,11):
            entry=self.page(n)
            row=dict(account='fb10',target=entry['target'],name=entry['name'],url=entry['url'],key=None,
                     filename='',status='no_new_video',reason='',recorded_inbox=[])
            if n==4:row.update(key=self.key,filename=self.video_path.name,status='ready_to_publish')
            if n==3:
                row.update(key='a'*64,filename='previous-success.mp4',status='ready_to_publish')
                self.state['a'*64]=dict(account='fb10',target=entry['target'],url=entry['url'],status='published',
                    video='previous-success.mp4',success_message='keep original success')
            self.rows.append(row)
        self.filename='fb10-pages-publish-20261028-170239-214791.json'
        self.path=self.root/'logs'/self.filename
        self.report=dict(schema='fb10-pages-direct-publication-v1',created='2026-10-28T17:02:39+08:00',
            phase='attempts_finished',caption_text=self.caption,ai_label='off',rows=self.rows,
            results=[dict(key=self.key,status='needs_check',error='original missing receipt')])
        upload.save_json(self.path,self.report)
        upload.save_json(self.state_path,self.state)
        self.config_before=upload.CONFIG.read_bytes()

    def pipeline(self,unknown=False):
        browser=MagicMock();browser.pages=[MagicMock()]
        button=MagicMock()
        with patch.object(upload,'check_identity') as identity, \
             patch('retry_current_verified_absent.close_selected_window') as close, \
             patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'prepare_reel',return_value=(button,{})) as prepare, \
             patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'), \
             patch.object(upload,'wait_for_receipt',return_value='Your reel is published.',
                side_effect=upload.ReceiptNeedsReview('new receipt unknown') if unknown else None), \
             patch('builtins.input',side_effect=AssertionError('retry must not prompt')) as read:
            result=retry.run(self.filename,'page04',True,'user-fixed-check',True)
        return result,button,identity,close,prepare,read

    def test_retries_only_original_page04_without_persisting_enable_and_updates_original_report(self):
        result,button,identity,close,prepare,read=self.pipeline()
        self.assertEqual(result,0)
        button.click.assert_called_once()
        identity.assert_called_once()
        close.assert_called_once_with('fb10')
        read.assert_not_called()
        self.assertEqual(prepare.call_args.args[1]['target'],'page04')
        self.assertEqual(prepare.call_args.args[2].name,'original.mp4')
        state=upload.read_json(self.state_path,{})
        for key,record in self.state.items():
            if key!=self.key:self.assertEqual(state[key],record)
        self.assertEqual(state[self.key]['status'],'published')
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        report=upload.read_json(self.path,{})
        self.assertEqual(report['rows'],self.report['rows'])
        self.assertEqual(report['results'],self.report['results'])
        self.assertEqual(len(report['resume_results']),1)
        self.assertEqual(next(row for row in report['final_rows'] if row['target']=='page04')['status'],'published')
        self.assertTrue((self.video_path.parent.parent/'completed/original.mp4').is_file())
        self.assertTrue(next((self.root/'backups').glob('verified-current-absent-*/publish_state.json')).is_file())

    def test_unknown_new_result_consumes_check_and_same_command_never_posts_twice(self):
        result,button,*_=self.pipeline(unknown=True)
        self.assertEqual(result,3)
        button.click.assert_called_once()
        state=self.state_path.read_bytes()
        result,button,identity,close,prepare,read=self.pipeline()
        self.assertEqual(result,3)
        button.click.assert_not_called()
        identity.assert_not_called()
        close.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(),state)

    def test_already_successful_source_is_not_republished(self):
        self.state[self.key].update(status='published',success_message='real receipt')
        upload.save_json(self.state_path,self.state)
        result,button,identity,close,prepare,read=self.pipeline()
        self.assertEqual(result,0)
        button.click.assert_not_called()
        identity.assert_not_called()

    def test_missing_user_verification_and_wrong_source_schema_or_material_are_rejected(self):
        with self.assertRaises(ValueError):retry.run(self.filename,'page04',False,'fixed')
        original=self.state_path.read_bytes()
        changed=copy.deepcopy(self.report);changed['schema']='fourteen-current-publication-v1'
        upload.save_json(self.path,changed)
        with self.assertRaises(ValueError):retry.run(self.filename,'page04',True,'fixed')
        upload.save_json(self.path,self.report)
        self.video_path.write_bytes(b'replacement video')
        result,button,identity,close,prepare,read=self.pipeline()
        self.assertEqual(result,3)
        button.click.assert_not_called()
        identity.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(),original)

    def test_source_common_caption_and_ai_must_match_before_identity_or_guard_removal(self):
        for field,value in [('caption_text','different caption'),('ai_label','on')]:
            report=copy.deepcopy(self.report);report[field]=value
            upload.save_json(self.path,report)
            result,button,identity,close,prepare,read=self.pipeline()
            self.assertEqual(result,3)
            button.click.assert_not_called()
            identity.assert_not_called()
            self.assertEqual(upload.read_json(self.state_path,{}),self.state)

    def test_another_pending_job_on_same_page_is_not_bypassed(self):
        self.state['other']=dict(self.old,video='another.mp4')
        upload.save_json(self.state_path,self.state)
        result,button,identity,close,prepare,read=self.pipeline()
        self.assertEqual(result,3)
        button.click.assert_not_called()
        identity.assert_not_called()
        self.assertEqual(upload.read_json(self.state_path,{}),self.state)

    def test_failure_to_launch_after_identity_restores_original_and_allows_not_started_retry(self):
        with patch.object(upload,'check_identity'),patch.object(upload,'launch_context',side_effect=RuntimeError('launch failed')):
            self.assertEqual(retry.run(self.filename,'page04',True,'user-fixed-check'),3)
        self.assertEqual(upload.read_json(self.state_path,{}),self.state)
        result,button,*_=self.pipeline()
        self.assertEqual(result,0)
        button.click.assert_called_once()


if __name__=='__main__':unittest.main()
