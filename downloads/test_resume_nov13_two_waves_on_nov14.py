import copy
import contextlib
import os
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import MagicMock,patch

import resume_nov13_two_waves_on_nov14 as app
from test_publish_all_distributed_nov13 import TwoWavePublicationTests


class CrossDayResumeTests(unittest.TestCase):
    def setUp(self):
        self.fx=TwoWavePublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root;self.first=app.first
        self.parent_path,self.parent=self.first.freeze()
        self.enterContext(patch.object(app,'datetime',wraps=datetime))
        self.clock=app.datetime

    def advance_day(self):
        self.fx.fx.now=datetime(2026,11,14,5,tzinfo=timezone.utc)
        for clock in self.fx.fx.clocks:clock.now.return_value=self.fx.fx.now
        self.clock.now.return_value=self.fx.fx.now
        for file in (self.root/'videos').rglob('*'):
            if file.is_file() and file.suffix in {'.mp4','.txt'}:os.utime(file,(self.fx.fx.now.timestamp()-180,)*2)

    def partial_source(self):
        state=self.first.upload.read_json(self.root/'logs/publish_state.json',{})
        statuses=['published','needs_review','needs_review','needs_review','published','failed_before_post','posting']
        created=self.fx.fx.now+timedelta(minutes=2)
        attempts=[]
        for job,status in zip(self.parent['payload']['jobs'],statuses):
            video=self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']
            row=dict(account=job['account'],target=job['target'],url=job['url'],video=str(video),created=created.isoformat(),
                     status=status,uploader_version='2.47',ai_label_requested=False,source_frozen_manifest=self.parent_path.name,
                     source_frozen_sha256=self.parent['sha256'],published_caption_text=job['caption_text'],comment_status='not_started')
            if status!='failed_before_post':row['post_intent_at']=(created+timedelta(seconds=5)).isoformat()
            if status=='needs_review':row['review_reason']='publication_receipt_timeout'
            if status=='published':
                row['published_at']=(created+timedelta(seconds=30)).isoformat()
                folder=self.first.upload.archive(video,video.with_suffix('.txt'));row['archived_video']=str(folder/video.name)
            state[job['key']]=row
            if status!='posting':attempts.append(dict(key=job['key'],account=job['account'],target=job['target'],action='finished' if status=='published' else 'manual_required',started_at=created.isoformat()))
        self.first.upload.save_json(self.root/'logs/publish_state.json',state)
        self.first.upload.save_json(self.parent_path.with_name(self.parent_path.stem+'-results.json'),dict(manifest=self.parent_path.name,attempts=attempts))
        self.parent_files={p:p.read_bytes() for p in (self.root/'logs').glob('frozen-material-2026-11-13-*.json')}
        self.original_rows=copy.deepcopy(state)

    def run_resume(self):
        finders=[]
        def factory(*args,**kwargs):
            def finder(*a,**k):finders.append((a[4],a[5]));raise ValueError('No unique confirmed old video')
            return finder
        with patch.object(app.original.registration,'discover',side_effect=self.fx.discover), \
             patch.object(app,'FINDER',side_effect=factory),patch.object(self.first,'execute',side_effect=lambda real:app.execute()):
            result,events,comments=self.fx.fx.core(include_new=True)
        return result,events,comments,finders

    def test_resume_partial_log_preserves_two_successes_and_four_submitted_and_uploads_remaining88_only(self):
        self.partial_source();self.advance_day()
        new_today=self.root/'videos/fb08/personal/inbox/nov14-new-only.mp4';new_today.write_bytes(b'do not move or publish Nov14 content')
        result,events,_,_=self.run_resume()
        self.assertEqual(result,3)
        posts=[e[1] for e in events if e[0]=='post']
        self.assertEqual(len(posts),88)
        self.assertNotIn(('fb01','page01'),posts);self.assertNotIn(('fb05','page01'),posts)
        for pair in (('fb02','page01'),('fb03','personal'),('fb04','personal'),('fb07','personal')):self.assertNotIn(pair,posts)
        self.assertIn(('fb06','page01'),posts)
        self.assertTrue(all(int(a[2:])<=24 for a,t in posts[:38]));self.assertEqual([a for a,t in posts[38:]],sorted(app.original.NEW))
        for path,data in self.parent_files.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(new_today.read_bytes(),b'do not move or publish Nov14 content')
        self.assertFalse(any((self.root/'logs/material-distribution').glob('*/2026-11-14.json')))
        state=self.first.upload.read_json(self.root/'logs/publish_state.json',{})
        first_job=self.parent['payload']['jobs'][0]
        self.assertEqual(state[first_job['key']]['published_at'],self.original_rows[first_job['key']]['published_at'])
        result,events,_,_=self.run_resume();self.assertEqual(result,3);self.assertFalse(any(e[0]=='post' for e in events))

    def test_already_finished_all94_and_comments_are_not_reposted_from_an_incomplete_pasted_log(self):
        self.fx.run_all();self.advance_day()
        result,events,_,_=self.run_resume()
        self.assertEqual(result,0);self.assertFalse(any(e[0]=='post' for e in events))

    def test_old13_date_guard_stays_closed_on14_and_bad_source_cannot_create_new_manifest(self):
        self.partial_source();self.advance_day()
        with self.assertRaises(ValueError):self.first.require_day()
        value=self.first.upload.read_json(self.parent_path,{})
        value['payload']['jobs'][0]['filename']='tampered.mp4';self.first.upload.save_json(self.parent_path,value)
        with self.assertRaisesRegex(ValueError,'校验失败'):app.execute()
        self.assertFalse((self.root/'logs'/app.FIRST_POINTER).exists())

    def test_comment_lookup_for_old_success_keeps_its13th_time_window(self):
        self.partial_source();self.advance_day();job=self.parent['payload']['jobs'][0]
        inner=MagicMock(return_value=('https://www.facebook.com/reel/1','verified_owner_caption_time'))
        with patch.object(app,'FINDER',return_value=inner):
            finder=app.source_day_finder([job],True)
            midnight=datetime.fromisoformat('2026-11-14T00:00:00+08:00').timestamp()
            finder(None,None,dict(account=job['account'],target=job['target']),job['caption_text'],midnight,self.fx.fx.now.timestamp())
        lower,upper=inner.call_args.args[4:6]
        original=self.original_rows[job['key']]
        self.assertEqual(lower,datetime.fromisoformat(original['created']).timestamp()-5)
        self.assertLessEqual(upper,datetime.fromisoformat(original['post_intent_at']).timestamp()+900)

    def test_resuming_old_distribution_preserves_new14_source_preferences(self):
        _,_,material_path,material,_,_=app.source()
        progress_path=material_path.with_name(material_path.stem+'-progress.json')
        progress=self.first.upload.read_json(progress_path,{})
        progress.update(done=progress['done'][:44],complete=False)
        self.first.upload.save_json(progress_path,progress)
        settings=self.root/self.first.materials.SETTINGS
        self.first.upload.save_json(settings,dict(source=str(self.root/'Nov14-new-folder'),target_scope='existing24'))
        before=settings.read_bytes()
        app.resume_distribution(self.root,material['payload']['source'],day='2026-11-13',scope='all')
        self.assertEqual(settings.read_bytes(),before)
        self.assertTrue(self.first.upload.read_json(progress_path,{})['complete'])


if __name__=='__main__':unittest.main()
