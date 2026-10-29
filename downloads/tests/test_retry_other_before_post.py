import copy
import os
import time
import unittest
from unittest.mock import MagicMock,patch

import fb_upload as upload
import retry_other_before_post as retry
import test_audit_other_publication as fixtures


class BeforePostRepairTests(fixtures.FailureAuditTests):
    def setUp(self):
        super().setUp()
        report=upload.read_json(self.source_path,{})
        self.custom=b'\xef\xbb\xbfFb23 original custom caption\r\nKeep this text\r\n'
        for row in report['rows']:
            pair=(row['account'],row['target'])
            video,key=self.paths[pair]
            self.state[key]['ai_label_requested']=False
            if pair==('fb23','personal'):
                video.with_suffix('.txt').write_bytes(self.custom)
                row.update(caption_policy='preserve_existing',caption_text=self.custom.decode('utf-8-sig').replace('\r\n','\n').strip())
            else:
                video.with_suffix('.txt').write_text('common caption')
                row.update(caption_policy='saved_common',caption_text='common caption')
            for path in (video,video.with_suffix('.txt')):os.utime(path,(time.time()-120,time.time()-120))
        (self.root/'common_caption_today.txt').write_text('common caption')
        self.rows=copy.deepcopy(report['rows'])
        upload.save_json(self.source_path,report)
        upload.save_json(self.root/'logs/publish_state.json',self.state)
        self.targets=self.failed[:-1]

    def pipeline(self,targets=None,unknown=False,security=False):
        button=MagicMock();browser=MagicMock();browser.pages=[MagicMock()]
        def identity(entry):
            if security and entry['account']=='fb23':raise upload.AccountActionRequired('Advanced Protection requires owner')
        with patch.object(upload,'check_identity',side_effect=identity) as check, \
             patch('retry_current_verified_absent.close_selected_window'), \
             patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'prepare_reel',return_value=(button,{})) as prepare, \
             patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'), \
             patch.object(upload,'wait_for_receipt',return_value='Your reel is published.',
                side_effect=upload.ReceiptNeedsReview('new unknown') if unknown else None), \
             patch('builtins.input',side_effect=AssertionError('must not prompt')) as read:
            result=retry.run(self.source,targets or self.targets,True)
        return result,button,prepare,read,check

    def test_repair_retries_only_four_selected_before_post_failures_once(self):
        original=copy.deepcopy(self.state)
        result,button,prepare,read,check=self.pipeline()
        self.assertEqual(result,0)
        self.assertEqual(button.click.call_count,4)
        read.assert_not_called()
        self.assertEqual({(call.args[1]['account'],call.args[1]['target']) for call in prepare.call_args_list},set(self.targets))
        state=upload.read_json(self.root/'logs/publish_state.json',{})
        for pair,(video,key) in self.paths.items():
            if pair in self.targets:self.assertEqual(state[key]['status'],'published')
            else:self.assertEqual(state[key],original[key])
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        assertion=upload.read_json(next((self.root/'backups').glob('verified-current-absent-*/assertion.json')), {})
        self.assertEqual(assertion['assertion'],'ledger_failure_before_post')

    def test_original_unknown_or_new_unknown_is_never_retried_under_before_post_mode(self):
        result,button,prepare,read,check=self.pipeline(targets=[self.confirmed[0]])
        self.assertEqual(result,3)
        button.click.assert_not_called()
        check.assert_not_called()
        result,button,prepare,read,check=self.pipeline(unknown=True)
        self.assertEqual(result,3)
        self.assertEqual(button.click.call_count,4)
        saved=(self.root/'logs/publish_state.json').read_bytes()
        result,button,prepare,read,check=self.pipeline()
        self.assertEqual(result,3)
        button.click.assert_not_called()
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),saved)

    def test_fb23_security_requirement_never_removes_guard_or_creates_another_task(self):
        before=(self.root/'logs/publish_state.json').read_bytes()
        result,button,prepare,read,check=self.pipeline(targets=[('fb23','personal')],security=True)
        self.assertEqual(result,3)
        button.click.assert_not_called()
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),before)
        video,_=self.paths[('fb23','personal')]
        self.assertEqual(video.with_suffix('.txt').read_bytes(),self.custom)

    def test_owner_resolved_fb23_can_retry_using_exact_original_custom_caption(self):
        result,button,prepare,read,check=self.pipeline(targets=[('fb23','personal')])
        self.assertEqual(result,0)
        button.click.assert_called_once()
        video,key=self.paths[('fb23','personal')]
        self.assertEqual((video.parent.parent/'completed/original.txt').read_bytes(),self.custom)
        self.assertEqual(prepare.call_args.args[3],self.custom.decode('utf-8-sig').replace('\r\n','\n').strip())


if __name__=='__main__':unittest.main()
