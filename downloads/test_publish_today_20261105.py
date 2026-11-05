import contextlib,copy,os,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch,MagicMock
import publish_today_20261105 as today
import test_retry_nov04_two_and_comment_20261105 as fixture
import fb_upload as upload


class TodayNov05Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.TwoRetryTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.f.root;self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        clock=self.stack.enter_context(patch.object(today,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,5,5,tzinfo=timezone.utc)
        clock=self.stack.enter_context(patch.object(today.priority,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,5,5,tzinfo=timezone.utc)
        self.state=copy.deepcopy(self.f.state)
        for job in self.f.other:self.state[job['key']]['status']='published'
        self.state[self.f.selected[0]['key']].update(status='needs_review',post_intent_at='2026-11-05T11:00:00+08:00')
        self.state[self.f.selected[1]['key']].update(status='published',comment_status='sent')
        upload.save_json(self.f.f.state_path,self.state)
    def test_confirms_only_original_alice_video_and_keeps_prycken_comment_and_claims(self):
        with patch.object(upload,'run_entry',side_effect=AssertionError('no old uploads')),patch.object(today.daily,'backfill',side_effect=AssertionError('no old comments')):today.confirm_previous()
        state=upload.read_json(self.f.f.state_path,{})
        for key,row in self.state.items():
            if key!=self.f.selected[0]['key']:self.assertEqual(state[key],row)
        row=state[self.f.selected[0]['key']];self.assertEqual(row['status'],'published');self.assertTrue(Path(row['archived_video']).is_file())
        self.assertEqual(row['confirmation_method'],'user_confirmed_nov04_two_published_before_nov05')
        self.assertEqual(self.f.old_path.read_bytes(),self.f.old_bytes);self.assertEqual(self.f.f.auto_path.read_bytes(),self.f.f.auto)
        self.assertEqual(upload.CONFIG.read_bytes(),self.f.f.config)
        before=copy.deepcopy(state);today.confirm_previous();self.assertEqual(upload.read_json(self.f.f.state_path,{}),before)
    def fresh(self):
        jobs=[]
        for i,old in enumerate(self.f.f.jobs[:2]):
            entry=today.daily.configured(old);file=upload.inbox_for(entry)/'nov05-fresh.mp4';file.write_bytes(('Nov5 fresh '+str(i)).encode())
            if i==0:file.with_suffix('.txt').write_text('Nov5 existing custom caption')
            jobs.append(file)
        (self.root/'common_caption_today.txt').write_text('Previous saved caption')
        return jobs
    def test_today_freeze_caption_priority_normal_scope_and_same_pointer_resume(self):
        files=self.fresh();captions=files[0].with_suffix('.txt').read_bytes();seen=[];original=upload.launch_context;original_report=today.priority.comment_report
        def execute(date,real):
            self.assertEqual(date,'2026-11-05');self.assertTrue(real)
            path,value=today.priority.prepare(date);seen.append((path,value))
            self.assertEqual(len(value['payload']['jobs']),2);self.assertFalse(value['payload']['ai_label'])
            self.assertEqual({j['filename'] for j in value['payload']['jobs']},{'nov05-fresh.mp4'})
            self.assertEqual({j['caption_text'] for j in value['payload']['jobs']},{'Nov5 existing custom caption','Previous saved caption'})
            self.assertEqual(value['local_file_input_mode'],today.local.VERSION)
            self.assertEqual(upload.read_json(self.f.f.state_path,{})[self.f.selected[0]['key']]['status'],'published')
            return 3
        with patch.object(today.priority,'execute',side_effect=execute):
            self.assertEqual(today.execute(True),3)
            (files[0].parent/'added-later.mp4').write_bytes(b'later new file')
            self.assertEqual(today.execute(True),3)
        self.assertEqual(seen[0],seen[1]);self.assertEqual(files[0].with_suffix('.txt').read_bytes(),captions)
        self.assertIs(upload.launch_context,original);self.assertIs(today.priority.comment_report,original_report)
        self.assertTrue(all(j['account'] not in {'fb16','fb18','fb21','fb24','fb25','fb26'} for j in seen[0][1]['payload']['jobs']))
    def test_failed_large_file_selfcheck_starts_no_upload_and_keeps_pointer_for_resume(self):
        self.fresh();original=upload.launch_context;self.f.f.check.side_effect=RuntimeError('file selfcheck failed')
        def execute(date,real):today.priority.prepare(date);raise AssertionError('must stop before upload')
        with patch.object(today.priority,'execute',side_effect=execute),patch.object(upload,'run_entry') as post:
            with self.assertRaises(RuntimeError):today.execute(True)
        post.assert_not_called();self.assertIs(upload.launch_context,original)
        self.assertTrue((self.root/'logs/priority-batch-2026-11-05.json').is_file())
    def test_explicit_non_ai_and_current_date_required_before_any_confirmation(self):
        with patch.object(today,'confirm_previous') as confirm:
            with self.assertRaises(ValueError):today.execute(False)
            today.datetime.now.return_value=datetime(2026,11,6,5,tzinfo=timezone.utc)
            with self.assertRaises(ValueError):today.execute(True)
        confirm.assert_not_called()
    def test_today_lookup_pending_preserves_publication_and_original_attempts(self):
        self.fresh();today.confirm_previous();path,value=today.priority.prepare('2026-11-05');job=value['payload']['jobs'][0]
        state=upload.read_json(self.f.f.state_path,{});state[job['key']]=dict(status='published',comment_status='manual_required')
        upload.save_json(self.f.f.state_path,state)
        attempts=[dict(key=job['key'],action='finished')];upload.save_json(path.with_name(path.stem+'-results.json'),dict(manifest=path.name,attempts=attempts))
        rows=[dict(key=job['key'],status='manual_required',error='自动定位暂未完成：缺少唯一匹配')]
        today.comment_report(path,value,rows)
        current=upload.read_json(self.f.f.state_path,{})[job['key']]
        self.assertEqual(current['status'],'published');self.assertEqual(current['comment_status'],'lookup_pending')
        self.assertEqual(upload.read_json(path.with_name(path.stem+'-results.json'),{})['attempts'],attempts)
