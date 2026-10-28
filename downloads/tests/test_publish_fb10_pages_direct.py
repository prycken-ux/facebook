import copy
import unittest
from unittest.mock import MagicMock,patch

import fb_upload as upload
import publish_fb10_pages_direct as direct
import test_prepare_fb10_pages as fixtures


class DirectPublicationTests(unittest.TestCase):
    setUp=fixtures.PagePreparationTests.setUp
    tearDown=fixtures.PagePreparationTests.tearDown
    page=fixtures.PagePreparationTests.page
    video=fixtures.PagePreparationTests.video
    age=fixtures.PagePreparationTests.age

    def report(self):
        return upload.read_json(sorted((self.root/'logs').glob('fb10-pages-publish-*.json'))[-1],{})

    def pipeline(self,fail_target=None,unknown_target=None,change=None,interrupt=False):
        browser=MagicMock()
        browser.pages=[MagicMock()]
        button=MagicMock()
        current={}
        def prepare(page,entry,video,text):
            current['target']=entry['target']
            if change:
                change(entry,video)
            if entry['target']==fail_target:
                raise RuntimeError('identity or editor cannot be verified')
            return button,{'method':'verified_page_actor'}
        def receipt(page,post):
            if current['target']==unknown_target:
                raise upload.ReceiptNeedsReview('no fresh success receipt')
            return 'Your reel is published.'
        if interrupt:
            button.click.side_effect=KeyboardInterrupt
        with patch('playwright.sync_api.sync_playwright'), \
             patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'prepare_reel',side_effect=prepare) as prepare_call, \
             patch.object(upload,'recheck_publish_identity') as recheck, \
             patch.object(upload,'install_receipt_watch'), \
             patch.object(upload,'wait_for_receipt',side_effect=receipt), \
             patch.object(direct,'close_selected_window') as close, \
             patch('builtins.input',side_effect=AssertionError('direct publication must never prompt')) as read:
            if interrupt:
                with self.assertRaises(KeyboardInterrupt):
                    direct.run(True,'off',True)
                result=130
            else:
                result=direct.run(True,'off',True)
        return result,button,prepare_call,read,close,recheck

    def test_new_disabled_pages_publish_directly_once_without_inputs_or_permanent_enable(self):
        config=upload.CONFIG.read_bytes()
        profile=self.profile.read_bytes()
        result,button,prepare,read,close,recheck=self.pipeline()
        self.assertEqual(result,3) # page10 unregistered remains a clearly reported missing target
        self.assertEqual(button.click.call_count,2)
        self.assertEqual(prepare.call_count,2) # no separate preview or second upload
        self.assertEqual(recheck.call_count,2)
        read.assert_not_called()
        close.assert_called_once_with('fb10')
        self.assertEqual(upload.CONFIG.read_bytes(),config)
        self.assertEqual(self.profile.read_bytes(),profile)
        state=upload.read_json(self.state_path,{})
        self.assertEqual(state['historical_review'],self.state['historical_review'])
        for call,video in zip(prepare.call_args_list,self.videos):
            entry=call.args[1]
            self.assertEqual(entry['account'],'fb10')
            self.assertTrue(entry['enabled'])
            self.assertFalse(entry['ai_label'])
            key=next(key for key,row in state.items() if row.get('target')==entry['target'] and row.get('account')=='fb10')
            self.assertEqual(state[key]['status'],'published')
            self.assertFalse(state[key]['ai_label_requested'])
            self.assertFalse(video.exists())
            self.assertTrue((video.parent.parent/'completed'/video.name).is_file())
        self.assertEqual(len(self.report()['final_rows']),10)
        self.assertEqual(self.report()['schema'],'fb10-pages-direct-publication-v1')
        self.assertEqual(sum(row['status']=='published' for row in self.report()['final_rows']),2)

    def test_ten_pages_with_fresh_videos_produce_ten_posts_and_no_inputs(self):
        tenth=self.page(10)
        self.config['targets'].append(tenth)
        upload.save_json(upload.CONFIG,self.config)
        for entry in self.entries[2:]+[tenth]:
            self.video(entry)
        result,button,prepare,read,close,recheck=self.pipeline()
        self.assertEqual(result,0)
        self.assertEqual(button.click.call_count,10)
        self.assertEqual(prepare.call_count,10)
        read.assert_not_called()
        self.assertEqual([call.args[1]['target'] for call in prepare.call_args_list],[f'page{n:02d}' for n in range(1,11)])
        self.assertTrue(all(row['status']=='published' for row in self.report()['final_rows']))

    def test_failure_before_post_and_unknown_receipt_continue_and_are_never_retried(self):
        result,button,prepare,read,close,recheck=self.pipeline(fail_target='page01',unknown_target='page02')
        self.assertEqual(button.click.call_count,1)
        self.assertEqual(prepare.call_count,2)
        read.assert_not_called()
        state=upload.read_json(self.state_path,{})
        rows={row['target']:row for row in self.report()['final_rows']}
        self.assertEqual(rows['page01']['status'],'failed_before_post')
        self.assertEqual(rows['page02']['status'],'needs_review')
        _,button,prepare,read,close,recheck=self.pipeline()
        button.click.assert_not_called()
        prepare.assert_not_called()
        self.assertEqual(upload.read_json(self.state_path,{}),state)
        self.assertTrue(self.videos[0].is_file())
        self.assertTrue(self.videos[1].is_file())
        self.assertEqual(len([row for row in self.report()['manual_checks'] if row['target'] in {'page01','page02'}]),2)

    def test_old_unknown_outcome_blocks_new_file_without_resetting_history(self):
        record=dict(account='fb10',target='page01',url=self.entries[0]['url'],video='older.mp4',status='needs_review')
        self.state['older_unknown']=record
        upload.save_json(self.state_path,self.state)
        _,button,prepare,read,close,recheck=self.pipeline()
        self.assertEqual(button.click.call_count,1)
        self.assertEqual(prepare.call_args.args[1]['target'],'page02')
        self.assertEqual(upload.read_json(self.state_path,{})['older_unknown'],record)
        self.assertEqual(self.report()['final_rows'][0]['status'],'blocked_by_older_review')

    def test_changing_video_during_upload_stops_before_post(self):
        def change(entry,video):
            if entry['target']=='page01':
                video.write_bytes(b'changed during editor upload')
        _,button,prepare,read,close,recheck=self.pipeline(change=change)
        self.assertEqual(button.click.call_count,1)
        self.assertEqual(self.report()['final_rows'][0]['status'],'failed_before_post')
        self.assertIn('源视频内容变化',self.report()['final_rows'][0]['reason'])

    def test_changing_caption_during_upload_stops_before_post(self):
        def change(entry,video):
            if entry['target']=='page01':
                video.with_suffix('.txt').write_text('unapproved changed caption')
        _,button,prepare,read,close,recheck=self.pipeline(change=change)
        self.assertEqual(button.click.call_count,1)
        self.assertEqual(self.report()['final_rows'][0]['status'],'failed_before_post')
        self.assertIn('同名文案变化',self.report()['final_rows'][0]['reason'])

    def test_read_only_plan_changes_no_caption_config_state_or_browser(self):
        originals={p:p.read_bytes() for p in [upload.CONFIG,self.state_path,*self.videos,*[v.with_suffix('.txt') for v in self.videos]]}
        with patch.object(upload,'run_entry') as publish:
            self.assertEqual(direct.run(),0)
        publish.assert_not_called()
        for path,content in originals.items():self.assertEqual(path.read_bytes(),content)
        self.assertEqual(self.report()['phase'],'plan_only')

    def test_multiple_new_videos_and_duplicate_destinations_do_not_guess(self):
        self.video(self.entries[0],'second.mp4',b'another source')
        _,button,prepare,read,close,recheck=self.pipeline()
        self.assertEqual(button.click.call_count,1)
        self.assertEqual(prepare.call_args.args[1]['target'],'page02')
        self.assertEqual(self.report()['final_rows'][0]['status'],'needs_check')

    def test_existing_lock_prevents_any_publication_or_changes(self):
        (self.root/'logs/batch.lock').write_text('another task')
        before=self.state_path.read_bytes()
        with patch.object(upload,'run_entry') as publish:
            with self.assertRaises(RuntimeError):direct.run(True,'off')
        publish.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(),before)
        self.assertEqual((self.root/'logs/batch.lock').read_text(),'another task')

    def test_interrupt_after_post_intent_keeps_posting_and_does_not_repeat(self):
        result,button,prepare,read,close,recheck=self.pipeline(interrupt=True)
        self.assertEqual(result,130)
        self.assertEqual(self.report()['phase'],'interrupted')
        self.assertEqual(self.report()['final_rows'][0]['status'],'posting')
        _,button,prepare,read,close,recheck=self.pipeline()
        self.assertEqual(button.click.call_count,1)
        self.assertEqual(prepare.call_args.args[1]['target'],'page02')

    def test_caption_creation_is_scoped_and_backup_preserves_original_text(self):
        for video in self.videos:video.with_suffix('.txt').write_text('original caption')
        other=self.video(self.other,'unselected.mp4',b'other account material')
        other.with_suffix('.txt').write_text('other account original')
        _,button,prepare,read,close,recheck=self.pipeline()
        self.assertEqual(other.with_suffix('.txt').read_text(),'other account original')
        for entry in self.entries[:2]:
            backup=next((self.root/'backups').glob('fb10-pages-direct-*/videos/fb10/'+entry['target']+'/inbox/new.txt'))
            self.assertEqual(backup.read_text(),'original caption')

    def test_ai_required_and_incompatible_core_fail_before_any_post(self):
        with self.assertRaises(ValueError):direct.run(True)
        with patch.object(upload,'VERSION','2.30'):
            with self.assertRaisesRegex(ValueError,'2.31'):direct.run(True,'off')
        self.assertEqual(upload.read_json(self.state_path,{}),self.state)


if __name__=='__main__':
    unittest.main()
