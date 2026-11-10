import copy,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import publish_today_20261110 as today
import fb_upload as upload
import test_scheduled_material_batch as fixtures


class Nov10DirectTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ScheduledMaterialTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        for module in (today,today.priority):
            clock=self.f.stack.enter_context(patch.object(module,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,10,8,tzinfo=timezone.utc)
        with today.locked():today.preferences.save_authorized()
        _,old=today.batch.freeze('2026-11-06','17:00',True,today.priority.daily.COMMENT,datetime(2026,11,6,8,tzinfo=timezone.utc),report_format='text')
        self.old_state={old['payload']['jobs'][0]['key']:dict(status='published',comment_status='sent',account='fb01',target='page01'),
                        old['payload']['jobs'][1]['key']:dict(status='needs_review',post_intent_at='2026-11-06T18:00:00+08:00',account='fb10',target='page01')}
        upload.save_json(self.f.state_path,self.old_state)
        self.fresh=[]
        for pair in [('fb01','page01'),('fb10','page01')]:
            video=self.f.videos[pair].parent/'nov10.mp4';video.write_bytes(('fresh Nov10 '+str(pair)).encode());self.fresh.append(video)
        self.fresh[0].with_suffix('.txt').write_text('Replace this old generic caption')
        self.claims=self.f.root/'logs/automatic_before_post_retry_claims.json';upload.save_json(self.claims,dict(schema='automatic-before-post-retry-claims-v1',jobs={'old claim':dict(used=True)}));self.claim_bytes=self.claims.read_bytes()
        self.f.stack.enter_context(patch.object(today.workflow,'register',side_effect=AssertionError('no task scheduler')))
        self.f.stack.enter_context(patch.object(today.workflow.previous,'execute',side_effect=AssertionError('no historic confirmation')))
    def preserved(self):
        self.assertEqual(upload.read_json(self.f.state_path,{}),self.old_state)
        if today.preferences.load('2026-11-10').get('account_resumption'):
            self.assertEqual(today.batch.excluded_accounts('2026-11-10'),set(today.preferences.EXCLUDED));self.assertEqual(today.batch.excluded_accounts('2026-11-11'),set())
        self.assertEqual(self.claims.read_bytes(),self.claim_bytes);self.assertEqual(upload.CONFIG.read_bytes(),self.f.config_before)
    def test_only_nov10_fresh_files_use_exact_caption_and_old_unknowns_remain_untouched(self):
        def worker(path):
            value=upload.read_json(path,{})
            self.assertEqual(value['payload']['date'],'2026-11-10');self.assertFalse(value['payload']['ai_label'])
            self.assertEqual(len(value['payload']['jobs']),2);self.assertEqual({j['filename'] for j in value['payload']['jobs']},{'nov10.mp4'})
            self.assertEqual({j['caption_text'] for j in value['payload']['jobs']},{today.preferences.CAPTION})
            self.assertEqual(set(value['payload']['excluded_accounts']),{'fb16','fb17','fb18','fb21'})
            self.assertEqual(value['scheduled_priority_runner'],today.workflow.VERSION)
            return 3
        with patch.object(today.workflow,'run',side_effect=worker):self.assertEqual(today.execute(True),3)
        self.preserved();self.assertEqual(self.fresh[0].with_suffix('.txt').read_text().strip(),today.preferences.CAPTION)
    def test_same_command_resumes_frozen_source_without_adding_later_files_or_resetting_records(self):
        with patch.object(today.workflow,'run',return_value=3) as worker:
            today.execute(True);first=worker.call_args.args[0];before=first.read_bytes()
            (self.fresh[0].parent/'later.mp4').write_bytes(b'later fresh video')
            today.execute(True)
            self.assertEqual(worker.call_args.args[0],first);self.assertEqual(first.read_bytes(),before)
        self.preserved()
    def test_active_worker_blocks_before_new_captions_or_uploads(self):
        lock=self.f.root/'logs/upload.lock';lock.write_text('12345');before=self.fresh[0].with_suffix('.txt').read_bytes()
        with self.assertRaises(RuntimeError):today.execute(True)
        self.assertEqual(self.fresh[0].with_suffix('.txt').read_bytes(),before);self.preserved()
    def test_current_date_explicit_real_footage_and_caption_proof_required(self):
        with patch.object(today.workflow,'run') as worker:
            with self.assertRaises(ValueError):today.execute(False)
            with patch.object(today.preferences,'CAPTION','wrong approved text'):
                with self.assertRaises(ValueError):today.execute(True)
            today.datetime.now.return_value=datetime(2026,11,11,8,tzinfo=timezone.utc)
            with self.assertRaises(ValueError):today.execute(True)
        worker.assert_not_called();self.preserved()
    def test_installed_browser_strategy_cannot_be_silently_replaced(self):
        path,value=today.priority.prepare(today.DATE);value['browser_launch_mode']='another browser';upload.save_json(path,value)
        with patch.object(today.workflow,'run') as worker:
            with self.assertRaises(ValueError):today.execute(True)
        worker.assert_not_called();self.preserved()
    def test_foreground_entry_cleans_only_stale_locks_and_records_console_output(self):
        with patch.object(today.sys,'platform','win32'),patch.object(today,'recover_locks') as recover,patch.object(today,'execute',return_value=3) as execute:
            self.assertEqual(today.start(self.f.root,True),3)
        recover.assert_called_once_with(self.f.root);execute.assert_called_once_with(True)
        self.assertTrue((self.f.root/'logs/direct-priority-2026-11-10.log').is_file());self.preserved()
