import contextlib,copy,hashlib,json,os,subprocess,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
import prepare_new50_queue_20261116 as prep
import publish_queued_new50_20261116 as app
from test_publish_all_distributed_nov13 import TwoWavePublicationTests


class New50QueueTests(unittest.TestCase):
    def setUp(self):
        self.fx=TwoWavePublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.runfx=self.fx.fx;self.root=self.fx.root;self.runfx.now=datetime(2026,11,16,6,tzinfo=timezone.utc)
        for c in self.runfx.clocks:c.now.return_value=self.runfx.now
        for module in (prep,prep.stage,app,app.queued,app.extra):
            clock=self.enterContext(patch.object(module,'datetime',wraps=datetime));clock.now.return_value=self.runfx.now;self.runfx.clocks.append(clock)
        self.pool=self.root/'Nov16-94';self.pool.mkdir()
        for n in range(1,95):(self.pool/f'{n}.mp4').write_bytes(('Nov16 distinct asset '+str(n)).encode())
        import stage_next_materials_20261116_v2 as first24
        c=self.enterContext(patch.object(first24,'datetime',wraps=datetime));c.now.return_value=self.runfx.now
        self.firstpath,self.firststage=first24.prepare(self.root,self.pool,scope='existing24')
        with patch.object(first24,'active_workers',return_value=[]):first24.import_stage(self.root,self.firstpath)
        prep.first.upload.save_json(self.root/'material-staging/first24-pending-import.json',dict(manifest=str(self.firstpath.relative_to(self.root)),sha256=self.firststage['sha256'],complete=True))
        old_entry=next(r for r in prep.first.upload.read_json(prep.first.upload.CONFIG,{})['targets'] if (r['account'],r['target'])==('fb01','page01'))
        old_video=prep.first.upload.inbox_for(old_entry)/self.firststage['payload']['distribution']['payload']['assignments'][0]['files'][-1]['destination_name']
        old_state=prep.first.upload.read_json(self.root/'logs/publish_state.json',{});self.ai_key=prep.first.upload.job_key(old_entry,old_video)
        old_state[self.ai_key]=dict(account='fb01',target='page01',url=old_entry['url'],video=str(old_video),status='needs_review',
                                   ai_label_requested=True,uploader_version='2.47',created=self.runfx.now.isoformat(),post_intent_at=self.runfx.now.isoformat())
        prep.first.upload.save_json(self.root/'logs/publish_state.json',old_state)
        self.before_files={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
        self.before_state=copy.deepcopy(prep.first.upload.read_json(self.root/'logs/publish_state.json',{}))
        self.old_rows={ (r['account'],r['target']):copy.deepcopy(r) for r in prep.first.upload.read_json(prep.first.upload.CONFIG,{})['targets'] if int(r['account'][2:])<=24}
        self.preferences=(self.root/'publication_preferences.json').read_bytes()
        self.original_run=app.first.upload.run_entry
    def prepare(self):
        pointer,value=prep.prepare(self.root,self.pool);_,_,path,source=prep.checked_queue(self.root)
        self.runfx.material=source['payload']['distribution'];return pointer,value,path,source
    def core(self,unknown=False,fail_account=None,network=False,midnight=False):
        self.prepare();calls=[];crossed=[];failed=[]
        def discover(account):
            if account==fail_account:raise ValueError('Login required')
            return self.fx.discover(account)
        def run(entry,*args,**kwargs):
            self.assertIs(kwargs['ai_label_override'],False);calls.append(entry['account'])
            if network and entry['account']=='fb25' and not failed:
                failed.append(True)
                with patch.object(app.first.upload,'prepare_reel',side_effect=RuntimeError('net::ERR_CONNECTION_RESET')):return self.original_run(entry,*args,**kwargs)
            result=self.original_run(entry,*args,**kwargs)
            if midnight and not crossed:
                crossed.append(True);self.runfx.now=datetime(2026,11,16,16,5,tzinfo=timezone.utc)
                for c in self.runfx.clocks:c.now.return_value=self.runfx.now
            return result
        with patch.object(app.workers,'active_workers',return_value=[]),patch.object(app,'first24_finished',return_value=True), \
             patch.object(app.browser.staged.lock_recovery,'recover_locks'),patch.object(app.owners,'discover_background',side_effect=discover), \
             patch.object(app.owners.guided,'prompt',return_value='S'),patch.object(app.browser.repair,'wait_session'),patch.object(app.extra,'wait_session'), \
             patch.object(app.extra,'ensure_background_identity',side_effect=lambda previous,page,entry:previous(page,entry)), \
             patch.object(app.first.upload,'run_entry',side_effect=run),patch.object(app.first,'execute',side_effect=lambda real:app.execute(self.root)):
            result,events,comments=self.runfx.core(unknown=unknown,include_new=True)
        return result,events,comments,calls
    def test_prepare50_natural_order_excludes_first44_and_touches_no_live_files(self):
        locks=[self.root/'logs'/n for n in ('batch.lock','upload.lock')]
        for p in locks:p.write_bytes(b'old-publisher')
        pointer,queue,path,source=self.prepare();rows=source['payload']['distribution']['payload']['assignments']
        self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(45,95)])
        self.assertEqual({r['account'] for r in rows},prep.owned.NEW);self.assertTrue(all(r['target']=='personal' for r in rows))
        self.assertIs(queue['payload']['ai_label'],False)
        for file,data in self.before_files.items():self.assertEqual(file.read_bytes(),data)
        for p in locks:self.assertEqual(p.read_bytes(),b'old-publisher');p.unlink()
        self.assertEqual(prep.prepare(self.root,self.pool)[1],queue)
        self.assertTrue(path.parent.name.endswith('-reserved50'))
    def test_all50_publish_false_including_new_generation25_26_and_replay_zero_posts(self):
        result,events,comments,calls=self.core();self.assertEqual(result,0)
        posts=[p for e,p in events if e=='post'];self.assertEqual([a for a,t in posts],sorted(prep.owned.NEW));self.assertEqual(len(posts),50)
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in self.before_state.items():self.assertEqual(state[key],row)
        self.assertIs(state[self.ai_key]['ai_label_requested'],True)
        config=app.first.upload.read_json(app.first.upload.CONFIG,{})
        for row in config['targets']:
            if int(row['account'][2:])<=24:self.assertEqual(row,self.old_rows[row['account'],row['target']])
        for file,data in self.before_files.items():self.assertEqual(file.read_bytes(),data)
        self.assertEqual((self.root/'publication_preferences.json').read_bytes(),self.preferences)
        new=[r for k,r in state.items() if k not in self.before_state];self.assertEqual(len(new),50);self.assertTrue(all(r['ai_label_requested'] is False for r in new))
        result,events,_,calls=self.core();self.assertEqual(result,0);self.assertFalse(any(e=='post' for e,p in events));self.assertEqual(calls,[])
    def test_cross_midnight_real_clock_continues_network_retry_and_comments_without_relabel(self):
        result,events,comments,calls=self.core(network=True,midnight=True);self.assertEqual(result,0)
        posts=[p for e,p in events if e=='post'];self.assertEqual(len(posts),50);self.assertEqual(posts[-1],('fb25','personal'))
        self.assertEqual(self.runfx.now.astimezone(app.first.batch.BJ).date().isoformat(),'2026-11-17')
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        rows=[r for k,r in state.items() if k not in self.before_state]
        self.assertTrue(any(datetime.fromisoformat(r['published_at']).astimezone(app.first.batch.BJ).day==17 for r in rows))
        self.assertTrue(all(r['comment_status']=='sent' and r['ai_label_requested'] is False for r in rows))
    def test_unknown_receipts_never_resend_and_old_first24_state_is_preserved(self):
        result,events,_,_=self.core(unknown=True);self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),50)
        _,events,_,calls=self.core(unknown=True);self.assertFalse(any(e=='post' for e,p in events));self.assertEqual(calls,[])
    def test_late_login_adds_only_one_missing_account_without_reposting_previous49(self):
        result,events,_,_=self.core(fail_account='fb74');self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),49)
        result,events,_,calls=self.core();self.assertEqual(result,0);self.assertEqual([p for e,p in events if e=='post'],[('fb74','personal')])
    def test_first24_not_finished_returns_wait_code_before_import_or_registration(self):
        self.prepare()
        with patch.object(app.workers,'active_workers',return_value=[]),patch.object(app,'first24_finished',return_value=False),patch.object(app.stage,'import_stage') as copy,patch.object(app,'initial_ready') as ready:
            self.assertEqual(app.execute(self.root),75)
        copy.assert_not_called();ready.assert_not_called()
    def test_old_deleted_generation_never_adopted(self):
        self.prepare();path=self.root/'additional_personal_accounts.json';value=app.first.upload.read_json(path,{})
        value['slots']['fb25']['batch_id']='old-deleted-fb25';app.first.upload.save_json(path,value)
        with self.assertRaisesRegex(ValueError,'新50账号批次'):prep.checked_queue(self.root)
    def test_byte_identical_renamed_first44_ai_asset_is_not_allocated_as_real(self):
        (self.pool/'0.mp4').write_bytes((self.pool/'1.mp4').read_bytes())
        _,_,_,source=self.prepare()
        self.assertNotIn('0.mp4',[r['video_filename'] for r in source['payload']['distribution']['payload']['assignments']])
    def test_first24_order_gate_requires_bound_plan_full_first_pass_and_honest_hash(self):
        _,queue,_,_=self.prepare();self.assertFalse(app.first24_finished(self.root,queue))
        jobs=[dict(key=str(n)*64) for n in (1,2)]
        payload=dict(stage_sha256=self.firststage['sha256'],jobs=jobs);value=dict(payload=payload,sha256=app.first.batch.digest(payload))
        name='frozen-material-2026-11-16-'+value['sha256'][:16]+'.json';path=self.root/'logs'/name
        app.first.upload.save_json(path,value);app.first.upload.save_json(self.root/'logs/nov16-new-first24-ai-disclosure-on-publication.json',dict(manifest=name,sha256=value['sha256']))
        report=path.with_name(path.stem+'-results.json');app.first.upload.save_json(report,dict(manifest=name,attempts=[dict(key=jobs[0]['key'])]))
        self.assertFalse(app.first24_finished(self.root,queue))
        app.first.upload.save_json(report,dict(manifest=name,attempts=[dict(key=j['key']) for j in jobs]))
        self.assertTrue(app.first24_finished(self.root,queue))
        value['payload']['stage_sha256']='a'*64;app.first.upload.save_json(path,value)
        with self.assertRaises(ValueError):app.first24_finished(self.root,queue)
    def test_prepare_start_detaches_waiter_without_holding_a_python_process(self):
        self.prepare()
        with patch.object(prep.sys,'platform','win32'),patch.object(prep.subprocess,'Popen') as start:
            self.assertEqual(prep.start(self.root),0)
        args=start.call_args.args[0];self.assertEqual(args[0],'powershell.exe');self.assertIn('-File',args)
        self.assertEqual(start.call_args.kwargs['creationflags'],0x00000010)
        self.assertNotIn('shell',start.call_args.kwargs)
    def test_interrupted_copy_resumes_original_allocation_after_midnight(self):
        real=prep.stage.materials.copy_exact
        def interrupted(*args,**kwargs):real(*args,**kwargs);raise KeyboardInterrupt
        with patch.object(prep.stage.materials,'copy_exact',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):prep.prepare(self.root,self.pool)
        source_record=prep.first.upload.read_json(self.root/'material-staging/new50-prepare/source.json',{})
        original=(self.root/source_record['manifest']).read_bytes()
        self.runfx.now=datetime(2026,11,16,16,10,tzinfo=timezone.utc)
        for c in self.runfx.clocks:c.now.return_value=self.runfx.now
        _,queue,manifest,source=self.prepare()
        self.assertEqual(queue['payload']['material_date'],'2026-11-16')
        self.assertEqual(manifest.read_bytes(),original)
        self.assertEqual(source['payload']['distribution']['payload']['assignments'][0]['video_filename'],'45.mp4')
    def test_ai_or_unconfirmed_reclassification_is_refused(self):
        pointer,queue,_,_=self.prepare()
        for field,value in [('ai_label',True),('real_footage_confirmed',False)]:
            altered=copy.deepcopy(queue);altered['payload'][field]=value;altered['sha256']=prep.stage.materials.digest(altered['payload'])
            prep.first.upload.save_json(pointer,altered)
            with self.assertRaises(ValueError):prep.checked_queue(self.root)
        prep.first.upload.save_json(pointer,queue)


