import contextlib
import copy
import io
import os
import tempfile
import time
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch,MagicMock
import fb_upload as upload
import add_fb_accounts
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import published_video_lookup as lookup
import safe_video_comments as comments


class PublishedStoryTests(unittest.TestCase):
    def setUp(self):
        self.story=dict(__typename='Story',actors=[{'id':'1001'}],message={'text':'Exact caption'},creation_time=100,
            attachments=[{'media':{'__typename':'Video','id':'9001','owner':{'id':'1001'}}}])

    def test_visible_owned_story_with_video_timestamp_and_caption_can_supply_link(self):
        self.assertEqual(lookup.story_videos({'data':self.story},'1001','Exact caption',90,110),{'https://www.facebook.com/reel/9001'})

    def test_wrong_author_caption_time_and_draft_never_supply_link(self):
        for change in [dict(actors=[{'id':'2'}]),dict(message={'text':'Other'}),dict(creation_time=89),dict(is_draft=True),dict(is_published=False),dict(is_pending=True)]:
            self.assertEqual(lookup.story_videos(dict(self.story,**change),'1001','Exact caption',90,110),set())

    def test_shared_video_or_multiple_videos_never_select_one(self):
        wrong=copy.deepcopy(self.story);wrong['attachments'][0]['media']['owner']['id']='2'
        self.assertEqual(lookup.story_videos(wrong,'1001','Exact caption',90,110),set())
        multi=copy.deepcopy(self.story);multi['attachments'].append({'media':{'__typename':'Video','id':'9002'}})
        self.assertEqual(lookup.story_videos(multi,'1001','Exact caption',90,110),set())

    def test_matching_parent_caption_does_not_leak_to_other_story(self):
        self.story['message']={'text':'Wrong'}
        self.assertEqual(lookup.story_videos({'message':{'text':'Exact caption'},'child':self.story},'1001','Exact caption',90,110),set())

    def test_story_fragments_merge_only_with_identical_story_id_and_no_field_conflicts(self):
        fragments=[dict(__typename='Story',id='story-1',actors=self.story['actors'],message=self.story['message']),
                   dict(__typename='Story',id='story-1',creation_time=100,attachments=self.story['attachments'])]
        self.assertEqual(lookup.story_videos(fragments,'1001','Exact caption',90,110),{'https://www.facebook.com/reel/9001'})
        fragments.append(dict(__typename='Story',id='story-1',message={'text':'Other caption'}))
        self.assertEqual(lookup.story_videos(fragments,'1001','Exact caption',90,110),set())
        fragments[1]['id']='story-2'
        self.assertEqual(lookup.story_videos(fragments[:2],'1001','Exact caption',90,110),set())

    def test_facebook_watch_and_vanity_video_links_normalize_but_external_links_do_not(self):
        for url in ['https://www.facebook.com/watch/?v=9001','https://www.facebook.com/example/videos/9001/','https://www.facebook.com/reels/9001/']:
            self.assertEqual(comments.direct_link(url),'https://www.facebook.com/reel/9001')
        for url in ['https://evil.example/reel/9001','https://www.facebook.com:444/reel/9001','https://www.facebook.com/watch/?v=bad']:
            self.assertIsNone(comments.direct_link(url))

    def test_graphql_prefix_and_lines_are_parsed_without_exporting_raw_data(self):
        self.assertEqual(lookup.payloads('for (;;);{"data":1}'),[{'data':1}])
        self.assertEqual(lookup.payloads('{"data":1}\n{"data":2}'),[{'data':1},{'data':2}])
        self.assertEqual(lookup.payloads('not json'),[])


class ConfirmedDailyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir()
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(patch.object(add_fb_accounts,'ROOT',self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entries=[];self.jobs=[];self.state={}
        for n,(account,target) in enumerate(sorted(daily.EXPECTED_PAIRS),1):
            entry=dict(account=account,target=target,type='personal' if target=='personal' else 'page',name='Example '+str(n),url='https://www.facebook.com/profile.php?id='+str(1000+n),enabled=False)
            if target=='personal':entry['workflow']='personal_recording_v1'
            video=upload.inbox_for(entry)/'old.mp4';video.parent.mkdir(parents=True);video.write_bytes(('old'+str(n)).encode());caption=video.with_suffix('.txt');caption.write_text('Yesterday caption')
            key=upload.job_key(entry,video)
            job=dict(account=account,target=target,filename=video.name,key=key,url=entry['url'],entry_sha256=batch.digest(entry),caption_text=caption.read_text(),caption_sha256=batch.file_hash(caption),video_size=video.stat().st_size)
            self.jobs.append(job);self.entries.append(entry)
            self.state[key]=dict(confirmed_batch_lookup_cutoff='2026-10-30T09:00:00+00:00',account=account,target=target,url=entry['url'],video=str(video),caption=str(caption),status='needs_review',error='previous error',created='2026-10-29T09:01:00+00:00')
        upload.save_json(upload.CONFIG,{'targets':self.entries});self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state)
        self.config_before=upload.CONFIG.read_bytes()
        payload=dict(schema=batch.SCHEMA,date=daily.OLD_DATE,start='2026-10-29T17:00:00+08:00',ai_label=False,include_fb10_pages=True,excluded_accounts=sorted(daily.EXCLUDED),comment_text=daily.COMMENT,jobs=self.jobs)
        checksum=batch.digest(payload);self.manifest=dict(payload=payload,sha256=checksum)
        self.path=self.root/'logs'/('frozen-material-'+daily.OLD_DATE+'-'+checksum[:16]+'.json');upload.save_json(self.path,self.manifest)

    def tearDown(self):self.stack.close();self.temp.cleanup()

    def test_confirmed_30_jobs_persist_no_reupload_guard_archive_only_matching_old_bytes_and_preserve_new_same_name(self):
        replaced=upload.inbox_for(self.entries[0])/'old.mp4';replaced.write_bytes(b'today new content')
        daily.confirm_yesterday(self.path,self.manifest)
        state=upload.read_json(self.state_path,{})
        self.assertEqual(len(state),30);self.assertTrue(all(r['status']=='published' for r in state.values()))
        self.assertEqual(state[self.jobs[0]['key']]['historical_attempts'][0]['error'],'previous error')
        self.assertEqual(replaced.read_bytes(),b'today new content')
        self.assertTrue((upload.inbox_for(self.entries[1]).parent/'completed/old.mp4').is_file())
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)

    def test_original_comment_lookup_cutoff_never_moves_past_todays_new_posts_on_rerun(self):
        daily.confirm_yesterday(self.path,self.manifest)
        state=upload.read_json(self.state_path,{})
        self.assertTrue(all(r['confirmed_batch_lookup_cutoff']=='2026-10-30T09:00:00+00:00' for r in state.values()))
        daily.confirm_yesterday(self.path,self.manifest)
        self.assertTrue(all(r['confirmed_batch_lookup_cutoff']=='2026-10-30T09:00:00+00:00' for r in upload.read_json(self.state_path,{}).values()))

    def test_missing_or_mismatched_record_stops_before_any_state_change_or_archive(self):
        del self.state[self.jobs[-1]['key']];upload.save_json(self.state_path,self.state);before=self.state_path.read_bytes()
        with self.assertRaises(ValueError):daily.confirm_yesterday(self.path,self.manifest)
        self.assertEqual(before,self.state_path.read_bytes())
        self.assertTrue((upload.inbox_for(self.entries[0])/'old.mp4').exists())

    def test_unique_manifest_ignores_results_files_and_rejects_multiple_plans(self):
        upload.save_json(self.path.with_name(self.path.stem+'-results.json'),{})
        self.assertEqual(daily.load_unique(daily.OLD_DATE)[0],self.path)
        payload=copy.deepcopy(self.manifest['payload']);payload['comment_text']='other';checksum=batch.digest(payload)
        upload.save_json(self.root/'logs'/('frozen-material-'+daily.OLD_DATE+'-'+checksum[:16]+'.json'),dict(payload=payload,sha256=checksum))
        with self.assertRaises(ValueError):daily.load_unique(daily.OLD_DATE)

    def test_unknown_comment_intent_is_skipped_without_opening_browser_or_sending_again(self):
        job=self.jobs[0]
        self.state[job['key']]['status']='published';upload.save_json(self.state_path,self.state)
        key=comments.hashlib.sha256((job['key']+'\0'+comments.text_hash(daily.COMMENT)).encode()).hexdigest()
        upload.save_json(self.root/'logs/video_comments.json',{key:dict(status='sending',permalink='https://www.facebook.com/reel/9001')})
        with patch.object(daily,'close_selected_window') as close:
            rows=daily.backfill(self.manifest,None,only_keys={job['key']})
        close.assert_not_called();self.assertEqual(rows[0]['status'],'sending')

    def test_comment_browser_close_error_does_not_turn_a_sent_comment_into_failure(self):
        job=self.jobs[0];self.state[job['key']]['status']='published';upload.save_json(self.state_path,self.state)
        browser=MagicMock();browser.pages=[MagicMock()];browser.close.side_effect=IndexError('list index out of range')
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser), \
             patch.object(upload,'ensure_identity',return_value={}),patch.object(daily,'close_selected_window'), \
             patch.object(daily,'find_published',return_value=('https://www.facebook.com/reel/9001','verified_owner_caption_time')), \
             patch.object(comments,'after_publication',return_value={'status':'sent','permalink':'https://www.facebook.com/reel/9001'}):
            rows=daily.backfill(self.manifest,None,only_keys={job['key']})
        self.assertEqual(rows[0]['status'],'sent')
        self.assertEqual(upload.read_json(self.state_path,{})[job['key']]['comment_status'],'sent')

    def test_user_link_requires_exact_job_target_and_full_fingerprint(self):
        path=self.root/'links.csv';job=self.jobs[0]
        path.write_text('account,target,key,permalink\n'+','.join([job['account'],job['target'],job['key'],'https://www.facebook.com/reel/9001'])+'\n')
        self.assertEqual(daily.manual_links(path,self.jobs),{job['key']:'https://www.facebook.com/reel/9001'})
        path.write_text(path.read_text().replace(job['account'],'fb99'))
        with self.assertRaises(ValueError):daily.manual_links(path,self.jobs)


