import copy,subprocess,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import distribute_eligible78_materials_20261117 as app
from test_distribute_video_materials import DistributionTests

class Eligible78AllocationTests(unittest.TestCase):
    def setUp(self):
        self.fx=DistributionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root;self.pool=self.fx.pool
        self.fx.videos(count=79)
        self.clock=self.enterContext(patch.object(app.stage,'datetime',wraps=datetime));self.clock.now.return_value=datetime(2026,11,17,5,tzinfo=timezone.utc)
        self.enterContext(patch.object(app.recovery,'recover_locks'))
        for account in app.stage.ALLOCATION_SKIP:
            path=self.root/'videos'/account/'personal/inbox';path.mkdir(parents=True,exist_ok=True)
            (path/'old.mp4').write_bytes(('old video '+account).encode())
        (self.root/'videos/fb23/personal/inbox/manual.mp4').write_bytes((self.pool/'40.mp4').read_bytes())
        (self.pool/'1.txt').write_text('caption');(self.pool/'1.comment.txt').write_text('comment')
        self.before=self.snapshot();self.state=(self.root/'logs/publish_state.json').read_bytes()
        self.original={p:p.read_bytes() for p in (self.root/'upload_config.json',self.root/'account_registry.json',self.root/'additional_personal_accounts.json')}
    def snapshot(self):return {p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
    def run_copy(self,source=True):
        with patch.object(app,'inspect_workers',return_value=[]):return app.execute(self.root,self.pool if source else None)
    def selected(self):
        pointer=app.stage.upload.read_json(self.root/'material-staging/eligible78-pending-import.json',{})
        path=self.root/pointer['manifest'];return path,app.stage.upload.read_json(path,{})
    def test_exact78_skip15_and_manual23_natural_order_sources_text_old_state_unchanged(self):
        self.assertEqual(self.run_copy(),0);path,value=self.selected();rows=value['payload']['distribution']['payload']['assignments']
        self.assertEqual(len(rows),78);self.assertEqual({(r['account'],r['target']) for r in rows},app.EXPECTED)
        self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(1,80) if n!=40])
        self.assertEqual(len({r['account'] for r in rows}),58)
        self.assertFalse({r['account'] for r in rows}&app.stage.ALLOCATION_SKIP)
        for row in rows:
            for info in row['files']:
                dest=app.stage.materials.safe_inbox(row['account'],row['target'])/info['destination_name']
                self.assertEqual(dest.read_bytes(),(self.pool/info['name']).read_bytes())
        for file,data in self.before.items():self.assertEqual(file.read_bytes(),data)
        for file,data in self.original.items():self.assertEqual(file.read_bytes(),data)
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),self.state)
        self.assertEqual(len(list(self.pool.glob('*.mp4'))),79)
        self.assertTrue((path.parent/'分配完成清单.txt').exists())
    def test_extra_video_is_left_in_source_without_an_extra_target(self):
        (self.pool/'80.mp4').write_bytes(b'extra source video')
        self.run_copy();_,v=self.selected();self.assertEqual(v['payload']['distribution']['payload']['leftover_count'],1)
        self.assertTrue((self.pool/'80.mp4').exists())
    def test_busy_wait_does_not_touch_active_files_or_state_then_imports(self):
        def wait(seconds):
            self.assertEqual(seconds,15);self.assertEqual(self.snapshot(),self.before)
            self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),self.state)
        with patch.object(app,'inspect_workers',side_effect=[[dict(pid=123)],[],[]]),patch.object(app.time,'sleep',side_effect=wait):
            self.assertEqual(app.execute(self.root,self.pool),0)
    def test_missing_available_target_refuses_without_copy(self):
        for name,key in [('upload_config.json','targets'),('account_registry.json','accounts')]:
            path=self.root/name;data=app.stage.upload.read_json(path,{})
            data[key]=[r for r in data[key] if r['account']!='fb24'];app.stage.upload.save_json(path,data)
        with self.assertRaisesRegex(ValueError,'78个原登记目标'):self.run_copy()
        self.assertEqual(self.snapshot(),self.before)
    def test_invalid_skipped_entries_and_missing_skipped_profiles_do_not_block(self):
        path=self.root/'upload_config.json';data=app.stage.upload.read_json(path,{})
        for row in data['targets']:
            if row['account']=='fb17':row['url']='invalid old owner'
        app.stage.upload.save_json(path,data)
        for account in app.UNAVAILABLE:
            path=self.root/'profiles'/account
            if path.exists():path.rmdir()
        self.assertEqual(self.run_copy(),0)
    def test_interrupted_staging_cross_midnight_resumes_original_mapping_without_picker(self):
        original=app.stage.materials.copy_exact
        def stop(*args):original(*args);raise OSError('interrupted copy')
        with patch.object(app.stage.materials,'copy_exact',side_effect=stop):
            with self.assertRaises(OSError):self.run_copy()
        path,value=self.selected();saved=path.read_bytes()
        self.clock.now.return_value=datetime(2026,11,18,5,tzinfo=timezone.utc)
        (self.pool/'0.mp4').write_bytes(b'new arrival must not shuffle')
        with patch.object(app.stage.materials,'choose_source',side_effect=AssertionError('must resume')):self.assertEqual(self.run_copy(source=False),0)
        self.assertEqual(path.read_bytes(),saved)
    def test_replay_does_not_refill_archived_or_change_later_settings(self):
        self.run_copy();_,value=self.selected();row=value['payload']['distribution']['payload']['assignments'][0]
        dest=app.stage.materials.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name'];dest.unlink()
        prefs=self.root/app.stage.materials.SETTINGS;app.stage.upload.save_json(prefs,dict(source='later'))
        saved=prefs.read_bytes();self.run_copy(source=False)
        self.assertFalse(dest.exists());self.assertEqual(prefs.read_bytes(),saved)
    def test_insufficient_space_or_material_keeps_live_files(self):
        with patch.object(app.stage.shutil,'disk_usage',return_value=type('Disk',(),dict(free=1))()):
            with self.assertRaisesRegex(ValueError,'磁盘可用空间不足'):self.run_copy()
        self.assertEqual(self.snapshot(),self.before)
    def test_owner_change_before_import_refuses_all_copies(self):
        def change(root):
            for name,key in [('upload_config.json','targets'),('account_registry.json','accounts')]:
                path=self.root/name;value=app.stage.upload.read_json(path,{})
                for row in value[key]:
                    if row['account']=='fb01':row['url']='https://www.facebook.com/profile.php?id=999'
                app.stage.upload.save_json(path,value)
            return []
        with patch.object(app,'inspect_workers',side_effect=change):
            with self.assertRaisesRegex(ValueError,'身份变化'):app.execute(self.root,self.pool)
        self.assertEqual(self.snapshot(),self.before)
    def test_short_source_refuses_without_any_live_copy(self):
        (self.pool/'79.mp4').unlink()
        with self.assertRaisesRegex(ValueError,'素材不足'):self.run_copy()
        self.assertEqual(self.snapshot(),self.before)
    def test_four_layer_venv_chain_exempts_only_this_verified_start(self):
        from test_nov16_venv_process_chain import VenvProcessChainTests
        fixture=VenvProcessChainTests();fixture.setUp()
        body=fixture.body.replace('start_finish_first24_nov16','start_distribute_eligible78_materials_20261117').replace('verified-nov16-first24-and-nov14-stage','verified-eligible78-material-distribution')
        rows=copy.deepcopy(fixture.rows)
        for row in rows[2:]:row['command']=subprocess.list2cmdline([fixture.exe,'-u','-c',body,fixture.root])
        rows.append(fixture.row(96,1,['-u',fixture.root+r'\publish_unplanned_fortysix_nov14.py',fixture.root]))
        with patch.object(app.workers,'BOOTSTRAP',app.BOOTSTRAP):workers,allowed=app.workers.classify_workers(rows,fixture.root,100,fixture.runner)
        self.assertEqual(allowed,[97,98,99,100]);self.assertEqual([r['pid'] for r in workers],[96])
    def test_bootstrap_worker_scope_matches_new_entry_only(self):
        old=__import__('material_distribution_worker_check')
        body="import hashlib,ssl,sys,urllib.request;c=ssl.create_default_context();c.minimum_version=ssl.TLSVersion.TLSv1_2;b=urllib.request.urlopen('https://raw.githubusercontent.com/prycken-ux/facebook/"+'a'*40+"/downloads/start_distribute_eligible78_materials_20261117.py',context=c,timeout=30).read(131073);hashlib.sha256(b).hexdigest()=='"+'b'*64+"' or sys.exit('Checksum mismatch; stopped');exec(compile(b,'verified-eligible78-material-distribution','exec'))"
        self.assertTrue(app.BOOTSTRAP.fullmatch(body));self.assertFalse(old.BOOTSTRAP.fullmatch(body))

if __name__=='__main__':unittest.main()