class QueuePowerShellTests(unittest.TestCase):
    def test_full_waiter_invokes_correct_venv_paths_prepares_then_publishes(self):
        import tempfile
        pwsh=Path('/tmp/nov16-pwsh/pwsh')
        if not pwsh.is_file():self.skipTest('PowerShell unavailable')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'project with space';root.mkdir()
            binary=root/'.venv/Scripts/python.exe';binary.parent.mkdir(parents=True)
            queue=root/'queue.json';calls=root/'calls.jsonl'
            shim="#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\nargs=sys.argv[1:]\nwith Path("+repr(str(calls))+").open('a') as out:out.write(json.dumps(args)+'\\n')\nif '--prepare-only' in args:Path("+repr(str(queue))+").write_text(json.dumps({'payload':{'authorization':'user-confirmed-real-new50-request-20261116-v1'},'sha256':'a'*64}))\n"
            binary.write_text(shim);binary.chmod(0o755)
            script=Path(__file__).with_name('queue_new50_after_first24.ps1')
            # Dot-source the real BOM-marked script so only the CIM provider is
            # synthetic; actual path invocation/mutex/prepare/publish flow runs.
            loader=root/'loader.ps1'
            loader.write_text("function Get-CimInstance {return @()}\n. '"+str(script)+"' -Root '"+str(root)+"' -Queue '"+str(queue)+"' -Prepare '"+str(root/'prepare helper.py')+"' -Publisher '"+str(root/'publisher helper.py')+"'\n")
            env=dict(os.environ,XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            result=subprocess.run([str(pwsh),'-NoLogo','-NoProfile','-File',str(loader)],input='\n',capture_output=True,text=True,env=env,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            rows=[json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(rows,[['-u',str(root/'prepare helper.py'),str(root),'--prepare-only'],['-u',str(root/'publisher helper.py'),str(root)]])
            self.assertTrue(script.read_bytes().startswith(b'\xef\xbb\xbf'))
    def test_actual_powershell_gate_and_private_pid_query(self):
        import tempfile
        pwsh=Path('/tmp/nov16-pwsh/pwsh')
        if not pwsh.is_file():self.skipTest('PowerShell unavailable')
        script=Path(__file__).with_name('queue_new50_after_first24.ps1').read_text();functions=script[script.index('function Read-Record'):script.index('$q=Read-Record $Queue')]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);logs=root/'logs';logs.mkdir();stage_sha='b'*64
            queue=dict(payload=dict(first24_stage_sha256=stage_sha))
            (root/'queue.json').write_text(json.dumps(queue))
            plan=dict(sha256='a'*64,payload=dict(stage_sha256=stage_sha,jobs=[dict(key='job-1'),dict(key='job-2')]))
            (logs/'frozen.json').write_text(json.dumps(plan));(logs/'nov16-new-first24-ai-disclosure-on-publication.json').write_text(json.dumps(dict(manifest='frozen.json',sha256='a'*64)))
            report=logs/'frozen-results.json';report.write_text(json.dumps(dict(attempts=[dict(key='job-1')])))
            prefix="$Root='"+str(root)+"'\n$Queue='"+str(root/'queue.json')+"'\n"
            fake="function Get-CimInstance {[pscustomobject]@{ProcessId=123;ExecutablePath=(Join-Path $Root '.venv/Scripts/python.exe');CommandLine='private-command-value'}}\n"
            suffix="[pscustomobject]@{finished=(First24-Finished (Read-Record $Queue));pids=@(Live-Publishers)} | ConvertTo-Json -Compress"
            file=root/'gate.ps1';file.write_text(prefix+fake+functions+suffix)
            env=dict(os.environ,XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
            def run():
                value=subprocess.run([str(pwsh),'-NoLogo','-NoProfile','-File',str(file)],capture_output=True,text=True,env=env,timeout=20)
                self.assertEqual(value.returncode,0,value.stderr);self.assertNotIn('private-command-value',value.stdout);return json.loads(value.stdout)
            self.assertEqual(run(),dict(finished=False,pids=[123]))
            report.write_text(json.dumps(dict(attempts=[dict(key='job-1'),dict(key='job-2')])))
            self.assertEqual(run(),dict(finished=True,pids=[123]))


if __name__=='__main__':unittest.main()