class TodayFirstOrderTests(unittest.TestCase):
    def test_all_today_uploads_run_before_today_comments_and_yesterday_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'logs').mkdir()
            manifest={'payload':{'date':daily.TODAY,'start':'2026-10-30T17:00:00+08:00','comment_text':daily.COMMENT,'jobs':[]},'sha256':'a'*64}
            path=root/'logs/frozen-material-2026-10-30-aaaaaaaaaaaaaaaa.json';events=[]
            with patch.object(upload,'ROOT',root),patch.object(add_fb_accounts,'ROOT',root),patch.object(daily,'datetime',wraps=datetime) as clock, \
                 patch.object(daily,'load_unique',return_value=(path,manifest)) as load, \
                 patch.object(daily,'confirm_yesterday',side_effect=AssertionError('yesterday was cancelled')), \
                 patch.object(batch,'run',side_effect=lambda *a,**k:events.append('all-today-videos') or 3) as run, \
                 patch.object(daily,'backfill',side_effect=lambda value,*a:events.append('today-comments') or []) as send, \
                 patch.object(batch,'results',return_value=[dict(video_status='published',comment_status='sent')]):
                clock.now.return_value=datetime(2026,10,30,12,0,tzinfo=timezone.utc)
                self.assertEqual(daily.execute(),0)
            self.assertEqual(events,['all-today-videos','today-comments'])
            load.assert_called_once_with(daily.TODAY,required=False)
            self.assertTrue(run.call_args.kwargs['defer_comments'])
            self.assertEqual(send.call_args.args[0]['payload']['date'],daily.TODAY)
