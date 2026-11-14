import copy,json,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import stage_next_materials_20261114_v1 as app
from test_distribute_video_materials import DistributionTests


class ParallelStagingTests(unittest.TestCase):
    def setUp(self):
        self.fx=DistributionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root;self.pool=self.fx.pool
        self.fx.videos();self.fx.run_copy(day='2026-11-13');self.fx.videos(start=95)
        (self.pool/'95.txt').write_text('today caption',encoding='utf-8')
        (self.pool/'95.comment.txt').write_text('today comment',encoding='utf-8')
        clock=self.enterContext(patch.object(app,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,14,5,tzinfo=timezone.utc)
        self.protected={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and not p.is_relative_to(self.pool)}
    def stage(self):return app.prepare(self.root,self.pool)
    def snapshot_live(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
    def test_prepare_during_live_upload_lock_writes_only_new_staging_tree_in_natural_order(self):
        for name in ('batch.lock','upload.lock'):(self.root/'logs'/name).write_bytes(b'1234')
        before=self.snapshot_live();settings=(self.root/app.materials.SETTINGS).read_bytes()
        path,value=self.stage();rows=value['payload']['distribution']['payload']['assignments']
        self.assertEqual(len(rows),94);self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(95,189)])
        self.assertEqual(self.snapshot_live(),before);self.assertEqual((self.root/app.materials.SETTINGS).read_bytes(),settings)
        for old,data in self.protected.items():self.assertEqual(old.read_bytes(),data)
        for name in ('batch.lock','upload.lock'):self.assertEqual((self.root/'logs'/name).read_bytes(),b'1234')
        first=rows[0];self.assertEqual((path.parent/'videos'/first['account']/first['target']/'inbox/95.txt').read_text(),'today caption')
        with patch.object(app,'active_workers',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'仍有上传任务'):app.import_stage(self.root,path)
    def test_import_refuses_live_worker_even_between_job_locks(self):
        path,_=self.stage();before=self.snapshot_live();settings=(self.root/app.materials.SETTINGS).read_bytes()
        with patch.object(app,'active_workers',return_value=[dict(pid=1234,name='python.exe')]):
            with self.assertRaisesRegex(RuntimeError,'任务进程运行'):app.import_stage(self.root,path)
        self.assertEqual(self.snapshot_live(),before);self.assertEqual((self.root/app.materials.SETTINGS).read_bytes(),settings)
        self.assertFalse(list((self.root/'logs/material-distribution').glob('*/2026-11-14.json')))
    def test_import_preserves_old_material_and_state_and_rerun_never_refills_or_resets_newer_preferences(self):
        path,value=self.stage();before=self.snapshot_live();state=(self.root/'logs/publish_state.json').read_bytes()
        with patch.object(app,'active_workers',return_value=[]):result=app.import_stage(self.root,path)
        rows=result['payload']['assignments'];self.assertEqual(len(rows),94)
        for key,data in before.items():self.assertEqual((self.root/key).read_bytes(),data)
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),state)
        for row in rows:
            destination=app.materials.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name']
            self.assertEqual(destination.read_bytes(),(self.pool/row['video_filename']).read_bytes())
        settings=self.root/app.materials.SETTINGS;app.upload.save_json(settings,dict(source='later-source-preference'))
        preserved=settings.read_bytes();first=rows[0];removed=app.materials.safe_inbox(first['account'],first['target'])/first['files'][-1]['destination_name'];removed.unlink()
        with patch.object(app,'active_workers',return_value=[]):app.import_stage(self.root,path)
        self.assertFalse(removed.exists());self.assertEqual(settings.read_bytes(),preserved)
    def test_changed_owner_or_staged_video_aborts_before_any_live_copy(self):
        path,value=self.stage();before=self.snapshot_live();row=value['payload']['distribution']['payload']['assignments'][0]
        target=path.parent/'videos'/row['account']/row['target']/'inbox'/row['files'][-1]['name'];original=target.read_bytes();target.write_bytes(b'tampered')
        with patch.object(app,'active_workers',return_value=[]):
            with self.assertRaisesRegex(ValueError,'暂存原素材变化'):app.import_stage(self.root,path)
        self.assertEqual(self.snapshot_live(),before);target.write_bytes(original)
        for name,key in [('upload_config.json','targets'),('account_registry.json','accounts')]:
            p=self.root/name;data=app.upload.read_json(p,{})
            next(r for r in data[key] if (r['account'],r['target'])==(row['account'],row['target']))['url']='https://www.facebook.com/profile.php?id=999999'
            app.upload.save_json(p,data)
        with patch.object(app,'active_workers',return_value=[]):
            with self.assertRaisesRegex(ValueError,'身份变化'):app.import_stage(self.root,path)
        self.assertEqual(self.snapshot_live(),before)
    def test_interrupted_staging_keeps_exact_assignments_after_source_pool_grows(self):
        real=app.materials.copy_exact
        def stop(*args):real(*args);raise OSError('fixture interruption after atomic commit')
        with patch.object(app.materials,'copy_exact',side_effect=stop):
            with self.assertRaises(OSError):self.stage()
        (self.pool/'0.mp4').write_bytes(b'new pool addition must not reshuffle')
        path,value=self.stage();rows=value['payload']['distribution']['payload']['assignments']
        self.assertEqual(rows[0]['video_filename'],'95.mp4');self.assertEqual(len(rows),94)
        self.assertFalse(list(path.parent.rglob('*.part')))
    def test_publisher_registration_can_complete_without_changing_target_allocation(self):
        path,_=self.stage();manifest=self.root/'additional_personal_accounts.json';extra=app.upload.read_json(manifest,{})
        slot=extra['slots']['fb25'];slot.update(state='registered',mapping=dict(account='fb25',target='personal',type='personal',url='https://www.facebook.com/profile.php?id=99025'))
        app.upload.save_json(manifest,extra)
        for name,key in [('upload_config.json','targets'),('account_registry.json','accounts')]:
            p=self.root/name;data=app.upload.read_json(p,{})
            data[key].append(dict(account='fb25',target='personal',type='personal',workflow='personal_recording_v1',name='new verified owner label',url='https://www.facebook.com/profile.php?id=99025'))
            app.upload.save_json(p,data)
        with patch.object(app,'active_workers',return_value=[]):app.import_stage(self.root,path)
        self.assertTrue((self.root/'videos/fb25/personal/inbox').is_dir())


class ProcessQueryTests(unittest.TestCase):
    def test_windows_probe_returns_only_pid_name_and_uses_no_shell_or_raw_command_output(self):
        result=type('Result',(),dict(returncode=0,stdout=b'[{"pid":1234,"name":"python.exe"}]'))()
        with patch.object(app.sys,'platform','win32'),patch.object(app.subprocess,'run',return_value=result) as call:
            self.assertEqual(app.active_workers(Path('/fixture/root')),[dict(pid=1234,name='python.exe')])
        data=json.loads(call.call_args.kwargs['input']);self.assertEqual(data['root'],'/fixture/root')
        self.assertNotIn('shell',call.call_args.kwargs);self.assertIn('creationflags',call.call_args.kwargs)
        self.assertIn('stage_next_materials_20261114_v1',app.WORKERS)


if __name__=='__main__':unittest.main()
