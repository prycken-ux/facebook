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

    def execute(self,unknown=False,failed=(),confirmed=(),occupied=False,fresh=False):
        from unittest.mock import MagicMock
        button=MagicMock();browser=MagicMock();browser.pages=[MagicMock()]
        def prepare(page,entry,video,caption):
            if (entry['account'],entry['target']) in failed:
                raise RuntimeError('subtree intercepts pointer events: new failure')
            return button,{}
        with patch.object(upload,'check_identity',side_effect=RuntimeError('fb01 的 Chrome 资料仍被占用') if occupied else None),patch('retry_current_verified_absent.close_selected_window'), \
             patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'prepare_reel',side_effect=prepare),patch.object(upload,'recheck_publish_identity'), \
             patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',return_value='Your reel is published.',
                 side_effect=upload.ReceiptNeedsReview('receipt timeout') if unknown else None), \
             patch('builtins.input',side_effect=AssertionError('no prompts')):
            result=resume.run(True,True,self.desktop,True,also_verified_published=confirmed,fresh_fb01_verification=fresh)
        return result,button

    def test_new_user_confirmation_records_fb09_fb23_and_only_posts_fb01(self):
        confirmed=(('fb09','personal'),('fb23','personal'))
        state=upload.read_json(self.root/'logs/publish_state.json',{})
        for pair in confirmed:state[self.paths[pair][1]]['status']='needs_review'
        upload.save_json(self.root/'logs/publish_state.json',state)
        result,button=self.execute(confirmed=confirmed)
        self.assertEqual(result,0);button.click.assert_called_once()
        state=upload.read_json(self.root/'logs/publish_state.json',{})
        for pair in confirmed:
            record=state[self.paths[pair][1]]
            self.assertEqual(record['status'],'published')
            self.assertEqual(record['confirmation_method'],'user_confirmed_existing_post_no_link')
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        _,button=self.execute(confirmed=confirmed)
        button.click.assert_not_called()

    def test_fb01_occupied_never_removes_guard_but_keeps_new_success_confirmations(self):
        original=upload.read_json(self.root/'logs/publish_state.json',{})
        result,button=self.execute(confirmed=(('fb09','personal'),('fb23','personal')),occupied=True)
        self.assertEqual(result,3);button.click.assert_not_called()
        state=upload.read_json(self.root/'logs/publish_state.json',{})
        key=self.paths[('fb01','page01')][1]
        self.assertEqual(state[key],original[key])
        for pair in [('fb06','page01'),('fb09','personal'),('fb23','personal')]:
            self.assertEqual(state[self.paths[pair][1]]['status'],'published')
        self.assertFalse((self.root/'logs/verified-current-absence-claims.json').exists())

    def test_cannot_expand_success_confirmation_to_fb01_or_other_targets(self):
        original=(self.root/'logs/publish_state.json').read_bytes()
        for pairs in [(('fb01','page01'),),(('fb10','personal'),),(('fb09','personal'),('fb09','personal'))]:
            with self.assertRaises(ValueError):resume.run(True,True,self.desktop,also_verified_published=pairs)
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),original)

    def test_latest_fb01_absence_can_retry_once_after_old_claim_is_consumed(self):
        confirmed=(('fb09','personal'),('fb23','personal'))
        result,button=self.execute(unknown=True,confirmed=confirmed)
        self.assertEqual(result,3);button.click.assert_called_once()
        result,button=self.execute(confirmed=confirmed)
        self.assertEqual(result,3);button.click.assert_not_called()
        result,button=self.execute(confirmed=confirmed,fresh=True)
        self.assertEqual(result,0);button.click.assert_called_once()
        result,button=self.execute(confirmed=confirmed,fresh=True)
        self.assertEqual(result,0);button.click.assert_not_called()
        claims=upload.read_json(self.root/'logs/verified-current-absence-claims.json',{})
        self.assertEqual(len(claims),2)

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


class CurrentStatusExplanationTests(unittest.TestCase):
    def test_success_does_not_display_old_receipt_error_as_current_failure(self):
        reason,action=resume.explanation(dict(status='published',review_reason='publication_receipt_timeout'),'120秒内未识别到成功回执')
        self.assertIn('已确认发布成功',reason)
        self.assertNotIn('待核实',reason)
        self.assertIn('不重复',action)

    def test_current_profile_occupancy_is_not_overridden_by_older_receipt_reason(self):
        reason,action=resume.explanation(dict(status='needs_review',review_reason='publication_receipt_timeout'),
            'fb01 的 Chrome 资料仍被占用（进程 PID：15320）。本次尚未启动浏览器或选择视频。')
        self.assertIn('被占用',reason)
        self.assertIn('本次未启动发布',reason)
        self.assertNotIn('回执',reason)

    def test_submitted_unknown_still_requires_actual_verification(self):
        reason,action=resume.explanation(dict(status='needs_review',review_reason='publication_receipt_timeout'),
            '已点击发布，120秒内未识别到成功回执')
        self.assertIn('待核实',reason)
        self.assertIn('禁止自动再次发布',action)
