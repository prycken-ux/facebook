import copy
import os
import time
import unittest
from unittest.mock import MagicMock,patch

import fb_upload as upload
import publish_other_accounts_direct as direct
import test_publish_available_today as fixtures


class OtherAccountsTests(unittest.TestCase):
    base_setUp=fixtures.AvailableTests.setUp
    tearDown=fixtures.AvailableTests.tearDown
    entry=fixtures.AvailableTests.entry
    video=fixtures.AvailableTests.video
    age=fixtures.AvailableTests.age

    def setUp(self):
        self.base_setUp()
        self.fb23=self.entry('fb23','personal',1023,False)
        self.config['targets'].append(self.fb23)
        self.custom=self.video(self.fb23,'custom.mp4',b'fb23 exact video')
        self.custom_caption=b'\xef\xbb\xbfOriginal fb23 caption\r\nhttps://example.com/product?x=1&y=2\r\n'
        self.custom.with_suffix('.txt').write_bytes(self.custom_caption)
        os.utime(self.custom.with_suffix('.txt'),(time.time()-120,time.time()-120))
        upload.save_json(upload.CONFIG,self.config)
        self.config_before=upload.CONFIG.read_bytes()

    def report(self):
        return upload.read_json(sorted((self.root/'logs').glob('other-accounts-publish-*.json'))[-1],{})

    def pipeline(self,unknown=None,change=None):
        browser=MagicMock();browser.pages=[MagicMock()]
        button=MagicMock();current={}
        def prepare(page,entry,video,text):
            current['account']=entry['account']
            if change:change(entry,video)
            return button,{'method':'verified actor'}
        def close(account):
            if account=='fb22':raise RuntimeError('profile busy')
        def receipt(page,post):
            if current['account']==unknown:raise upload.ReceiptNeedsReview('no receipt')
            return 'Your reel is published.'
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'prepare_reel',side_effect=prepare) as prepare_call, \
             patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'), \
             patch.object(upload,'wait_for_receipt',side_effect=receipt), \
             patch.object(direct,'close_selected_window',side_effect=close) as close_call, \
             patch('builtins.input',side_effect=AssertionError('automatic publishing must not prompt')) as read:
            result=direct.run(True,'off',True)
        return result,button,prepare_call,close_call,read

    def test_direct_posts_preserve_fb23_caption_bytes_and_use_saved_common_for_others(self):
        result,button,prepare,close,read=self.pipeline()
        self.assertEqual(result,3) # busy fb22
        self.assertEqual(button.click.call_count,3)
        read.assert_not_called()
        calls={call.args[1]['account']:call for call in prepare.call_args_list}
        self.assertEqual(set(calls),{'fb01','fb14','fb23'})
        common=(self.root/'common_caption_today.txt').read_text().strip()
        for account in ('fb01','fb14'):self.assertEqual(calls[account].args[3],common)
        self.assertEqual(calls['fb23'].args[3],self.custom_caption.decode('utf-8-sig').strip().replace('\r\n','\n'))
        self.assertEqual((self.custom.parent.parent/'completed/custom.txt').read_bytes(),self.custom_caption)
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        self.assertTrue(all(not call.args[1]['ai_label'] for call in prepare.call_args_list))
        self.assertTrue(all(call.args[1]['auto_switch_personal'] for call in prepare.call_args_list))
        self.assertFalse(self.videos['fb16'].with_suffix('.txt').exists())
        self.assertNotIn('fb16',{call.args[0] for call in close.call_args_list})
        self.assertNotIn('fb10',{call.args[0] for call in close.call_args_list})
        self.assertTrue(all(not (r['account']=='fb10' and r['target'].startswith('page')) for r in self.report()['rows']))

    def test_fb10_personal_included_while_all_fb10_pages_and_three_paused_slots_untouched(self):
        personal=self.entry('fb10','personal',1010,False)
        self.config['targets'].append(personal)
        personal_video=self.video(personal,'personal.mp4',b'fb10 personal new')
        page_video=self.video(self.empty,'excluded-page.mp4',b'fb10 excluded Page new')
        page_video.with_suffix('.txt').write_text('excluded Page original caption')
        paused=[]
        for account,number in [('fb18',1018),('fb21',1021)]:
            entry=self.entry(account,'personal',number,False)
            self.config['targets'].append(entry)
            paused.append(self.video(entry,'paused.mp4',account.encode()))
        upload.save_json(upload.CONFIG,self.config)
        _,button,prepare,close,read=self.pipeline()
        self.assertEqual(button.click.call_count,4)
        self.assertIn(('fb10','personal'),[(call.args[1]['account'],call.args[1]['target']) for call in prepare.call_args_list])
        self.assertEqual(page_video.with_suffix('.txt').read_text(),'excluded Page original caption')
        self.assertTrue(page_video.is_file())
        self.assertTrue(all(not path.with_suffix('.txt').exists() for path in paused))
        self.assertFalse(personal_video.exists())

    def test_fb23_missing_or_empty_txt_is_skipped_without_creating_or_overwriting(self):
        self.custom.with_suffix('.txt').unlink()
        _,button,prepare,close,read=self.pipeline()
        self.assertNotIn('fb23',[call.args[1]['account'] for call in prepare.call_args_list])
        self.assertFalse(self.custom.with_suffix('.txt').exists())
        row=next(row for row in self.report()['final_rows'] if row['account']=='fb23')
        self.assertEqual(row['status'],'needs_check')
        self.custom.with_suffix('.txt').write_bytes(b'')
        _,button,prepare,close,read=self.pipeline()
        self.assertEqual(self.custom.with_suffix('.txt').read_bytes(),b'')
        self.assertNotIn('fb23',[call.args[1]['account'] for call in prepare.call_args_list])

    def test_unknown_receipt_is_preserved_and_not_retried(self):
        self.pipeline(unknown='fb23')
        key=upload.job_key(self.fb23,self.custom)
        state=upload.read_json(self.state_path,{})
        self.assertEqual(state[key]['status'],'needs_review')
        _,button,prepare,close,read=self.pipeline()
        self.assertNotIn('fb23',[call.args[1]['account'] for call in prepare.call_args_list])
        self.assertEqual(upload.read_json(self.state_path,{}),state)
        self.assertEqual(self.custom.with_suffix('.txt').read_bytes(),self.custom_caption)

    def test_fb23_caption_changed_during_upload_stops_before_post(self):
        def change(entry,video):
            if entry['account']=='fb23':video.with_suffix('.txt').write_text('external changed caption')
        _,button,prepare,close,read=self.pipeline(change=change)
        self.assertEqual(button.click.call_count,2)
        row=next(row for row in self.report()['final_rows'] if row['account']=='fb23')
        self.assertEqual(row['status'],'failed_before_post')
        self.assertIn('同名文案变化',row['reason'])

    def test_previous_unknown_blocks_new_video_without_clearing_old_guard(self):
        old=dict(account='fb14',target='personal',url=self.new['url'],video='older.mp4',status='needs_review')
        upload.save_json(self.state_path,{'old_unknown':old})
        _,button,prepare,close,read=self.pipeline()
        self.assertNotIn('fb14',[call.args[1]['account'] for call in prepare.call_args_list])
        self.assertEqual(upload.read_json(self.state_path,{})['old_unknown'],old)
        self.assertFalse(self.videos['fb14'].with_suffix('.txt').exists())

    def test_duplicate_url_with_excluded_page_is_still_rejected(self):
        self.config['targets'][2]['url']=self.new['url']
        upload.save_json(upload.CONFIG,self.config)
        _,button,prepare,close,read=self.pipeline()
        self.assertNotIn('fb14',[call.args[1]['account'] for call in prepare.call_args_list])

    def test_plan_only_is_read_only_and_ai_or_incompatible_core_are_required_for_run(self):
        state=self.state_path.read_bytes()
        with patch.object(upload,'run_entry') as publish:
            self.assertEqual(direct.run(),0)
        publish.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(),state)
        self.assertEqual(self.custom.with_suffix('.txt').read_bytes(),self.custom_caption)
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        with self.assertRaises(ValueError):direct.run(True)
        with patch.object(upload,'VERSION','2.31'):
            with self.assertRaises(ValueError):direct.run(True,'off')


if __name__=='__main__':unittest.main()
