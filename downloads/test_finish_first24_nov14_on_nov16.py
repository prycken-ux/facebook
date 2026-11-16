import contextlib,copy,json,os,subprocess,unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch
import finish_first24_nov14_on_nov16 as app
from test_publish_distributed_nov13_first24 import DistributedFirst24Tests
from test_retry_nov13_prepost_fifteen_on_nov14 import ExplicitFifteenTests


class StagedOn16Tests(unittest.TestCase):
    def setUp(self):
        self.fx=DistributedFirst24Tests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        self.fx.now=datetime(2026,11,14,6,tzinfo=timezone.utc)
        for c in self.fx.clocks:c.now.return_value=self.fx.now
        self.staged_clock=self.enterContext(patch.object(app.staged,'datetime',wraps=datetime));self.staged_clock.now.return_value=self.fx.now
        stageclock=self.enterContext(patch.object(app.staged.stage,'datetime',wraps=datetime));stageclock.now.return_value=self.fx.now
        pool=self.root/'nov14-source';pool.mkdir()
        for n in range(1,45):(pool/f'new-{n}.mp4').write_bytes(('Nov14 original '+str(n)).encode())
        path,self.source=app.staged.stage.prepare(self.root,pool,scope='existing24')
        self.enterContext(patch.object(app.staged,'SOURCE_ID',self.source['payload']['source_id']))
        self.enterContext(patch.object(app.staged,'STAGE',path.relative_to(self.root)))
        self.fx.material=self.source['payload']['distribution']
        self.fx.now=datetime(2026,11,16,6,tzinfo=timezone.utc)
        for c in self.fx.clocks:c.now.return_value=self.fx.now
        clock=self.enterContext(patch.object(app,'datetime',wraps=datetime));clock.now.return_value=self.fx.now;self.fx.clocks.append(clock)
        clock=self.enterContext(patch.object(app.repair,'datetime',wraps=datetime));clock.now.return_value=self.fx.now;self.fx.clocks.append(clock)
        self.before=copy.deepcopy(app.first.upload.read_json(self.root/'logs/publish_state.json',{}))
        self.files={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
        self.stagebytes=path.read_bytes()
    def core(self,unknown=False,fail_once=False):
        with patch.object(app,'assert_idle'),patch.object(app.staged.stage,'active_workers',return_value=[]), \
             patch.object(app.repair,'wait_session'),patch.object(app.repair,'ensure_background_identity',side_effect=lambda previous,page,entry:previous(page,entry)), \
             patch.object(app.staged.lock_recovery,'recover_locks'),patch.object(app.first,'execute',side_effect=lambda real:app.publish_stage()):
            return self.fx.core(unknown=unknown,fail_once=fail_once)
    def test_exact_source43_with_comments_and_no_duplicates_after_restart_preserves_all_history(self):
        result,events,comments=self.core();self.assertEqual(result,0)
        posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),43);self.assertNotIn(('fb17','personal'),posts)
        self.assertTrue(all(int(a[2:])<=24 for a,t in posts));self.assertEqual(len(comments[0]),43)
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for k,row in self.before.items():self.assertEqual(state[k],row)
        for path,data in self.files.items():self.assertEqual(path.read_bytes(),data)
        pointer=app.first.upload.read_json(self.root/'logs'/app.POINTER,{})
        value=app.first.archive.checked_json(self.root/'logs'/pointer['manifest'])
        self.assertEqual(value['payload']['date'],'2026-11-16');self.assertEqual(value['payload']['material_source_date'],'2026-11-14')
        self.assertEqual(value['payload']['stage_sha256'],self.source['sha256'])
        _,events,_=self.core();self.assertFalse(any(e=='post' for e,p in events))
        self.assertEqual((self.root/app.staged.STAGE).read_bytes(),self.stagebytes)
    def test_unknowns_are_preserved_and_never_reposted(self):
        result,events,_=self.core(unknown=True);self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),43)
        _,events,_=self.core(unknown=True);self.assertFalse(any(e=='post' for e,p in events))
    def test_prepost_network_failure_retried_only_for_exact_new_video(self):
        result,events,_=self.core(fail_once=True);self.assertEqual(result,0)
        self.assertEqual([p for e,p in events if e=='post'][-1],('fb02','page01'))
    def test_carry_partial14_keeps_published_and_posted_and_repairs_before_post_only(self):
        with patch.object(app.staged.stage,'active_workers',return_value=[]):app.staged.stage.import_stage(self.root,self.root/app.staged.STAGE)
        for c in self.fx.clocks:c.now.return_value=datetime(2026,11,14,7,tzinfo=timezone.utc)
        with patch.object(app.first,'DAY','2026-11-14'),patch.object(app.first,'MATERIAL_DAY','2026-11-14'), \
             patch.object(app.first,'SCOPE',app.staged.SCOPE),patch.object(app.first,'POINTER',app.staged.POINTER),patch.object(app.first,'ALLOWED',app.staged.ALLOWED):
            parent_path,parent=app.first.freeze()
        for c in self.fx.clocks:c.now.return_value=self.fx.now
        jobs=parent['payload']['jobs'][:3];state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for j,status in zip(jobs,['published','needs_review','failed_before_post']):
            video=self.root/'videos'/j['account']/j['target']/'inbox'/j['filename']
            row=dict(account=j['account'],target=j['target'],url=j['url'],video=str(video),status=status,uploader_version='2.47',ai_label_requested=False,
                     created='2026-11-14T07:01:00+00:00',source_frozen_manifest=parent_path.name,source_frozen_sha256=parent['sha256'],comment_status='sent' if status=='published' else 'not_started')
            if status!='failed_before_post':row['post_intent_at']='2026-11-14T07:02:00+00:00'
            if status=='published':
                folder=app.first.upload.archive(video,video.with_suffix('.txt'));row.update(archived_video=str(folder/video.name))
            state[j['key']]=row
        app.first.upload.save_json(self.root/'logs/publish_state.json',state);original=copy.deepcopy(state[jobs[0]['key']]);parentbytes=parent_path.read_bytes()
        result,events,_=self.core();self.assertEqual(result,3)
        posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),41)
        self.assertNotIn((jobs[0]['account'],jobs[0]['target']),posts);self.assertNotIn((jobs[1]['account'],jobs[1]['target']),posts)
        self.assertIn((jobs[2]['account'],jobs[2]['target']),posts)
        self.assertEqual(app.first.upload.read_json(self.root/'logs/publish_state.json',{})[jobs[0]['key']],original)
        self.assertEqual(parent_path.read_bytes(),parentbytes)
        _,events,_=self.core();self.assertFalse(any(e=='post' for e,p in events))
    def test_any_live_worker_stops_instead_of_waiting_or_mutating(self):
        with patch.object(app.staged.stage,'active_workers',return_value=[dict(pid=921,name='python.exe')]), \
             patch.object(app.staged.lock_recovery,'recover_locks') as recover,patch.object(app.staged.stage,'import_stage') as importer:
            with self.assertRaisesRegex(RuntimeError,'921'):app.publish_stage()
        recover.assert_not_called();importer.assert_not_called()
        self.assertEqual(app.first.upload.read_json(self.root/'logs/publish_state.json',{}),self.before)
    def test_expired_pointer_retired_with_backup_but_original_manifest_and_state_kept(self):
        # Create a valid old14 queue pointer without publishing it.
        p=dict(date='2026-11-14',distributed_scope=app.staged.SCOPE)
        v=dict(payload=p,sha256=app.first.batch.digest(p));name='frozen-material-2026-11-14-'+v['sha256'][:16]+'.json'
        path=self.root/'logs'/name;app.first.upload.save_json(path,v)
        old=self.root/'logs'/app.staged.POINTER;app.first.upload.save_json(old,dict(manifest=name,sha256=v['sha256']))
        statebytes=(self.root/'logs/publish_state.json').read_bytes();manifestbytes=path.read_bytes()
        completed=subprocess.CompletedProcess([],0,json.dumps(dict(removed=['FBUpload-Old'],preserved=['FutureTask'])).encode(),b'')
        with patch.object(app,'assert_idle'),patch.object(app.sys,'platform','win32'),patch.object(app.subprocess,'run',return_value=completed):backup=app.retire_queues()
        self.assertFalse(old.exists());self.assertTrue((backup/app.staged.POINTER).is_file())
        self.assertEqual(path.read_bytes(),manifestbytes);self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),statebytes)


