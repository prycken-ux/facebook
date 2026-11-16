import contextlib,copy,shutil,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import publish_first24_ai_materials_20261116 as app
from test_publish_distributed_nov13_first24 import DistributedFirst24Tests
from test_modern_editor import ModernEditorTests,EDITOR


class AIOnFirst24Tests(unittest.TestCase):
    def setUp(self):
        self.fx=DistributedFirst24Tests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        self.fx.now=datetime(2026,11,16,6,tzinfo=timezone.utc)
        for c in self.fx.clocks:c.now.return_value=self.fx.now
        for module in (app,app.ai,app.extra,app.stage):
            c=self.enterContext(patch.object(module,'datetime',wraps=datetime));c.now.return_value=self.fx.now;self.fx.clocks.append(c)
        pool=self.root/'Nov16-new44';pool.mkdir()
        for n in range(1,45):(pool/f'clip-{n}.mp4').write_bytes(('AI footage Nov16 '+str(n)).encode())
        path,value=app.stage.prepare(self.root,pool,scope='existing24')
        with patch.object(app.stage,'active_workers',return_value=[]):app.stage.import_stage(self.root,path)
        app.first.upload.save_json(self.root/'material-staging/first24-pending-import.json',dict(manifest=str(path.relative_to(self.root)),sha256=value['sha256'],complete=True))
        self.fx.material=value['payload']['distribution'];self.source=value;self.stage_path=path
        self.before=copy.deepcopy(app.first.upload.read_json(self.root/'logs/publish_state.json',{}))
        self.files={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
        self.config=app.first.upload.CONFIG.read_bytes();self.original_run=app.first.upload.run_entry
    def core(self,unknown=False,fail_once=False,comment_retry=False,extra_failure=False,interrupt=False):
        calls=[]
        def run(entry,*args,**kwargs):
            self.assertIs(kwargs['ai_label_override'],True);calls.append((entry['account'],entry['target']))
            if extra_failure and len(calls)==1:
                with patch.object(app.first.upload,'prepare_reel',side_effect=RuntimeError('AI标签控件尚未可用，未点击发布。')):
                    return self.original_run(entry,*args,**kwargs)
            if interrupt and len(calls)==1:
                with patch.object(app.first.upload,'wait_for_receipt',side_effect=KeyboardInterrupt):
                    return self.original_run(entry,*args,**kwargs)
            return self.original_run(entry,*args,**kwargs)
        with patch.object(app,'assert_idle'),patch.object(app.browser.staged.lock_recovery,'recover_locks'), \
             patch.object(app.extra,'wait_session'),patch.object(app.extra,'ensure_background_identity',side_effect=lambda previous,page,entry:previous(page,entry)), \
             patch.object(app.first.upload,'run_entry',side_effect=run),patch.object(app.first,'execute',side_effect=app.execute):
            result,events,comments=self.fx.core(unknown=unknown,fail_once=fail_once,comment_retry=comment_retry)
        return result,events,comments,calls
    def primary(self):
        ptr=app.first.upload.read_json(self.root/'logs'/app.POINTER,{})
        path=self.root/'logs'/ptr['manifest'];return path,app.first.archive.checked_json(path)
    def test_all44_including17_have_ai_on_and_original_comments_without_touching_any_old_state(self):
        result,events,comments,calls=self.core();self.assertEqual(result,0)
        posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),44);self.assertIn(('fb17','personal'),posts)
        self.assertEqual(len(comments[0]),44);self.assertTrue(all(int(a[2:])<=24 for a,t in posts))
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in self.before.items():self.assertEqual(state[key],row)
        path,value=self.primary();self.assertIs(value['payload']['ai_label'],True)
        self.assertEqual(value['payload']['stage_sha256'],self.source['sha256'])
        for job in value['payload']['jobs']:self.assertIs(state[job['key']]['ai_label_requested'],True)
        self.assertEqual(app.first.upload.CONFIG.read_bytes(),self.config)
        for file,data in self.files.items():
            if file.name.startswith('20261116-'):continue
            self.assertEqual(file.read_bytes(),data)
        _,events,_,calls=self.core();self.assertFalse(any(e=='post' for e,p in events));self.assertEqual(calls,[])
    def test_ai_network_retry_and_extra_comment_pass_remain_scoped(self):
        result,events,comments,calls=self.core(fail_once=True,comment_retry=True);self.assertEqual(result,0)
        posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),44);self.assertEqual(posts[-1],('fb02','page01'))
        self.assertEqual(len(comments),2);self.assertEqual(len(calls),45)
    def test_proven_prepost_ai_label_failure_gets_one_durable_extra_chance(self):
        result,events,comments,calls=self.core(extra_failure=True);self.assertEqual(result,0)
        self.assertEqual(sum(e=='post' for e,p in events),44);self.assertEqual(calls.count(('fb01','page01')),2)
        self.assertEqual(len(calls),45)
        _,events,_,calls=self.core();self.assertFalse(any(e=='post' for e,p in events));self.assertEqual(calls,[])
    def test_unknown_post_receipts_never_resend_or_mark_success(self):
        result,events,_,calls=self.core(unknown=True);self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),44)
        _,events,_,calls=self.core(unknown=True);self.assertFalse(any(e=='post' for e,p in events));self.assertEqual(calls,[])
        _,value=self.primary();state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        self.assertTrue(all(state[j['key']]['status']=='needs_review' and state[j['key']]['ai_label_requested'] is True for j in value['payload']['jobs']))
    def test_post_interruption_resumes_other43_and_never_reposts_first(self):
        with self.assertRaises(KeyboardInterrupt):self.core(interrupt=True)
        result,events,_,calls=self.core();self.assertEqual(result,3)
        posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),43);self.assertNotIn(('fb01','page01'),posts)
    def test_downgraded_ai_manifest_is_rejected_before_any_new_attempt(self):
        self.core();path,value=self.primary();value['payload']['ai_label']=False;value['sha256']=app.first.batch.digest(value['payload'])
        changed=path.with_name('frozen-material-'+app.DAY+'-'+value['sha256'][:16]+'.json');app.first.upload.save_json(changed,value)
        app.first.upload.save_json(self.root/'logs'/app.POINTER,dict(manifest=changed.name,sha256=value['sha256']))
        with self.assertRaises(ValueError):self.core()
    def test_missing_ai_authorization_or_unfinished_allocation_refuses_before_upload(self):
        with self.assertRaisesRegex(ValueError,'尚未确认含AI'):app.execute(False)
        ptr=self.root/'material-staging/first24-pending-import.json';value=app.first.upload.read_json(ptr,{});value['complete']=False;app.first.upload.save_json(ptr,value)
        with self.assertRaisesRegex(ValueError,'尚未正式分配完成'):self.core()
        self.assertEqual(app.first.upload.read_json(self.root/'logs/publish_state.json',{}),self.before)
    def test_ai_hooks_restore_original_real_footage_guards_and_fb17_override_is_scoped(self):
        callbacks=(app.first.priority.validate,app.first.batch.run,app.first.priority.retry.load_source,app.first.priority.retry.decide)
        self.core()
        self.assertEqual(callbacks,(app.first.priority.validate,app.first.batch.run,app.first.priority.retry.load_source,app.first.priority.retry.decide))
        with patch.object(app.first.batch,'excluded_accounts',return_value={'fb17','fb99'}):
            with app.ai.installed(self.source['sha256']):self.assertEqual(app.first.batch.excluded_accounts(app.DAY),{'fb99'})
            self.assertEqual(app.first.batch.excluded_accounts(app.DAY),{'fb17','fb99'})
    def test_stale_source_day_or_wrong_allocation_hash_refuses(self):
        value=app.first.upload.read_json(self.stage_path,{});value['payload']['date']='2026-11-14';app.first.upload.save_json(self.stage_path,value)
        with self.assertRaises(ValueError):self.core()
    def test_changed_new_file_is_not_replaced_by_another_inbox_video(self):
        row=self.fx.material['payload']['assignments'][0];video=self.root/'videos'/row['account']/row['target']/'inbox'/row['files'][-1]['destination_name']
        video.write_bytes(b'changed input')
        result,events,_,_=self.core();self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),43)
        self.assertTrue(video.is_file());self.assertEqual(video.read_bytes(),b'changed input')
    def test_retry_queue_cannot_downgrade_ai_label_or_change_primary_jobs(self):
        self.core();path,value=self.primary();payload=copy.deepcopy(value['payload'])
        payload.update(jobs=payload['jobs'][:1],run_kind='automatic-safe-retry-v1',source_manifest=path.name,source_sha256=value['sha256'],ai_label=False)
        checksum=app.first.batch.digest(payload);queue=path.with_name('automatic-retry-'+app.DAY+'-'+checksum[:16]+'.json')
        candidate=dict(payload=payload,sha256=checksum,comment_timing=app.first.priority.TIMING)
        with app.ai.installed(self.source['sha256']):
            with self.assertRaises(ValueError):app.ai.validate_run_manifest(queue,candidate)
    def test_pending_ai_video_comment_is_verification_only(self):
        self.core();_,value=self.primary();state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        job=value['payload']['jobs'][0];state[job['key']]['comment_status']='needs_review'
        selected,_=app.first.priority.comment_retry.candidates(value,state,{},dict(jobs={}))
        self.assertEqual([(j['key'],mode) for j,key,mode in selected],[(job['key'],'verify_only')])
    def test_launch_failure_before_media_is_persisted_as_ai_failure_without_overwriting_existing_rows(self):
        assigned=self.fx.material['payload']['assignments'][0]
        entry=next(e for e in app.first.upload.read_json(app.first.upload.CONFIG,{})['targets'] if (e['account'],e['target'])==(assigned['account'],assigned['target']))
        file=app.first.upload.inbox_for(entry)/assigned['files'][-1]['destination_name']
        job=dict(account=entry['account'],target=entry['target'],url=entry['url'],filename=file.name,key=app.first.upload.job_key(entry,file))
        value=dict(sha256='a'*64);path=self.root/'logs'/('frozen-material-'+app.DAY+'-'+'a'*16+'.json')
        def failed(*args):raise app.browser.repair.SessionNotReady('等待登录确认')
        launch=app.scoped_launcher(failed,[job],path,value)
        with self.assertRaises(app.browser.repair.SessionNotReady):launch(None,entry)
        recorded=app.first.upload.read_json(self.root/'logs/publish_state.json',{})[job['key']]
        self.assertEqual(recorded['status'],'failed_before_post');self.assertIs(recorded['ai_label_requested'],True)
        self.assertTrue(recorded['before_media_launch_failure']);self.assertNotIn('post_intent_at',recorded)
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{});state[job['key']].update(status='published',post_intent_at=self.fx.now.isoformat())
        app.first.upload.save_json(self.root/'logs/publish_state.json',state);published=copy.deepcopy(state[job['key']])
        with self.assertRaises(app.browser.repair.SessionNotReady):launch(None,entry)
        self.assertEqual(app.first.upload.read_json(self.root/'logs/publish_state.json',{})[job['key']],published)
        state.pop(job['key']);app.first.upload.save_json(self.root/'logs/publish_state.json',state)
        app.first.upload.save_json(path.with_name(path.stem+'-results.json'),dict(rows=[dict(key=job['key'],video_status='published')]))
        with self.assertRaises(app.browser.repair.SessionNotReady):launch(None,entry)
        self.assertNotIn(job['key'],app.first.upload.read_json(self.root/'logs/publish_state.json',{}))


