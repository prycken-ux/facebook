import copy,json,subprocess,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import distribute_first24_materials_20261116 as app
from test_stage_next_materials_20261114_v1 import ParallelStagingTests


class First24AutoImportTests(unittest.TestCase):
    def setUp(self):
        self.fx=ParallelStagingTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root;self.pool=self.fx.pool
        clock=self.enterContext(patch.object(app.stage,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,16,6,tzinfo=timezone.utc)
        self.enterContext(patch.object(app.recovery,'recover_locks'))
        self.before={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
        self.state=(self.root/'logs/publish_state.json').read_bytes()
    def run_copy(self):
        with patch.object(app,'inspect_workers',return_value=[]):return app.execute(self.root,self.pool)
    def selected(self):
        pointer=app.stage.upload.read_json(self.root/'material-staging/first24-pending-import.json',{})
        path=self.root/pointer['manifest'];return path,app.stage.upload.read_json(path,{})
    def test_all44_including_paused17_and_exact20_additional_pages_preserve_old_and_new50(self):
        self.assertEqual(self.run_copy(),0);path,value=self.selected();rows=value['payload']['distribution']['payload']['assignments']
        self.assertEqual(len(rows),44);self.assertEqual({(r['account'],r['target']) for r in rows},app.EXPECTED)
        self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(95,139)])
        self.assertEqual(sum(r['account'] in {'fb09','fb10'} and r['target'].startswith('page') for r in rows),20)
        for row in rows:
            dest=app.stage.materials.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name']
            self.assertEqual(dest.read_bytes(),(self.pool/row['video_filename']).read_bytes())
        for file,data in self.before.items():self.assertEqual(file.read_bytes(),data)
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),self.state)
        before={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()};self.run_copy()
        self.assertEqual(before,{p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()})
        self.assertTrue((path.parent/'分配完成清单.txt').exists())
    def test_busy_publisher_prepares_without_touching_live_queue_then_imports_automatically(self):
        locks=[self.root/'logs'/n for n in ('batch.lock','upload.lock')]
        for path in locks:path.write_bytes(b'publisher-pid')
        def sleep(seconds):
            self.assertEqual(seconds,15)
            self.assertEqual(self.before,{p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()})
            for p in locks:self.assertEqual(p.read_bytes(),b'publisher-pid');p.unlink()
        with patch.object(app,'inspect_workers',side_effect=[[dict(pid=123,name='python.exe')],[],[]]),patch.object(app.time,'sleep',side_effect=sleep) as wait:
            self.assertEqual(app.execute(self.root,self.pool),0)
        wait.assert_called_once();self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),self.state)
    def test_interrupted_wait_resumes_saved_mapping_without_reopening_source_picker(self):
        with patch.object(app,'inspect_workers',return_value=[dict(pid=123,name='python.exe')]),patch.object(app.time,'sleep',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):app.execute(self.root,self.pool)
        path,value=self.selected();original=path.read_bytes()
        with patch.object(app,'inspect_workers',return_value=[]),patch.object(app.stage.materials,'choose_source',side_effect=AssertionError('No extra folder prompt')):
            self.assertEqual(app.execute(self.root),0)
        self.assertEqual(path.read_bytes(),original)
    def test_footage_already_in_unimported14_stage_is_not_reassigned(self):
        import stage_next_materials_20261114_v1 as old
        old_path,_=old.prepare(self.root,self.pool,scope='existing24');old_bytes=old_path.read_bytes()
        self.run_copy();_,value=self.selected();rows=value['payload']['distribution']['payload']['assignments']
        self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(139,183)])
        self.assertEqual(old_path.read_bytes(),old_bytes)
    def test_insufficient_pool_keeps_every_live_file(self):
        for n in range(110,189):(self.pool/f'{n}.mp4').unlink()
        with self.assertRaisesRegex(ValueError,'素材不足'):self.run_copy()
        self.assertEqual(self.before,{p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()})
    def test_low_disk_space_keeps_originals_and_does_not_begin_copying(self):
        usage=type('Disk',(),dict(free=1024))()
        with patch.object(app.stage.shutil,'disk_usage',return_value=usage):
            with self.assertRaisesRegex(ValueError,'磁盘可用空间不足'):self.run_copy()
        self.assertEqual(self.before,{p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()})
        self.assertFalse(list((self.root/'material-staging').glob('*/*/videos/**/*.mp4')))
    def test_tampered_staged_media_is_rejected_before_any_live_copy(self):
        def idle(root):
            path,_=self.selected();next((path.parent/'videos').rglob('*.mp4')).write_bytes(b'changed')
            return []
        with patch.object(app,'inspect_workers',side_effect=idle):
            with self.assertRaisesRegex(ValueError,'暂存原素材变化'):app.execute(self.root,self.pool)
        self.assertEqual(self.before,{p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()})
    def test_invalid_scope_and_second_dispatch_do_not_enter_import(self):
        with self.assertRaises(ValueError):app.check_scope([dict(account='fb25',target='personal')])
        folder=self.root/'material-staging/first24-dispatch';folder.mkdir(parents=True)
        with app.stage.staging_lock(folder):
            with self.assertRaisesRegex(RuntimeError,'仍在运行'):app.execute(self.root,self.pool)


class MaterialWorkerChainTests(unittest.TestCase):
    def test_four_layer_venv_chain_is_exempt_but_old_publisher_is_not(self):
        from test_nov16_venv_process_chain import VenvProcessChainTests
        fixture=VenvProcessChainTests();fixture.setUp()
        body=fixture.body.replace('start_finish_first24_nov16','start_distribute_first24_materials_20261116').replace('verified-nov16-first24-and-nov14-stage','verified-first24-material-distribution')
        rows=copy.deepcopy(fixture.rows)
        for row in rows[2:]:row['command']=subprocess.list2cmdline([fixture.exe,'-u','-c',body,fixture.root])
        rows.append(fixture.row(96,1,['-u',fixture.root+r'\publish_unplanned_fortysix_nov14.py',fixture.root]))
        workers,allowed=app.workers.classify_workers(rows,fixture.root,100,fixture.runner)
        self.assertEqual(allowed,[97,98,99,100]);self.assertEqual([r['pid'] for r in workers],[96])


if __name__=='__main__':unittest.main()
