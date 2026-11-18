import copy,hashlib,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import publish_eligible78_materials_20261117 as app
import distribute_eligible78_materials_20261117 as distribution
from test_publish_all_distributed_nov13 import TwoWavePublicationTests

class Eligible78PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fx=TwoWavePublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.runfx=self.fx.fx;self.root=self.fx.root
        self.runfx.now=datetime(2026,11,17,6,tzinfo=timezone.utc)
        for c in self.runfx.clocks:c.now.return_value=self.runfx.now
        for module in (app,app.queued,app.extra,distribution.stage):
            clock=self.enterContext(patch.object(module,'datetime',wraps=datetime));clock.now.return_value=self.runfx.now;self.runfx.clocks.append(clock)
        pool=self.root/'Nov17-78';pool.mkdir()
        for n in range(1,79):(pool/f'{n}.mp4').write_bytes(('Nov17 fresh real scene '+str(n)).encode())
        with patch.object(distribution,'inspect_workers',return_value=[]),patch.object(distribution.recovery,'recover_locks'):distribution.execute(self.root,pool)
        _,self.source,self.journal,self.material=app.allocation(self.root);self.runfx.material=self.material
        self.before_state=copy.deepcopy(app.first.upload.read_json(self.root/'logs/publish_state.json',{}));self.prefs=(self.root/'publication_preferences.json').read_bytes()
        self.before_config=app.first.upload.read_json(app.first.upload.CONFIG,{})
        self.protected={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file() and p.relative_to(self.root).parts[1] in app.BLOCKED}
        self.original_run=app.first.upload.run_entry
    def core(self,unknown=False,fail_account=None,network=False,comment_retry=False,midnight=False,manual=False,login_account=None):
        calls=[];failed=[];crossed=[];phases=[];manual_called=[]
        def discover(account):
            if account==fail_account:raise ValueError('Login required for this profile')
            return self.fx.discover(account)
        def run(entry,*args,**kwargs):
            self.assertIs(kwargs['ai_label_override'],False);self.assertNotIn(entry['account'],app.BLOCKED);calls.append(entry['account'])
            if entry['account']==login_account:
                with patch.object(app.first.upload,'prepare_reel',side_effect=RuntimeError('Login required for original account')):return self.original_run(entry,*args,**kwargs)
            if network and entry['account']=='fb02' and not failed:
                failed.append(True)
                with patch.object(app.first.upload,'prepare_reel',side_effect=RuntimeError('net::ERR_CONNECTION_RESET')):return self.original_run(entry,*args,**kwargs)
            result=self.original_run(entry,*args,**kwargs)
            if midnight and not crossed:
                crossed.append(True);self.runfx.now=datetime(2026,11,17,16,5,tzinfo=timezone.utc)
                for c in self.runfx.clocks:c.now.return_value=self.runfx.now
            return result
        phase=app.run_phase
        def step(name,*args):phases.append(name);return phase(name,*args)
        def prompt(text):
            manual_called.append((text,list(phases)))
            return '' if manual else 'S'
        with patch.object(app.workers,'active_workers',return_value=[]),patch.object(app.browser.staged.lock_recovery,'recover_locks'), \
             patch.object(app.owners,'discover_background',side_effect=discover),patch.object(app.owners.guided,'prompt',side_effect=prompt), \
             patch.object(app.extra,'wait_session'),patch.object(app.extra,'ensure_background_identity',side_effect=lambda previous,page,entry:previous(page,entry)), \
             patch.object(app.first.upload,'run_entry',side_effect=run),patch.object(app,'run_phase',side_effect=step), \
             patch.object(app.first,'execute',side_effect=lambda real:app.execute(self.root,real)):
            result,events,comments=self.runfx.core(unknown=unknown,include_new=True,comment_retry=comment_retry)
        return result,events,comments,calls,phases,manual_called
    def test_exact78_real_off_excludes16_including23_preserves_old_history_and_replay_zero(self):
        result,events,comments,calls,phases,prompts=self.core();self.assertEqual(result,0)
        posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),78);self.assertEqual(set(posts),app.EXPECTED)
        self.assertFalse(set(calls)&app.BLOCKED);self.assertFalse(prompts)
        self.assertLess(max(i for i,p in enumerate(phases) if p=='videos'),min(i for i,p in enumerate(phases) if p=='retry'))
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in self.before_state.items():self.assertEqual(state[key],row)
        for file,data in self.protected.items():self.assertEqual(file.read_bytes(),data)
        self.assertEqual((self.root/'publication_preferences.json').read_bytes(),self.prefs)
        rows=[r for k,r in state.items() if k not in self.before_state];self.assertEqual(len(rows),78);self.assertTrue(all(r['ai_label_requested'] is False for r in rows));self.assertTrue(all(r['comment_status']=='sent' for r in rows))
        available=app.first.upload.read_json(self.root/app.AVAILABILITY,{})['payload'];self.assertEqual(available['excluded_accounts'],sorted(app.BLOCKED))
        result,events,_,calls,_,_=self.core();self.assertEqual(result,0);self.assertFalse(any(e=='post' for e,p in events));self.assertEqual(calls,[])
    def test_stale_foreground_modes_retired_without_resetting_original_progress(self):
        self.core();request_path=self.root/app.REQUEST;request_bytes=request_path.read_bytes();req=app.first.upload.read_json(request_path,{})
        path=self.root/'logs'/('eligible78-real-publication-'+req['sha256'][:16]+'.json');control=app.first.upload.read_json(path,{})
        control['modes'].update(fb03='foreground_minimized',fb09='foreground');app.first.upload.save_json(path,control)
        frozen={self.root/'logs'/w['manifest']:(self.root/'logs'/w['manifest']).read_bytes() for w in control['waves']}
        state=(self.root/'logs/publish_state.json').read_bytes()
        with patch.object(app.owners.guided,'minimized_chrome',side_effect=AssertionError('Do not reuse foreground fallback')):
            result,events,_,_,_,_=self.core()
        self.assertEqual(result,0);self.assertFalse(any(e=='post' for e,p in events));self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),state)
        updated=app.first.upload.read_json(path,{})
        self.assertEqual(updated['modes']['fb03'],'background');self.assertEqual(updated['modes']['fb09'],'background');self.assertEqual(len(updated['retired_foreground_mode_history']),1)
        self.assertEqual(request_path.read_bytes(),request_bytes)
        for file,data in frozen.items():self.assertEqual(file.read_bytes(),data)
    def test_recoverable_network_and_comment_failures_retry_after_other_videos(self):
        result,events,comments,_,phases,_=self.core(network=True,comment_retry=True);self.assertEqual(result,0)
        posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),78);self.assertEqual(posts[-1],('fb02','page01'));self.assertGreaterEqual(len(comments),2)
    def test_unknown_submissions_never_upload_twice(self):
        result,events,_,_,_,prompts=self.core(unknown=True);self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),78);self.assertTrue(prompts)
        _,events,_,_,_,_=self.core(unknown=True);self.assertFalse(any(e=='post' for e,p in events))
    def test_early_unavailable_new25_skips_and_manual_prompt_is_after_all_auto_phases(self):
        result,events,_,calls,phases,prompts=self.core(fail_account='fb25');self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),77)
        self.assertNotIn('fb25',calls);self.assertTrue(prompts);self.assertIn('comment_retry',prompts[0][1]);self.assertIn('fb26',calls)
        result,events,_,calls,_,_=self.core();self.assertEqual(result,0);self.assertEqual([p for e,p in events if e=='post'],[('fb25','personal')])
    def test_cross_midnight_continues_same_frozen_scope_off_actual_timestamps(self):
        result,events,_,_,_,_=self.core(network=True,midnight=True);self.assertEqual(result,0);self.assertEqual(sum(e=='post' for e,p in events),78)
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        self.assertTrue(any(datetime.fromisoformat(r['published_at']).astimezone(app.first.batch.BJ).day==18 for k,r in state.items() if k not in self.before_state))
    def test_manual_new_login_only_after77_then_publishes_missing_one(self):
        entry,proof=self.fx.discover('fb25')
        with patch.object(app,'manual_new',return_value=(entry,proof,'background')) as manual:
            result,events,_,_,phases,prompts=self.core(fail_account='fb25',manual=True)
        self.assertEqual(result,0);self.assertEqual(sum(e=='post' for e,p in events),78);manual.assert_called_once_with('fb25');self.assertIn('comment_retry',prompts[0][1])
        self.assertEqual([p for e,p in events if e=='post'][-1],('fb25','personal'))
    def test_user_skipped_old_account_gets_no_extra_video_attempt_after_manual(self):
        with patch.object(app,'manual_existing',return_value=None) as manual:
            result,events,_,calls,_,prompts=self.core(login_account='fb02',manual=True)
        self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),77);self.assertEqual(calls.count('fb02'),1);self.assertTrue(prompts);manual.assert_called_once()
    def test_orphan_primary_recovers_even_if_ready_scope_changed_after_crash(self):
        self.core(fail_account='fb25')
        request=app.first.upload.read_json(self.root/app.REQUEST,{})
        control=self.root/'logs'/('eligible78-real-publication-'+request['sha256'][:16]+'.json')
        value=app.first.upload.read_json(control,{});value['waves']=[];app.first.upload.save_json(control,value)
        result,events,_,_,_,_=self.core();self.assertEqual(result,0);self.assertEqual([p for e,p in events if e=='post'],[('fb25','personal')])
    def test_new_pending_comments_are_verification_only(self):
        self.core();request=app.first.upload.read_json(self.root/app.REQUEST,{})
        control=app.first.upload.read_json(self.root/'logs'/('eligible78-real-publication-'+request['sha256'][:16]+'.json'),{})
        value=app.first.archive.checked_json(self.root/'logs'/control['waves'][0]['manifest']);job=value['payload']['jobs'][0]
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{});state[job['key']]['comment_status']='needs_review'
        selected,_=app.first.priority.comment_retry.candidates(value,state,{},dict(jobs={}))
        self.assertEqual([(j['key'],mode) for j,key,mode in selected],[(job['key'],'verify_only')])
    def test_login_failure_defers_other_pages_of_same_account_and_continues_healthy_account(self):
        from unittest.mock import MagicMock
        pairs=[('fb09','personal'),('fb09','page01'),('fb10','personal')];jobs=[];entries=[]
        config=app.first.upload.read_json(app.first.upload.CONFIG,{})['targets']
        for pair in pairs:
            entry=next(e for e in config if (e['account'],e['target'])==pair);entries.append(entry)
            row=next(r for r in self.material['payload']['assignments'] if (r['account'],r['target'])==pair)
            video=app.first.upload.inbox_for(entry)/row['files'][-1]['destination_name']
            jobs.append(dict(account=pair[0],target=pair[1],url=entry['url'],filename=video.name,key=app.first.upload.job_key(entry,video)))
        calls=[];context=MagicMock();context.pages=[MagicMock()]
        def factory(pw,entry):
            calls.append(entry['account'])
            if entry['account']=='fb09':raise app.extra.SessionNotReady('Login required')
            return context
        deferred={};launch=app.media_launcher(factory,jobs,self.root/'logs/frozen.json',dict(sha256='a'*64),deferred)
        with patch.object(app.extra,'wait_session'),patch.object(app.first.upload,'ensure_identity'):
            for entry in entries[:2]:
                with self.assertRaises(app.extra.SessionNotReady):launch(None,entry)
            self.assertIs(launch(None,entries[2]),context)
        self.assertEqual(calls,['fb09','fb10']);state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        self.assertTrue(all(state[j['key']]['status']=='failed_before_post' and not state[j['key']].get('post_intent_at') for j in jobs[:2]))
    def test_missing_problem_account_slots_do_not_block_or_restore_those_accounts(self):
        path=self.root/'additional_personal_accounts.json';value=app.first.upload.read_json(path,{})
        removed=app.BLOCKED&app.owned.NEW
        for account in removed:value['slots'].pop(account,None)
        app.first.upload.save_json(path,value)
        result,events,_,_,_,_=self.core();self.assertEqual(result,0);self.assertEqual(sum(e=='post' for e,p in events),78)
        self.assertFalse(removed&set(app.first.upload.read_json(path,{})['slots']))
    def test_interrupted_distribution_receipt_is_finished_before_publish_without_new_picker(self):
        path=self.root/'material-staging/eligible78-pending-import.json';value=app.first.upload.read_json(path,{})
        value['complete']=False;app.first.upload.save_json(path,value)
        sibling=app.sibling
        def load(name):return distribution if name=='distribute_eligible78_materials_20261117.py' else sibling(name)
        with patch.object(distribution.stage.materials,'choose_source',side_effect=AssertionError('Do not choose another source')),patch.object(distribution.recovery,'recover_locks'),patch.object(app,'sibling',side_effect=load):
            result,events,_,_,_,_=self.core()
        self.assertEqual(result,0);self.assertEqual(sum(e=='post' for e,p in events),78)
        self.assertTrue(app.first.upload.read_json(path,{})['complete'])
    def test_old_deleted_generation_is_rejected_before_any_upload(self):
        path=self.root/'additional_personal_accounts.json';value=app.first.upload.read_json(path,{})
        value['slots']['fb25']['batch_id']='old-deleted-fb25';app.first.upload.save_json(path,value)
        with self.assertRaisesRegex(ValueError,'原预留代次|代次变化'):self.core()
    def test_ai_true_or_changed_material_authorization_refused(self):
        self.core();path=self.root/app.REQUEST;value=app.first.upload.read_json(path,{});value['payload']['ai_label']=True;value['sha256']=app.first.batch.digest(value['payload']);app.first.upload.save_json(path,value)
        with self.assertRaisesRegex(ValueError,'标签'):self.core()
    def test_missing_distribution_or_unconfirmed_real_refuses_before_post(self):
        with self.assertRaisesRegex(ValueError,'确认实拍'):app.execute(self.root,False)
        path=self.root/'material-staging/eligible78-pending-import.json';value=app.first.upload.read_json(path,{});path.unlink()
        with self.assertRaisesRegex(ValueError,'原分配清单'):self.core()

class Eligible78WorkerTests(unittest.TestCase):
    def test_four_layer_venv_chain_is_verified_but_old_publisher_still_blocks(self):
        import subprocess
        from test_nov16_venv_process_chain import VenvProcessChainTests
        f=VenvProcessChainTests();f.setUp();rows=copy.deepcopy(f.rows)
        body=f.body.replace('start_finish_first24_nov16','start_publish_eligible78_real_20261117').replace('verified-nov16-first24-and-nov14-stage','verified-real-eligible78-publication')
        for row in rows[2:]:row['command']=subprocess.list2cmdline([f.exe,'-u','-c',body,f.root])
        rows.append(f.row(96,1,['-u',f.root+r'\publish_queued_new50_20261116.py',f.root]))
        with patch.object(app.workers,'BOOTSTRAP',app.BOOTSTRAP):workers,allowed=app.workers.classify_workers(rows,f.root,100,f.runner)
        self.assertEqual(allowed,[97,98,99,100]);self.assertEqual([r['pid'] for r in workers],[96])

if __name__=='__main__':unittest.main()
