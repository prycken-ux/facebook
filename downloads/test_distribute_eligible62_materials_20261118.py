import copy,hashlib,subprocess,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import distribute_eligible62_materials_20261118 as app
from test_distribute_video_materials import DistributionTests

class Eligible62AllocationTests(unittest.TestCase):
    def setUp(self):
        self.fx=DistributionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root;self.pool=self.fx.pool
        self.fx.videos(count=62);(self.pool/'1.txt').write_text('caption');(self.pool/'1.comment.txt').write_text('comment')
        self.clock=self.enterContext(patch.object(app.stage,'datetime',wraps=datetime));self.clock.now.return_value=datetime(2026,11,18,5,tzinfo=timezone.utc)
        self.enterContext(patch.object(app.recovery,'recover_locks'))
        for account in app.UNAVAILABLE:
            path=self.root/'videos'/account/'personal/inbox';path.mkdir(parents=True,exist_ok=True);(path/'old.mp4').write_bytes(('existing paused '+account).encode())
        self.before=self.snapshot();self.protected={p:p.read_bytes() for p in (self.root/'upload_config.json',self.root/'account_registry.json',self.root/'additional_personal_accounts.json',self.root/'logs/publish_state.json')}
    def snapshot(self):return {p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
    def run_copy(self,source=True):
        with patch.object(app,'inspect_workers',return_value=[]):return app.execute(self.root,self.pool if source else None)
    def selected(self):
        pointer=app.stage.upload.read_json(self.root/'material-staging/eligible62-pending-import.json',{})
        path=self.root/pointer['manifest'];return path,app.stage.upload.read_json(path,{})
    def test_exact62_skip32_with_public_pages_natural_order_sources_old_status_and_config_unchanged(self):
        self.assertEqual(self.run_copy(),0);path,value=self.selected();rows=value['payload']['distribution']['payload']['assignments']
        self.assertEqual(len(rows),62);self.assertEqual({(r['account'],r['target']) for r in rows},app.EXPECTED)
        self.assertEqual(len({r['account'] for r in rows}),42);self.assertFalse({r['account'] for r in rows}&app.UNAVAILABLE)
        self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(1,63)])
        self.assertEqual(sum(r['account'] in {'fb09','fb10'} and r['target'].startswith('page') for r in rows),20)
        for row in rows:
            for info in row['files']:
                target=app.stage.materials.safe_inbox(row['account'],row['target'])/info['destination_name'];self.assertEqual(target.read_bytes(),(self.pool/info['name']).read_bytes())
        for p,data in self.before.items():self.assertEqual(p.read_bytes(),data)
        for p,data in self.protected.items():self.assertEqual(p.read_bytes(),data)
        self.assertEqual(len(list(self.pool.glob('*.mp4'))),62);self.assertTrue((path.parent/'分配完成清单.txt').exists())
        settings=app.stage.upload.read_json(self.root/app.stage.materials.SETTINGS,{})
        self.assertEqual(settings['target_scope'],'eligible62');self.assertEqual(settings['excluded_accounts'],sorted(app.UNAVAILABLE))
    def test_existing78_pointer_and_plan_are_never_reused_or_changed(self):
        import stage_eligible78_materials_v4 as legacy
        pool=self.root/'old78';pool.mkdir()
        for n in range(1,79):(pool/f'{n}.mp4').write_bytes(('old78 unique '+str(n)).encode())
        old_path,old=legacy.prepare(self.root,pool,scope='eligible78')
        with patch.object(legacy,'active_workers',return_value=[]):legacy.import_stage(self.root,old_path)
        pointer=self.root/'material-staging/eligible78-pending-import.json';app.stage.upload.save_json(pointer,dict(manifest=str(old_path.relative_to(self.root)),sha256=old['sha256'],complete=True))
        before=(old_path.read_bytes(),pointer.read_bytes())
        with patch.object(app.stage.materials,'choose_source',return_value=str(self.pool)) as choose:
            self.assertEqual(self.run_copy(source=False),0)
        choose.assert_called_once();new_path,new=self.selected();self.assertNotEqual(new_path,old_path)
        self.assertEqual((old_path.read_bytes(),pointer.read_bytes()),before);self.assertEqual(new['payload']['source'],str(self.pool))
    def test_busy_publisher_only_stages_before_importing(self):
        def wait(seconds):
            self.assertEqual(seconds,15);self.assertEqual(self.snapshot(),self.before)
            for file,data in self.protected.items():self.assertEqual(file.read_bytes(),data)
        with patch.object(app,'inspect_workers',side_effect=[[dict(pid=100)],[],[]]),patch.object(app.time,'sleep',side_effect=wait):self.assertEqual(app.execute(self.root,self.pool),0)
    def test_interrupted_copy_cross_midnight_resumes_same_assignment_without_picker(self):
        original=app.stage.materials.copy_exact
        def stop(*args):original(*args);raise OSError('interrupted after commit')
        with patch.object(app.stage.materials,'copy_exact',side_effect=stop):
            with self.assertRaises(OSError):self.run_copy()
        path,_=self.selected();before=path.read_bytes();self.clock.now.return_value=datetime(2026,11,19,5,tzinfo=timezone.utc);(self.pool/'0.mp4').write_bytes(b'new arrival')
        with patch.object(app.stage.materials,'choose_source',side_effect=AssertionError('Do not reshuffle')):self.assertEqual(self.run_copy(source=False),0)
        self.assertEqual(path.read_bytes(),before)
    def test_short_source_and_low_space_leave_formal_video_folders_unchanged(self):
        (self.pool/'62.mp4').unlink()
        with self.assertRaisesRegex(ValueError,'素材不足'):self.run_copy()
        self.assertEqual(self.snapshot(),self.before);(self.pool/'62.mp4').write_bytes(b'new unique62')
        with patch.object(app.stage.shutil,'disk_usage',return_value=type('Disk',(),dict(free=1))()):
            with self.assertRaisesRegex(ValueError,'磁盘可用空间不足'):self.run_copy()
        self.assertEqual(self.snapshot(),self.before)
    def test_missing_paused_profiles_and_invalid_paused_urls_are_ignored(self):
        path=self.root/'upload_config.json';value=app.stage.upload.read_json(path,{})
        for row in value['targets']:
            if row['account'] in app.UNAVAILABLE:row['url']='not a profile URL'
        app.stage.upload.save_json(path,value)
        for account in app.UNAVAILABLE:
            folder=self.root/'profiles'/account
            if folder.exists():folder.rmdir()
        self.assertEqual(self.run_copy(),0)
    def test_completed_rerun_never_refills_archived_media_or_overrides_later_settings(self):
        self.run_copy();_,value=self.selected();row=value['payload']['distribution']['payload']['assignments'][0]
        video=app.stage.materials.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name'];video.unlink()
        settings=self.root/app.stage.materials.SETTINGS;app.stage.upload.save_json(settings,dict(source='later setting'));saved=settings.read_bytes()
        self.run_copy(source=False);self.assertFalse(video.exists());self.assertEqual(settings.read_bytes(),saved)
    def test_same_content_renamed_from_confirmed_archive_is_excluded(self):
        checksum=hashlib.sha256((self.pool/'1.mp4').read_bytes()).hexdigest()
        app.stage.upload.save_json(self.root/'logs/user_confirmed_archived_media.json',dict(schema='user-confirmed-archived-media-v1',rows={'old':dict(status='published',video_sha256=checksum)}))
        (self.pool/'63.mp4').write_bytes(b'new63');self.run_copy();_,value=self.selected()
        self.assertEqual([r['video_filename'] for r in value['payload']['distribution']['payload']['assignments']],[f'{n}.mp4' for n in range(2,64)])
    def test_pause_list_expanding_before_import_aborts_without_formal_copy(self):
        def update(root):
            payload=dict(schema='publication-account-exclusions-v1',excluded_accounts=sorted(app.UNAVAILABLE|{'fb40'}))
            app.stage.upload.save_json(root/'publication_account_exclusions.json',dict(payload=payload,sha256=app.stage.materials.digest(payload)));return []
        with patch.object(app,'inspect_workers',side_effect=update):
            with self.assertRaisesRegex(ValueError,'暂停名单已扩大'):app.execute(self.root,self.pool)
        self.assertEqual(self.snapshot(),self.before)
    def test_changed_target_owner_is_rejected_before_any_formal_copy(self):
        def change(root):
            for name,key in [('upload_config.json','targets'),('account_registry.json','accounts')]:
                path=root/name;value=app.stage.upload.read_json(path,{})
                for row in value[key]:
                    if row['account']=='fb01':row['url']='https://www.facebook.com/profile.php?id=999'
                app.stage.upload.save_json(path,value)
            return []
        with patch.object(app,'inspect_workers',side_effect=change):
            with self.assertRaisesRegex(ValueError,'身份变化'):app.execute(self.root,self.pool)
        self.assertEqual(self.snapshot(),self.before)
    def test_four_layer_venv_chain_exempts_this_launcher_only(self):
        from test_nov16_venv_process_chain import VenvProcessChainTests
        f=VenvProcessChainTests();f.setUp();rows=copy.deepcopy(f.rows)
        body=f.body.replace('start_finish_first24_nov16','start_distribute_eligible62_materials_20261118').replace('verified-nov16-first24-and-nov14-stage','verified-eligible62-material-distribution')
        for row in rows[2:]:row['command']=subprocess.list2cmdline([f.exe,'-u','-c',body,f.root])
        rows.append(f.row(96,1,['-u',f.root+r'\publish_eligible78_materials_20261117.py',f.root]))
        with patch.object(app.workers,'BOOTSTRAP',app.BOOTSTRAP):workers,allowed=app.workers.classify_workers(rows,f.root,100,f.runner)
        self.assertEqual(allowed,[97,98,99,100]);self.assertEqual([r['pid'] for r in workers],[96])

if __name__=='__main__':unittest.main()