class AIWorkerChainTests(unittest.TestCase):
    def test_own_four_layer_chain_exempt_but_other_publisher_preserved(self):
        import subprocess
        from test_nov16_venv_process_chain import VenvProcessChainTests
        fx=VenvProcessChainTests();fx.setUp();rows=copy.deepcopy(fx.rows)
        body=fx.body.replace('start_finish_first24_nov16','start_publish_first24_ai_20261116').replace('verified-nov16-first24-and-nov14-stage','verified-ai-first24-publication')
        for row in rows[2:]:row['command']=subprocess.list2cmdline([fx.exe,'-u','-c',body,fx.root])
        rows.append(fx.row(96,1,['-u',fx.root+r'\finish_first24_nov14_on_nov16.py',fx.root]))
        with patch.object(app.workers,'BOOTSTRAP',app.BOOTSTRAP):blocking,own=app.workers.classify_workers(rows,fx.root,100,fx.runner)
        self.assertEqual(own,[97,98,99,100]);self.assertEqual([r['pid'] for r in blocking],[96])


class AIOnNativeControlTests(ModernEditorTests):
    def test_ai_label_true_clicks_visible_parent_and_checks_hidden_native_before_post(self):
        self.entry['ai_label']=True
        self.editor=EDITOR.replace('id="ai" type="checkbox"','id="ai" style="display:none" type="checkbox"')
        self.editor=self.editor.replace('aria-label="Add AI label Add AI label We require you to label content"',
            'aria-label="Add AI label Add AI label We require you to label content" onclick="document.querySelector(\'#ai\').checked=!document.querySelector(\'#ai\').checked;window.aiParentClicks=(window.aiParentClicks||0)+1"')
        with app.first.editor.installed():button,_=self.prepare()
        self.assertTrue(self.page.locator('#ai').is_checked());self.assertEqual(self.page.evaluate('window.aiParentClicks'),1)
        self.assertTrue(button.is_enabled());self.assertIsNone(self.page.evaluate('window.postClicks'))
    def test_unverifiable_ai_switch_true_stops_without_clicking_post(self):
        self.page.set_content('<button aria-label="Add AI label"><span>Unknown</span></button><button onclick="window.posts=1">Post</button>')
        with self.assertRaises(RuntimeError):app.first.editor.set_modern_ai(self.page,dict(ai_label=True),timeout_ms=100)
        self.assertIsNone(self.page.evaluate('window.posts'))


if __name__=='__main__':unittest.main()