class OldFirst24RetryTests(unittest.TestCase):
    def setUp(self):
        self.fx=ExplicitFifteenTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root;self.first=app.first
        self.distributed=self.fx.distributed;self.distributed.now=datetime(2026,11,16,6,tzinfo=timezone.utc)
        for c in self.distributed.clocks:c.now.return_value=self.distributed.now
        clock=self.enterContext(patch.object(app.repair,'datetime',wraps=datetime));clock.now.return_value=self.distributed.now
        spec={p:v for p,v in app.staged.guided.base.SPEC.items() if p[0]=='fb09' and p[1]!='personal'}
        # Existing fixture patches the old15 source spec to synthetic originals.
        self.enterContext(patch.object(app.repair,'SPEC',spec))
        self.fx.jobs=[self.fx.alljobs[p] for p in spec]
    def core(self,**kwargs):
        # Reuse the browser fixture against the NEW module, without invoking any
        # old date-guarded runner or loosening frozen video verification.
        import test_retry_nov13_prepost_fifteen_on_nov14 as fixture
        with patch.object(fixture,'app',app.repair):return self.fx.core(**kwargs)
    def test_only_ten_pages_no_personal17_or_new50_and_repeat_posts_zero(self):
        result,posts,_=self.core();self.assertEqual(result,0);self.assertEqual(len(posts),10)
        self.assertEqual(set(posts),set(app.repair.SPEC))
        state=self.first.upload.read_json(self.root/'logs/publish_state.json',{})
        keys={j['key'] for j in self.fx.jobs}
        for key,row in self.fx.before.items():
            if key not in keys:self.assertEqual(state[key],row)
        for path,data in self.fx.original_parents.items():self.assertEqual(path.read_bytes(),data)
        _,posts,_=self.core();self.assertEqual(posts,[])
    def test_interrupt_then_unknowns_never_resubmitted(self):
        _,posts,_=self.core(interrupt=True);self.assertEqual(len(posts),1)
        result,posts,_=self.core(unknown=True);self.assertEqual(result,3);self.assertEqual(len(posts),9)
        _,posts,_=self.core(unknown=True);self.assertEqual(posts,[])
    def test_nested_post_intent_excludes_retry_and_comments(self):
        j=self.fx.jobs[0];state=self.first.upload.read_json(self.root/'logs/publish_state.json',{})
        state[j['key']]['previous_before_post_attempt']={'post_intent_at':self.distributed.now.isoformat()}
        self.first.upload.save_json(self.root/'logs/publish_state.json',state)
        _,posts,comments=self.core();self.assertEqual(len(posts),9)
        self.assertNotIn((j['account'],j['target']),posts);self.assertTrue(all(j['key'] not in keys for keys in comments))


