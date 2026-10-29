import copy
import os
import time
import zipfile
import unittest
from unittest.mock import patch

import fb_upload as upload
import resume_confirmed_other_failures as resume
from test_retry_other_before_post import BeforePostRepairTests


class ResumeConfirmedFailuresTests(unittest.TestCase):
    def setUp(self):
        self.fixture=BeforePostRepairTests()
        self.fixture.setUp()
        self.__dict__.update(self.fixture.__dict__)
        self.pairs=[('fb01','page01'),('fb06','page01'),('fb09','personal'),('fb23','personal')]
        self.bound={pair:self.paths[pair][1] for pair in self.pairs}
        self.stack.enter_context(patch.object(resume,'BOUND',self.bound))
        self.stack.enter_context(patch.object(resume,'SOURCE',self.source))
        state=upload.read_json(self.root/'logs/publish_state.json',{})
        for pair in self.pairs[:2]:state[self.paths[pair][1]]['status']='needs_review'
        upload.save_json(self.root/'logs/publish_state.json',state)

    def tearDown(self):
        self.fixture.tearDown()

    def execute(self,unknown=False,failed=()):
        from unittest.mock import MagicMock
        button=MagicMock();browser=MagicMock();browser.pages=[MagicMock()]
        def prepare(page,entry,video,caption):
            if (entry['account'],entry['target']) in failed:
                raise RuntimeError('subtree intercepts pointer events: new failure')
            return button,{}
        with patch.object(upload,'check_identity'),patch('retry_current_verified_absent.close_selected_window'), \
             patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'prepare_reel',side_effect=prepare),patch.object(upload,'recheck_publish_identity'), \
             patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',return_value='Your reel is published.',
                 side_effect=upload.ReceiptNeedsReview('receipt timeout') if unknown else None), \
             patch('builtins.input',side_effect=AssertionError('no prompts')):
            result=resume.run(True,True,self.desktop,True)
        return result,button

    def test_exact_user_success_and_absence_plus_before_post_failures(self):
        original=upload.read_json(self.root/'logs/publish_state.json',{})
        result,button=self.execute()
        self.assertEqual(result,0);self.assertEqual(button.click.call_count,3)
        state=upload.read_json(self.root/'logs/publish_state.json',{})
        for pair in self.pairs:self.assertEqual(state[self.paths[pair][1]]['status'],'published')
        for pair,(video,key) in self.paths.items():
            if pair not in self.pairs:self.assertEqual(state[key],original[key])
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        claims=upload.read_json(self.root/'logs/verified-current-absence-claims.json',{})
        self.assertEqual(len(claims),3)
        for claim in claims.values():self.assertEqual(claim['phase'],'consumed')
        video,key=self.paths[('fb23','personal')]
        self.assertEqual((video.parent.parent/'completed/original.txt').read_bytes(),self.custom)
        _,button=self.execute();button.click.assert_not_called()

    def test_unknown_receipts_preserve_guard_and_cannot_reuse_user_absence(self):
        result,button=self.execute(unknown=True)
        self.assertEqual(result,3);self.assertEqual(button.click.call_count,3)
        saved=(self.root/'logs/publish_state.json').read_bytes()
        _,button=self.execute();button.click.assert_not_called()
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),saved)

    def test_latest_attempt_wins_over_stale_original_and_old_core_error(self):
        path,report=resume.confirmations.load_expanded_report(self.source)
        row=next(r for r in report['rows'] if r['account']=='fb09')
        record=upload.read_json(self.root/'logs/publish_state.json',{})[row['key']]
        core=self.root/'logs'/('review-'+row['key'][:12]+'-error.txt')
        core.write_text('old core error')
        os.utime(core,(time.time()-50,time.time()-50))
        report['repair_results']=[dict(key=row['key'],attempted_at=resume.now(),error='new preflight error')]
        self.assertEqual(resume.latest_error(path,report,row,record),('new preflight error','repair_results/latest'))
        core.write_text('newer core error')
        os.utime(core,(time.time()+1,time.time()+1))
        self.assertEqual(resume.latest_error(path,report,row,record)[0],'newer core error')

    def test_source_key_mismatch_and_missing_assertions_change_nothing(self):
        state=(self.root/'logs/publish_state.json').read_bytes()
        with self.assertRaises(ValueError):resume.run(False,True,self.desktop)
        bad=dict(self.bound);bad[('fb01','page01')]='a'*64
        with patch.object(resume,'BOUND',bad):
            with self.assertRaises(ValueError):resume.run(True,True,self.desktop)
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),state)

    def test_failure_keeps_full_reason_and_only_curated_evidence(self):
        result,button=self.execute(failed={('fb09','personal')})
        self.assertEqual(result,3);self.assertEqual(button.click.call_count,2)
        history=upload.read_json(self.root/'logs/publication_failure_history.json',{})
        fb09=[e for e in history['events'] if e['account']=='fb09' and e['phase']=='after_retry'][-1]
        self.assertIn('挡住',fb09['reason']);self.assertIn('个人号',fb09['prevention'])
        with zipfile.ZipFile(sorted(self.desktop.glob('*.zip'))[-1]) as archive:
            self.assertIn('fb09-personal-latest-error.txt',archive.namelist())
            self.assertIn('new failure',archive.read('fb09-personal-latest-error.txt').decode())
            self.assertNotIn('publish_state.json',archive.namelist())
            self.assertFalse(any(name.endswith('.mp4') for name in archive.namelist()))
