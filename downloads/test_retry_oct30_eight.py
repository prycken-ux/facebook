import contextlib
import copy
import io
import os
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch

import fb_upload as upload
import add_fb_accounts
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import retry_oct30_eight as retry


class EightRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir()
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(patch.object(add_fb_accounts,'ROOT',self.root));self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.keys={};self.entries=[];self.jobs=[];self.state={}
        for n,pair in enumerate(retry.KEYS,1):
            account,target=pair
            entry=dict(account=account,target=target,type='personal' if target=='personal' else 'page',name='Example '+str(n),url='https://www.facebook.com/profile.php?id='+str(1000+n),enabled=False)
            if target=='personal':entry['workflow']='personal_recording_v1'
            self.entries.append(entry)
            video=upload.inbox_for(entry)/('video'+str(n)+'.mp4');video.parent.mkdir(parents=True);video.write_bytes(('exact video '+str(n)).encode())
            caption=video.with_suffix('.txt');caption.write_text('Exact existing caption '+str(n));os.utime(video,(1000000000,1000000000));os.utime(caption,(1000000000,1000000000))
            key=upload.job_key(entry,video);self.keys[pair]=key
            job=dict(account=account,target=target,filename=video.name,key=key,url=entry['url'],entry_sha256=batch.digest(entry),caption_text=caption.read_text(),caption_sha256=batch.file_hash(caption),video_size=video.stat().st_size)
            self.jobs.append(job)
            self.state[key]=dict(account=account,target=target,url=entry['url'],video=str(video),caption=str(caption),status='failed_before_post',error='original pre-Post failure',created='2026-10-30T10:00:00+00:00')
        self.unrelated=dict(account='fb02',target='page01',url='https://www.facebook.com/profile.php?id=2002',video='2.mp4',status='preparing')
        self.state['f'*64]=copy.deepcopy(self.unrelated)
        upload.save_json(upload.CONFIG,{'targets':self.entries});self.config_before=upload.CONFIG.read_bytes()
        self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state)
        payload=dict(schema=batch.SCHEMA,date='2026-10-30',start='2026-10-30T17:00:00+08:00',ai_label=False,comment_text=daily.COMMENT,jobs=self.jobs)
        sha=batch.digest(payload);self.source=self.root/'logs'/('frozen-material-2026-10-30-'+sha[:16]+'.json')
        upload.save_json(self.source,dict(payload=payload,sha256=sha))
        self.stack.enter_context(patch.object(retry,'SOURCE',self.source.name));self.stack.enter_context(patch.object(retry,'KEYS',self.keys))
        self.clock=self.stack.enter_context(patch.object(retry,'datetime',wraps=datetime));self.clock.now.return_value=datetime(2026,10,31,5,0,tzinfo=timezone.utc)

    def tearDown(self):self.stack.close();self.temp.cleanup()

    def pipeline(self):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock()
        def comment_phase(value,output):
            state=upload.read_json(self.state_path,{})
            for job in value['payload']['jobs']:
                row=state[job['key']]
                if row['status']=='published':
                    if row.get('comment_status') in {'sent','already_present'}:continue
                    self.assertEqual(row['comment_status'],'deferred')
                    self.assertTrue(Path(row['archived_video']).is_file())
                    row['comment_status']='sent'
            upload.save_json(self.state_path,state)
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'prepare_reel',return_value=(button,{})),patch.object(upload,'recheck_publish_identity'), \
             patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',return_value='Your reel is published.'), \
             patch.object(batch,'close_selected_window'),patch.object(daily,'backfill',side_effect=comment_phase), \
             patch('safe_video_comments.after_publication',side_effect=AssertionError('comments cannot run during uploads')):
            result=retry.execute()
        return result,button

    def test_only_eight_original_keys_retry_archive_then_comment_without_touching_unrelated_records(self):
        result,button=self.pipeline();self.assertEqual(result,0);self.assertEqual(button.click.call_count,8)
        state=upload.read_json(self.state_path,{})
        self.assertEqual(state['f'*64],self.unrelated);self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        for key in self.keys.values():
            self.assertEqual(state[key]['status'],'published');self.assertEqual(state[key]['previous_before_post_attempt'],self.state[key])
            self.assertEqual(state[key]['comment_status'],'sent')
        result,button=self.pipeline();button.click.assert_not_called()

    def test_changed_to_unknown_state_is_not_retried_while_other_seven_continue(self):
        job=self.jobs[0];self.state[job['key']]['status']='needs_review';old=copy.deepcopy(self.state[job['key']]);upload.save_json(self.state_path,self.state)
        result,button=self.pipeline();self.assertEqual(result,3);self.assertEqual(button.click.call_count,7)
        self.assertEqual(upload.read_json(self.state_path,{})[job['key']],old)

    def test_missing_record_is_manual_issue_and_never_treated_as_fresh_unrecorded_video(self):
        job=self.jobs[0];del self.state[job['key']];upload.save_json(self.state_path,self.state);before=self.state_path.read_bytes()
        path,value=retry.make_retry()
        self.assertNotIn(job['key'],{j['key'] for j in value['payload']['jobs']})
        self.assertEqual(len(value['issues']),1);self.assertEqual(self.state_path.read_bytes(),before)

    def test_original_named_file_replaced_with_today_new_video_cannot_be_selected(self):
        job=self.jobs[0];video=upload.inbox_for(self.entries[0])/job['filename'];video.write_bytes(b'different new video')
        with self.assertRaises(ValueError):batch.validate_job(job)

    def test_retry_grant_is_reserved_once_and_missing_records_cannot_bypass_it(self):
        job=self.jobs[0];retry.reserve_exact_retry(job)
        with self.assertRaises(ValueError):retry.reserve_exact_retry(job)
        del self.state[job['key']];upload.save_json(self.state_path,self.state)
        with self.assertRaises(ValueError):retry.reserve_exact_retry(job)
        self.assertNotIn(job['key'],upload.read_json(self.state_path,{}))

    def test_authorization_date_and_source_hash_are_required(self):
        self.clock.now.return_value=datetime(2026,11,1,5,0,tzinfo=timezone.utc)
        with self.assertRaises(ValueError):retry.make_retry()
        value=upload.read_json(self.source,{});value['payload']['jobs'][0]['key']='a'*64;upload.save_json(self.source,value)
        with self.assertRaises(ValueError):retry.source_jobs()