class ManualBrowserTests(unittest.TestCase):
    def setUp(self):
        app.SKIPPED.clear();self.entry=dict(account='fb09',target='page01',url='https://www.facebook.com/profile.php?id=61595182473231')
        self.context=MagicMock();self.page=MagicMock();self.context.pages=[self.page]
    def test_background_identity_success_returns_original_context_without_prompt(self):
        with patch.object(app,'NORMAL',return_value=self.context),patch.object(app.repair,'wait_session'),patch.object(app.first.upload,'ensure_identity'),patch('builtins.input') as prompt:
            self.assertIs(app.manual_launcher(MagicMock(),self.entry),self.context)
        prompt.assert_not_called()
    def test_manual_login_reuses_verified_context_and_skip_blocks_remaining_account(self):
        with patch.object(app,'NORMAL',side_effect=[app.repair.SessionNotReady('missing'),self.context]),patch.object(app,'require_day'), \
             patch.object(app.first.upload,'navigate_profile'),patch.object(app.repair,'wait_session'),patch.object(app.first.upload,'ensure_identity'),patch('builtins.input',return_value=''):
            self.assertIs(app.manual_launcher(MagicMock(),self.entry),self.context)
        with patch.object(app,'NORMAL',side_effect=[app.repair.SessionNotReady('missing'),self.context]),patch.object(app,'require_day'), \
             patch.object(app.first.upload,'navigate_profile'),patch('builtins.input',return_value='s'):
            with self.assertRaises(app.repair.SessionNotReady):app.manual_launcher(MagicMock(),self.entry)
        self.context.close.assert_called_once()
        with patch.object(app,'NORMAL') as launch:
            with self.assertRaises(app.repair.SessionNotReady):app.manual_launcher(MagicMock(),self.entry)
        launch.assert_not_called()


class OrchestrationTests(unittest.TestCase):
    def test_preflight_before_retirement_then_old_failures_then_original_stage(self):
        events=[]
        with patch.object(app,'require_day'),patch.object(app.first.workflow,'require_versions'),patch.object(app.staged.stage,'setup'), \
             patch.object(app.staged,'checked_stage',side_effect=lambda:events.append('check-stage')), \
             patch.object(app.repair,'source',side_effect=lambda:events.append('check-old')),patch.object(app,'assert_idle'), \
             patch.object(app.staged.lock_recovery,'recover_locks'),patch.object(app,'retire_queues',side_effect=lambda:events.append('retire')), \
             patch.object(app,'browser_fixes',side_effect=contextlib.nullcontext), \
             patch.object(app.repair,'execute',side_effect=lambda:events.append('old') or 3),patch.object(app,'publish_stage',side_effect=lambda:events.append('stage') or 0):
            self.assertEqual(app.execute(),3)
        self.assertEqual(events,['check-stage','check-old','retire','old','stage'])
    def test_bad_original_stage_cannot_retire_queue_or_start_publishing(self):
        with patch.object(app,'require_day'),patch.object(app.first.workflow,'require_versions'),patch.object(app.staged.stage,'setup'), \
             patch.object(app.staged,'checked_stage',side_effect=ValueError('bad source')),patch.object(app,'retire_queues') as retire, \
             patch.object(app.repair,'execute') as old,patch.object(app,'publish_stage') as new:
            with self.assertRaisesRegex(ValueError,'bad source'):app.execute()
        retire.assert_not_called();old.assert_not_called();new.assert_not_called()


if __name__=='__main__':unittest.main()
