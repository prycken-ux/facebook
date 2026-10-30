import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
from xml.etree import ElementTree as ET

import add_fb_accounts
import fb_upload as upload
import scheduled_material_batch as schedule


class ScheduledMaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir()
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(patch.object(add_fb_accounts,'ROOT',self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.now=datetime(2026,10,29,8,0,tzinfo=timezone.utc)
        self.comment='Get your own copy:\nhttps://www.amazon.com/s?maas=abc&ref_=aa_maas&tag=maas&me=EXAMPLE&marketplaceID=ATVPDKIKX0DER'
        self.entries=[];self.videos={}
        for n,target in [(1,'page01'),(10,'page01'),(10,'personal'),(16,'personal'),(18,'personal'),(21,'personal'),(23,'personal')]:
            entry=dict(account=f'fb{n:02}',target=target,type='personal' if target=='personal' else 'page',name='Example '+str(n)+target,
                url='https://www.facebook.com/profile.php?id='+str(1000+n+(100 if target=='page01' else 0)),enabled=False)
            if entry['type']=='personal':entry['workflow']='personal_recording_v1'
            self.entries.append(entry)
            video=upload.inbox_for(entry)/'today.mp4';video.parent.mkdir(parents=True);video.write_bytes((entry['account']+target).encode())
            os.utime(video,(time.time()-180,time.time()-180));self.videos[(entry['account'],target)]=video
        self.custom=b'\xef\xbb\xbfMy original custom caption\r\nKeep this exact text\r\n'
        self.videos[('fb23','personal')].with_suffix('.txt').write_bytes(self.custom)
        os.utime(self.videos[('fb23','personal')].with_suffix('.txt'),(time.time()-180,time.time()-180))
        upload.save_json(upload.CONFIG,dict(targets=self.entries));self.config_before=upload.CONFIG.read_bytes()
        (self.root/'common_caption_today.txt').write_text('Saved old caption\n#Prycken')
        self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,{})

    def tearDown(self):self.stack.close();self.temp.cleanup()

    def freeze(self,include=True):return schedule.freeze('2026-10-29','17:00',include,self.comment,self.now)

    def test_freezes_both_fb10_targets_excludes_three_slots_and_preserves_existing_caption_bytes(self):
        path,manifest=self.freeze();jobs=manifest['payload']['jobs']
        self.assertEqual({(j['account'],j['target']) for j in jobs},{('fb01','page01'),('fb10','page01'),('fb10','personal'),('fb23','personal')})
        self.assertEqual(manifest['payload']['start'],'2026-10-29T17:00:00+08:00')
        self.assertFalse(manifest['payload']['ai_label'])
        self.assertEqual(self.videos[('fb23','personal')].with_suffix('.txt').read_bytes(),self.custom)
        self.assertEqual(self.videos[('fb01','page01')].with_suffix('.txt').read_text().strip(),'Saved old caption\n#Prycken')
        for n in (16,18,21):self.assertFalse(self.videos[(f'fb{n}','personal')].with_suffix('.txt').exists())
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        self.assertEqual(self.freeze()[0],path)

    def test_any_target_existing_nonempty_caption_is_preserved_not_only_fb23(self):
        video=self.videos[('fb01','page01')];caption=video.with_suffix('.txt');caption.write_bytes(self.custom)
        _,manifest=self.freeze()
        job=next(j for j in manifest['payload']['jobs'] if j['account']=='fb01')
        self.assertEqual(caption.read_bytes(),self.custom)
        self.assertIn('My original',job['caption_text'])

    def test_empty_caption_falls_back_with_backup_and_duplicate_bytes_only_selected_once(self):
        video=self.videos[('fb01','page01')];video.with_suffix('.txt').write_bytes(b'')
        (video.parent/'copy.mp4').write_bytes(video.read_bytes())
        _,manifest=self.freeze()
        self.assertEqual(len([j for j in manifest['payload']['jobs'] if j['account']=='fb01']),1)
        self.assertTrue(any('重复文件' in i['reason'] for i in manifest['issues']))

    def test_known_old_files_are_not_retried_and_new_different_bytes_are_frozen(self):
        entry=self.entries[0];old=upload.inbox_for(entry)/'old.mp4';old.write_bytes(b'older video')
        key=upload.job_key(entry,old);state={key:dict(account=entry['account'],target=entry['target'],url=entry['url'],video=str(old),status='needs_review')}
        upload.save_json(self.state_path,state)
        _,manifest=self.freeze()
        self.assertNotIn(key,[j['key'] for j in manifest['payload']['jobs']])
        self.assertEqual(upload.read_json(self.state_path,{}),state)

    def test_one_time_task_has_beijing_offset_no_calendar_and_no_force_termination(self):
        path,manifest=self.freeze();root=ET.fromstring(schedule.task_xml(path,manifest));ns={'t':schedule.NS}
        self.assertEqual(len(root.findall('t:Triggers/t:TimeTrigger',ns)),1)
        self.assertEqual(root.findall('t:Triggers/t:CalendarTrigger',ns),[])
        self.assertEqual(root.find('t:Triggers/t:TimeTrigger/t:StartBoundary',ns).text,'2026-10-29T17:00:00+08:00')
        self.assertEqual(root.find('t:Settings/t:AllowHardTerminate',ns).text,'false')
        self.assertEqual(root.find('t:Settings/t:ExecutionTimeLimit',ns).text,'PT0S')

    def test_late_setup_stays_today_and_yesterday_commands_are_rejected(self):
        late=datetime(2026,10,29,10,0,tzinfo=timezone.utc)
        self.assertEqual(schedule.start_time('2026-10-29','17:00',late).date(),late.astimezone(schedule.BJ).date())
        with self.assertRaises(ValueError):schedule.start_time('2026-10-28','17:00',self.now)

    def pipeline(self,path,unknown=False,comment_failure=False,before_job=None):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock()
        with patch.object(schedule,'datetime',wraps=datetime) as clock,patch('playwright.sync_api.sync_playwright'), \
             patch.object(upload,'launch_context',return_value=browser),patch.object(upload,'prepare_reel',return_value=(button,{})), \
             patch.object(upload,'recheck_publish_identity'),patch.object(upload,'install_receipt_watch'), \
             patch.object(upload,'wait_for_receipt',return_value='Your reel is published.',side_effect=upload.ReceiptNeedsReview('unknown') if unknown else None), \
             patch('safe_video_comments.after_publication',return_value={'status':'sent'},side_effect=RuntimeError('comment UI unavailable') if comment_failure else None) as comment, \
             patch.object(schedule,'close_selected_window'),patch('builtins.input',side_effect=AssertionError('must never prompt')):
            clock.now.return_value=datetime(2026,10,29,9,1,tzinfo=timezone.utc)
            # Captions were frozen at setup; simulate the scheduled stable-file interval.
            for file in self.root.rglob('*.txt'):os.utime(file,(time.time()-180,time.time()-180))
            result=schedule.run(path,before_job=before_job)
        return result,button,comment

    def test_run_posts_exact_frozen_jobs_comments_once_and_preserves_old_review_without_enabling_config(self):
        entry=self.entries[0];old=upload.inbox_for(entry)/'old.mp4';old.write_bytes(b'old')
        old_key=upload.job_key(entry,old);old_row=dict(account=entry['account'],target=entry['target'],url=entry['url'],video=str(old),status='needs_review')
        upload.save_json(self.state_path,{old_key:old_row})
        path,manifest=self.freeze()
        result,button,comment=self.pipeline(path)
        self.assertEqual(result,0);self.assertEqual(button.click.call_count,4);self.assertEqual(comment.call_count,4)
        state=upload.read_json(self.state_path,{})
        self.assertEqual(state[old_key],old_row)
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        self.assertTrue(old.exists())
        result,button,comment=self.pipeline(path)
        self.assertEqual(result,0);button.click.assert_not_called();comment.assert_not_called()

    def test_before_job_comment_updates_are_reloaded_before_saving_new_publication_state(self):
        path,_=self.freeze()
        old_key='f'*64
        def hook(job):
            state=upload.read_json(self.state_path,{})
            state[old_key]=dict(account='fb99',target='personal',url='https://www.facebook.com/profile.php?id=9999',status='published',comment_status='sent')
            upload.save_json(self.state_path,state)
        result,button,comment=self.pipeline(path,before_job=hook)
        self.assertEqual(result,0)
        self.assertEqual(upload.read_json(self.state_path,{})[old_key]['comment_status'],'sent')

    def test_comment_failure_never_changes_published_video_to_failed_or_causes_reupload(self):
        path,_=self.freeze();result,button,comment=self.pipeline(path,comment_failure=True)
        self.assertEqual(result,3)
        state=upload.read_json(self.state_path,{})
        self.assertTrue(all(r['status']=='published' and r['comment_status']=='manual_required' for r in state.values()))
        _,button,comment=self.pipeline(path);button.click.assert_not_called();comment.assert_not_called()

    def test_unknown_publication_never_comments_or_retries(self):
        path,_=self.freeze();result,button,comment=self.pipeline(path,unknown=True)
        self.assertEqual(result,3);comment.assert_not_called()
        _,button,comment=self.pipeline(path);button.click.assert_not_called();comment.assert_not_called()

    def test_changed_video_or_caption_stops_without_substitution(self):
        path,manifest=self.freeze();job=manifest['payload']['jobs'][0]
        entry=next(e for e in self.entries if (e['account'],e['target'])==(job['account'],job['target']))
        video=upload.inbox_for(entry)/job['filename'];video.write_bytes(b'replaced contents')
        with self.assertRaises(ValueError):schedule.validate_job(job)
        video.write_bytes((entry['account']+entry['target']).encode());video.with_suffix('.txt').write_text('changed caption')
        with self.assertRaises(ValueError):schedule.validate_job(job)

    def test_before_start_and_tampered_manifest_cannot_publish(self):
        path,manifest=self.freeze()
        with patch.object(schedule,'datetime',wraps=datetime) as clock:
            clock.now.return_value=self.now
            with self.assertRaises(ValueError):schedule.run(path)
        manifest['payload']['comment_text']='changed';upload.save_json(path,manifest)
        with self.assertRaises(ValueError):schedule.run(path)
