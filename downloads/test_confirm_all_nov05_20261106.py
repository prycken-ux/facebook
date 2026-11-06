import contextlib,copy,shutil,unittest
from pathlib import Path
from unittest.mock import patch
import confirm_all_nov05_20261106 as run
import test_retry_nov04_after_local_file_fix_20261105 as fixtures
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import publish_priority_batch as priority


class ConfirmNov05Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.RepairedNov04Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.jobs=copy.deepcopy(self.f.jobs);self.state=copy.deepcopy(self.f.state)
        page08=next(e for e in self.f.entries if (e['account'],e['target'])==('fb10','page08'))
        for i,job in enumerate(self.jobs):
            if (job['account'],job['target'])==('fb10','page10'):
                old=self.state.pop(job['key']);file=upload.inbox_for(page08)/'second.mp4';file.write_bytes(b'second Nov5 page08 video');caption=file.with_suffix('.txt');caption.write_text('Second original caption')
                key=upload.job_key(page08,file)
                job.update(target='page08',url=page08['url'],filename=file.name,key=key,entry_sha256=batch.digest(page08),caption_text=caption.read_text(),caption_sha256=batch.file_hash(caption),video_size=file.stat().st_size)
                self.state[key]=dict(old,target='page08',url=page08['url'],video=str(file),caption=str(caption))
        self.fb17=next(j for j in self.jobs if j['account']=='fb17');self.missing_record=self.state.pop(self.fb17['key'])
        others=[j for j in self.jobs if j['key']!=self.fb17['key']]
        self.existing=others[:16]
        for i,job in enumerate(others):
            self.state[job['key']].update(status='published' if i<16 else 'failed_before_post' if i==16 else 'needs_review',comment_status='sent' if i<11 else 'manual_required' if i<16 else 'not_started',comment_error='keep exact comment outcome' if i>=11 else '')
        upload.save_json(self.f.state_path,self.state)
        value=dict(payload=dict(schema=batch.SCHEMA,date='2026-11-05',start='2026-11-05T12:00:00+08:00',ai_label=False,include_fb10_pages=True,excluded_accounts=['fb16','fb18','fb21'],comment_text=daily.COMMENT,jobs=self.jobs),
                   workflow='future-video-comments-v1',auto_retry_policy=priority.retry.POLICY,comment_timing=priority.TIMING,priority_workflow=priority.PRIORITY_WORKFLOW_VERSION,report_format='text',created_at='2026-11-05T11:58:00+08:00',issues=[])
        value['sha256']=batch.digest(value['payload']);self.stack.enter_context(patch.object(run,'PREFIX',value['sha256'][:8]))
        self.path=self.f.root/'logs'/('frozen-material-2026-11-05-'+value['sha256'][:16]+'.json');upload.save_json(self.path,value);self.source=self.path.read_bytes()
        self.pointer=self.f.root/'logs/priority-batch-2026-11-05.json';upload.save_json(self.pointer,dict(date='2026-11-05',manifest=self.path.name,sha256=value['sha256']));self.pointer_bytes=self.pointer.read_bytes()
        self.attempts=[dict(key=j['key'],action='manual_required',error='keep original attempt history') for j in self.jobs]
        self.report_path=self.path.with_name(self.path.stem+'-results.json');upload.save_json(self.report_path,dict(manifest=self.path.name,attempts=self.attempts))
        self.ledger=self.f.root/'logs/video_comments.json';upload.save_json(self.ledger,{'keep':dict(status='sent',text='existing authorized comment')});self.ledger_bytes=self.ledger.read_bytes()
        for mod,name in [(upload,'run_entry'),(upload,'launch_context'),(daily,'backfill')]:self.stack.enter_context(patch.object(mod,name,side_effect=AssertionError('confirmation cannot launch or publish/comment')))
    def assert_other_data(self):
        self.assertEqual(upload.CONFIG.read_bytes(),self.f.config);self.assertEqual(self.f.auto_path.read_bytes(),self.f.auto)
        self.assertEqual(self.ledger.read_bytes(),self.ledger_bytes);self.assertEqual(self.path.read_bytes(),self.source);self.assertEqual(self.pointer.read_bytes(),self.pointer_bytes)
        self.assertEqual(upload.read_json(self.report_path,{})['attempts'],self.attempts)
        state=upload.read_json(self.f.state_path,{})
        for key in ('old-paused','old-unknown'):self.assertEqual(state[key],self.state[key])
    def test_confirms_30_with_missing_record_preserving_comments_successes_and_all_claims(self):
        self.assertEqual(run.execute(),0);state=upload.read_json(self.f.state_path,{})
        self.assertTrue(all(state[j['key']]['status']=='published' for j in self.jobs))
        for job in self.existing:self.assertEqual(state[job['key']],self.state[job['key']])
        for job in self.jobs:
            if job['key'] in self.state:self.assertEqual(state[job['key']].get('comment_status'),self.state[job['key']].get('comment_status'))
        missing=state[self.fb17['key']];self.assertEqual(missing['comment_status'],'not_started');self.assertNotIn('post_intent_at',missing);self.assertNotIn('published_at',missing)
        self.assertTrue(missing['created_from_user_confirmation']);self.assertTrue(Path(missing['archived_video']).is_file())
        self.assertEqual(len([j for j in self.jobs if (j['account'],j['target'])==('fb10','page08')]),2)
        self.assert_other_data();before=copy.deepcopy(state);self.assertEqual(run.execute(),0);self.assertEqual(upload.read_json(self.f.state_path,{}),before)
    def test_missing_record_requires_same_content_local_source_before_any_writes(self):
        Path(self.missing_record['video']).write_bytes(b'replaced same-name video')
        with self.assertRaises(ValueError):run.execute()
        self.assertEqual(upload.read_json(self.f.state_path,{}),self.state);self.assert_other_data()
    def test_known_record_replacement_file_stays_untouched_after_original_confirmation(self):
        job=next(j for j in self.jobs if self.state.get(j['key'],{}).get('status')=='needs_review');video=Path(self.state[job['key']]['video']);video.write_bytes(b'todays replacement bytes')
        run.execute();self.assertEqual(video.read_bytes(),b'todays replacement bytes');self.assertEqual(upload.read_json(self.f.state_path,{})[job['key']]['status'],'published');self.assert_other_data()
    def test_missing_record_can_be_reconstructed_from_matching_completed_original(self):
        source=Path(self.missing_record['video']);dest=source.parent.parent/'completed/manual-save';dest.mkdir(parents=True)
        shutil.move(source,dest/source.name);shutil.move(source.with_suffix('.txt'),dest/source.with_suffix('.txt').name)
        run.execute();row=upload.read_json(self.f.state_path,{})[self.fb17['key']]
        self.assertEqual(row['status'],'published');self.assertEqual(Path(row['video']),dest/source.name);self.assert_other_data()
    def test_inflight_original_and_active_worker_are_not_overwritten(self):
        job=self.jobs[0];changed=copy.deepcopy(self.state);changed[job['key']]['status']='posting';upload.save_json(self.f.state_path,changed)
        with self.assertRaises(ValueError):run.execute()
        self.assertEqual(upload.read_json(self.f.state_path,{}),changed)
        upload.save_json(self.f.state_path,self.state);lock=self.f.root/'logs/upload.lock';lock.write_text('12345')
        with self.assertRaises(RuntimeError):run.execute()
        self.assertEqual(upload.read_json(self.f.state_path,{}),self.state);self.assertEqual(lock.read_text(),'12345')
    def test_tampered_source_or_wrong_pointer_cannot_confirm(self):
        value=upload.read_json(self.path,{});value['payload']['jobs'][0]['filename']='another.mp4';upload.save_json(self.path,value)
        with self.assertRaises(ValueError):run.execute()
        self.path.write_bytes(self.source);upload.save_json(self.pointer,dict(date='2026-11-05',manifest='another.json',sha256='0'*64))
        with self.assertRaises(ValueError):run.execute()
        self.assertEqual(upload.read_json(self.f.state_path,{}),self.state)
