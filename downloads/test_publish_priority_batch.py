import contextlib,copy,io,os,tempfile,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import publish_priority_batch as priority
import scheduled_material_batch as batch
import fb_upload as upload
import test_scheduled_material_batch as fixtures


class PriorityBatchTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ScheduledMaterialTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.now=datetime(2026,10,29,9,1,tzinfo=timezone.utc)
        self.fx.stack.enter_context(patch.object(priority,'datetime',wraps=datetime))
        priority.datetime.now.return_value=self.now
    def prepare(self):return priority.prepare('2026-10-29')
    def test_new_batch_freezes_caption_priority_and_resume_keeps_the_same_jobs(self):
        path,value=self.prepare()
        self.assertEqual(len(value['payload']['jobs']),4)
        self.assertEqual(value['comment_timing'],priority.TIMING)
        self.assertFalse(value['payload']['ai_label'])
        custom=next(j for j in value['payload']['jobs'] if j['account']=='fb23')
        self.assertIn('My original custom caption',custom['caption_text'])
        fallback=next(j for j in value['payload']['jobs'] if j['account']=='fb01')
        self.assertEqual(fallback['caption_text'],'Saved old caption\n#Prycken')
        new=self.fx.videos[('fb01','page01')].parent/'added-later.mp4';new.write_bytes(b'later media')
        same_path,same_value=self.prepare();self.assertEqual(same_path,path);self.assertEqual(same_value,value)
        self.assertFalse(list(self.fx.root.rglob('*.csv')))
    def test_new_batch_excludes_unstarted_old_frozen_media_and_preserves_custom_txt(self):
        old_path,_=self.fx.freeze();priority.datetime.now.return_value=self.now+timedelta(days=1)
        new=self.fx.videos[('fb01','page01')].parent/'fresh.mp4';new.write_bytes(b'todays new bytes')
        new.with_suffix('.txt').write_text('Today custom caption')
        path,value=priority.prepare('2026-10-30')
        self.assertEqual([j['filename'] for j in value['payload']['jobs']],['fresh.mp4'])
        self.assertEqual(value['payload']['jobs'][0]['caption_text'],'Today custom caption')
        self.assertTrue(any(old_path.name in i['reason'] for i in value['issues']))
    def test_runner_orders_all_uploads_then_retry_then_comments_without_immediate_sends(self):
        path,value=self.prepare();value['payload']['start']=(self.now-timedelta(seconds=1)).isoformat();events=[]
        def finish(*args,**kwargs):
            events.append('uploads')
            state={j['key']:dict(status='published',comment_status='deferred') for j in value['payload']['jobs']}
            upload.save_json(self.fx.state_path,state)
        def comments(*args,**kwargs):
            events.append('comments')
            self.assertEqual(events,['uploads','retry','comments'])
            self.assertTrue(kwargs['future_only'])
        with patch.object(priority,'prepare',return_value=(path,value)),patch.object(batch,'run',side_effect=finish) as run,patch.object(priority.retry,'run',side_effect=lambda *a:events.append('retry')),patch.object(priority.daily,'backfill',side_effect=comments),patch.object(priority.comment_retry,'run',side_effect=lambda *a,**k:events.append('comment-retry')),patch.object(batch,'results',return_value=[]),patch.object(priority.actual,'make_finder',return_value=object()):
            self.assertEqual(priority.execute('2026-10-29',True),3)
        self.assertEqual(events,['uploads','retry','comments'])
        self.assertEqual(run.call_args.kwargs,dict(defer_comments=True,resume=True))
    def test_resume_preserves_attempt_history_and_only_runs_unattempted_jobs(self):
        path,value=self.prepare();first=value['payload']['jobs'][0]
        attempt=dict(key=first['key'],action='manual_required',error='Chrome profile busy')
        upload.save_json(path.with_name(path.stem+'-results.json'),dict(manifest=path.name,attempts=[attempt]))
        for f in self.fx.root.rglob('*.txt'):os.utime(f,(time.time()-180,time.time()-180))
        calls=[]
        def finish(entry,state,state_path,*args,**kwargs):
            key=kwargs['expected_job_key'];calls.append(key);self.assertTrue(kwargs['defer_comments'])
            state[key]=dict(account=entry['account'],target=entry['target'],status='published',comment_status='deferred')
            upload.save_json(state_path,state)
        with patch.object(batch,'datetime',wraps=datetime) as clock,patch.object(batch,'close_selected_window'),patch.object(upload,'run_entry',side_effect=finish):
            clock.now.return_value=self.now+timedelta(minutes=2)
            batch.run(path,defer_comments=True,resume=True)
            batch.run(path,defer_comments=True,resume=True)
        self.assertEqual(len(calls),len(value['payload']['jobs'])-1);self.assertNotIn(first['key'],calls)
        report=upload.read_json(path.with_name(path.stem+'-results.json'),{})
        self.assertEqual(report['attempts'][0],attempt);self.assertEqual(len(report['attempts']),len(value['payload']['jobs']))
    def test_invalid_resume_history_and_pointer_fail_before_upload(self):
        path,value=self.prepare()
        upload.save_json(path.with_name(path.stem+'-results.json'),dict(manifest=path.name,attempts=[dict(key='outside-job',action='finished')]))
        with patch.object(batch,'datetime',wraps=datetime) as clock,patch.object(upload,'run_entry') as run:
            clock.now.return_value=self.now+timedelta(minutes=2)
            with self.assertRaises(ValueError):batch.run(path,defer_comments=True,resume=True)
        run.assert_not_called()
        pointer=self.fx.root/'logs/priority-batch-2026-10-29.json';upload.save_json(pointer,dict(date='2026-10-29',manifest='../other.json'))
        with self.assertRaises(ValueError):self.prepare()
    def test_old_date_and_unconfirmed_footage_are_rejected(self):
        with self.assertRaises(ValueError):priority.execute('1900-01-01',True)
        with self.assertRaises(ValueError):priority.execute('2026-10-29',False)
