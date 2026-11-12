import copy
import os
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import MagicMock,patch

import publish_today_20261112 as app
from test_retry_three_personal_20261112 import ThreePersonalRetryTests


class Nov12NewVideosTests(unittest.TestCase):
    def setUp(self):
        self.base=ThreePersonalRetryTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.root=self.base.root;self.stack=self.base.stack
        self.stack.enter_context(patch.object(app,'SOURCE_PREFIX',self.base.value['sha256'][:8]))
        self.clock=self.stack.enter_context(patch.object(app,'datetime',wraps=datetime));self.clock.now.return_value=datetime(2026,11,12,4,tzinfo=timezone.utc)
        self.config=app.upload.read_json(app.upload.CONFIG,{})
        self.expected={}
        for entry in self.config['targets']:
            if entry['account'] not in app.ALLOWED:continue
            if entry['account'] in {'fb17','fb18','fb21'} and entry['target']=='personal':
                video=app.upload.inbox_for(entry)/self.base.records[entry['account']]['filename']
            else:video=app.upload.inbox_for(entry)/('today-'+entry['account']+'-'+entry['target']+'.mp4')
            video.parent.mkdir(parents=True,exist_ok=True);video.write_bytes(('Nov12 new footage '+entry['account']+entry['target']).encode())
            self.expected[(entry['account'],entry['target'])]=(video.name,app.old.batch.file_hash(video))
        self.assertEqual(len(self.expected),44)
        for n in range(25,75):
            account=f'fb{n:02d}';row=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',name=account,url='https://www.facebook.com/profile.php?id='+str(99000+n))
            self.config['targets'].append(row)
            video=app.upload.inbox_for(row)/'future.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'new account video must stay')
        app.upload.save_json(app.upload.CONFIG,self.config)
        self.state_before=app.upload.read_json(self.root/'logs/publish_state.json',{})
        self.original_before=self.base.path.read_bytes()
        self.normal_pointer=self.root/'logs/priority-batch-2026-11-12.json';self.pointer_before=self.normal_pointer.read_bytes()
        self.owner=self.stack.enter_context(patch.object(app.personal,'discover',side_effect=self.base.discover))
        for file in self.root.rglob('*'):
            if file.is_file() and file.suffix in {'.mp4','.txt'}:os.utime(file,(self.clock.now.return_value.timestamp()-180,)*2)

    def core(self,unknown=False):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock();events=[];active={}
        button.click.side_effect=lambda **k:events.append(('post',active['pair']))
        def prepare(page,entry,video,caption,**kwargs):
            active['pair']=entry['account'],entry['target']
            self.assertIn(active['pair'],self.expected)
            self.assertEqual(app.old.batch.file_hash(video),self.expected[active['pair']][1])
            return button,{}
        def run_video(path,value,retry=False):
            self.assertFalse(retry)
            for job in value['payload']['jobs']:
                file=self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']
                if file.is_file():os.utime(file,(self.clock.now.return_value.timestamp()-180,)*2)
                if file.with_suffix('.txt').is_file():os.utime(file.with_suffix('.txt'),(self.clock.now.return_value.timestamp()-180,)*2)
            with app.personal.launcher(value):app.old.batch.run(path,defer_comments=True,resume=True)
        def comments(value,*a,**kwargs):
            events.append(('comments',len(value['payload']['jobs'])))
            self.assertTrue(all(e[0]=='post' for e in events[:-1]))
            state=app.upload.read_json(self.root/'logs/publish_state.json',{})
            for job in value['payload']['jobs']:
                if state[job['key']]['status']=='published':state[job['key']]['comment_status']='sent'
            app.upload.save_json(self.root/'logs/publish_state.json',state)
        with patch.object(app,'run_video',side_effect=run_video),patch.object(app.old.normal,'launcher_for_jobs',return_value=lambda *a:browser), \
             patch('playwright.sync_api.sync_playwright'),patch.object(app.old.batch,'close_selected_window'),patch.object(app.upload,'prepare_reel',side_effect=prepare), \
             patch.object(app.upload,'recheck_publish_identity'),patch.object(app.upload,'install_receipt_watch'), \
             patch.object(app.upload,'wait_for_receipt',side_effect=app.upload.ReceiptNeedsReview('unknown') if unknown else None,return_value='Your reel is published.'), \
             patch('safe_video_comments.resolve_published_link',return_value=('https://www.facebook.com/reel/9001','fresh_success_view_reel_link')), \
             patch.object(app.old.priority.daily,'backfill',side_effect=comments),patch.object(app.old.priority.comment_retry,'run',return_value=[]):
            result=app.execute(True)
        return result,button,events

    def test_all_44_today_targets_publish_only_new_bytes_and_preserve_all_50_new_accounts(self):
        result,button,events=self.core()
        self.assertEqual(result,0);self.assertEqual(button.click.call_count,44)
        self.assertEqual({e[1] for e in events if e[0]=='post'},set(self.expected))
        state=app.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in self.state_before.items():self.assertEqual(state[key],row)
        for n in range(25,75):self.assertEqual((self.root/f'videos/fb{n:02d}/personal/inbox/future.mp4').read_bytes(),b'new account video must stay')
        self.assertEqual(self.base.path.read_bytes(),self.original_before)
        self.assertEqual(self.normal_pointer.read_bytes(),self.pointer_before)
        self.assertFalse((self.root/'logs/nov11-three-personal-recovery-20261112.json').exists())
        self.assertEqual({c.args[0] for c in self.owner.call_args_list},{'fb17','fb18','fb21','fb24'})
        result,button,events=self.core()
        self.assertEqual(result,0);button.click.assert_not_called()

    def test_unknown_receipts_and_cancelled_old_personal_materials_are_not_reposted(self):
        result,button,events=self.core(unknown=True)
        self.assertEqual(result,3);self.assertEqual(button.click.call_count,44)
        result,button,events=self.core()
        self.assertEqual(result,3);button.click.assert_not_called()

    def test_snapshot_keeps_later_additions_out_and_all_old_recorded_bytes_out(self):
        with app.old.locked():
            parent,original=app.old_sources();app.ready_personals(parent)
            path,control=app.today_controller(original)
            records=control['payload']['records']
            self.assertEqual(len(records),44)
            self.assertEqual(control['payload']['cancelled_old_personal_retries'],['fb17','fb18','fb21'])
            extra=self.root/'videos/fb01/page01/inbox/added-later.mp4';extra.write_bytes(b'late addition')
            app.prepare_wave(path,control,set())
            plans=app.load_today_plans(control)
        self.assertEqual(sum(len(v['payload']['jobs']) for p,v in plans),44)
        self.assertTrue(all(j['filename']!='added-later.mp4' for p,v in plans for j in v['payload']['jobs']))

    def test_partial_setup_can_add_only_previously_snapshotted_unplanned_target_on_resume(self):
        with app.old.locked():
            parent,original=app.old_sources();app.ready_personals(parent)
            path,control=app.today_controller(original)
            app.prepare_wave(path,control,{'fb18'})
            self.assertEqual(sum(len(v['payload']['jobs']) for p,v in app.load_today_plans(control)),43)
            (self.root/'videos/fb18/personal/inbox/extra-later.mp4').write_bytes(b'not in original request snapshot')
            app.prepare_wave(path,control,set())
            plans=app.load_today_plans(control)
        self.assertEqual([len(v['payload']['jobs']) for p,v in plans],[43,1])
        self.assertEqual(plans[-1][1]['payload']['jobs'][0]['account'],'fb18')
        self.assertEqual(plans[-1][1]['payload']['jobs'][0]['filename'],self.expected[('fb18','personal')][0])

    def test_committed_plan_survives_interruption_before_pointer_write_and_waits_for_caption_stability(self):
        with app.old.locked():
            parent,original=app.old_sources();app.ready_personals(parent)
            path,control=app.today_controller(original)
            committed,value=app.prepare_wave(path,control,set())
            self.assertGreaterEqual(datetime.fromisoformat(value['payload']['start']).timestamp()-self.clock.now.return_value.timestamp(),75)
            control['plans']=[];app.upload.save_json(path,control)
            self.assertIsNone(app.prepare_wave(path,control,set()))
            recovered=app.load_today_plans(control)
            self.assertEqual(recovered,[(committed,value)])


if __name__=='__main__':unittest.main()
