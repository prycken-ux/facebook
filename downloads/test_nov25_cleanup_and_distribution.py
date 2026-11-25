import contextlib,copy,hashlib,io,os,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import distribute_eligible60_materials_20261125 as app
import distribute_eligible60_materials_20261124 as previous
import clean_pre_nov25_materials_20261125 as cleanup
import test_distribute_video_materials as fixture

class ProtectCleanAllocateTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.DistributionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        self.output=io.StringIO();self.enterContext(contextlib.redirect_stdout(self.output))
        self.enterContext(patch.object(app.recovery,'recover_locks'));self.enterContext(patch.object(cleanup.recovery,'recover_locks'));self.enterContext(patch.object(previous.recovery,'recover_locks'))
        self.clock=self.enterContext(patch.object(app.stage,'datetime',wraps=datetime));self.clock.now.return_value=datetime(2026,11,24,5,tzinfo=timezone.utc)
        old_clock=self.enterContext(patch.object(previous.stage,'datetime',wraps=datetime));old_clock.now.return_value=datetime(2026,11,24,5,tzinfo=timezone.utc)
        self.old=self.root/'old-pool';self.old.mkdir()
        for n in range(1,61):(self.old/f'{n}.mp4').write_bytes(('old Nov24 material '+str(n)).encode())
        with patch.object(previous,'inspect_workers',return_value=[]):previous.execute(self.root,self.old)
        pointer=app.stage.upload.read_json(self.root/previous.POINTER,{})
        self.old_manifest=self.root/pointer['manifest'];old=app.stage.upload.read_json(self.old_manifest,{})
        row=old['payload']['distribution']['payload']['assignments'][0]
        self.old_video=app.stage.materials.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name']
        self.old_staged=self.old_manifest.parent/'videos'/row['account']/row['target']/'inbox'/row['files'][-1]['name']
        entry=next(e for e in app.stage.upload.read_json(self.root/'upload_config.json',{})['targets'] if (e.get('account'),e.get('target'))==(row['account'],row['target']))
        self.old_key=app.stage.upload.job_key(entry,self.old_video);state=app.stage.upload.read_json(self.root/'logs/publish_state.json',{})
        state[self.old_key]=dict(account=row['account'],target=row['target'],url=entry['url'],video=str(self.old_video),status='needs_review',post_intent_at='2026-11-24T11:00:00Z',comment_status='lookup_pending')
        app.stage.upload.save_json(self.root/'logs/publish_state.json',state)
        self.clock.now.return_value=datetime(2026,11,25,5,tzinfo=timezone.utc)
        self.pool=self.root/'today-pool';self.pool.mkdir()
        for n in range(1,61):(self.pool/f'2026-11-01_camera_{n}.mp4').write_bytes(('fresh Nov25 '+str(n)).encode())
        self.source_before={p:p.read_bytes() for p in self.pool.iterdir()}
        self.credentials=self.root/'profiles/fb01/Default/Login Data';self.credentials.parent.mkdir(parents=True,exist_ok=True);self.credentials.write_bytes(b'keep user browser data')
        self.program=self.root/'fixture-code.py';self.program.write_text('keep original software')
        self.comments=self.root/'logs/video_comments.json';self.comments.write_text('{"receipt":"keep"}')
        self.before_config={p:p.read_bytes() for p in [self.root/'upload_config.json',self.root/'account_registry.json',self.root/'additional_personal_accounts.json']}
        self.enterContext(patch.object(app.stage.upload,'run_entry',side_effect=AssertionError('Allocation must never publish video')))
    def run(self,result=None):return super().run(result)
    def execute(self,source=None):
        with patch.object(app,'inspect_workers',return_value=[]):return app.execute(self.root,self.pool if source is None else source)
    def selected(self):
        pointer=app.stage.upload.read_json(self.root/app.POINTER,{});return pointer,app.stage.upload.read_json(self.root/pointer['manifest'],{})
    def test_cleans24_and_copies25_exact60_with_all_pauses_and_no_publication(self):
        self.assertEqual(self.execute(),0);pointer,plan=self.selected();self.assertIs(pointer['complete'],True)
        assignments=plan['payload']['distribution']['payload']['assignments'];self.assertEqual(len(assignments),60);self.assertEqual({(r['account'],r['target']) for r in assignments},app.EXPECTED)
        self.assertFalse({r['account'] for r in assignments}&app.UNAVAILABLE);self.assertEqual(len(app.UNAVAILABLE),34);self.assertTrue({('fb37','personal'),('fb63','personal')}<=app.EXPECTED)
        for row in assignments:
            info=row['files'][-1];self.assertTrue(info['destination_name'].startswith('20261125-'));video=app.stage.materials.safe_inbox(row['account'],row['target'])/info['destination_name'];self.assertEqual(video.read_bytes(),(self.pool/info['name']).read_bytes())
        self.assertFalse(self.old_video.exists());self.assertFalse(self.old_staged.exists());self.assertEqual(list(self.old.glob('*.mp4')),[])
        state=app.stage.upload.read_json(self.root/'logs/publish_state.json',{})
        self.assertEqual(state[self.old_key]['status'],'archived');self.assertEqual(state[self.old_key]['publication_status_before_user_archive'],'needs_review');self.assertEqual(state[self.old_key]['post_intent_at'],'2026-11-24T11:00:00Z')
        for p,b in self.source_before.items():self.assertEqual(p.read_bytes(),b)
        for p,b in self.before_config.items():self.assertEqual(p.read_bytes(),b)
        self.assertEqual(self.credentials.read_bytes(),b'keep user browser data');self.assertEqual(self.program.read_text(),'keep original software');self.assertEqual(self.comments.read_text(),'{"receipt":"keep"}');self.assertTrue(self.old_manifest.exists())
    def test_reused_same_source_folder_preserves_new_video_and_unassigned_extra(self):
        for n in range(1,62):(self.old/f'new-{n}.mp4').write_bytes(('Nov25 same source new '+str(n)).encode())
        self.assertEqual(self.execute(self.old),0)
        self.assertFalse((self.old/'1.mp4').exists());self.assertEqual(len(list(self.old.glob('new-*.mp4'))),61)
        _,plan=self.selected();self.assertEqual(plan['payload']['distribution']['payload']['leftover_count'],1)
    def test_reused_same_filenames_with_new_bytes_are_never_deleted(self):
        originals={}
        for n in range(1,61):
            file=self.old/f'{n}.mp4';file.write_bytes(('Nov25 replacing same source filename '+str(n)).encode());originals[file]=file.read_bytes()
        self.assertEqual(self.execute(self.old),0)
        self.assertFalse(self.old_video.exists());self.assertFalse(self.old_staged.exists())
        for file,data in originals.items():self.assertEqual(file.read_bytes(),data)
        _,plan=self.selected();self.assertEqual(len(plan['payload']['distribution']['payload']['assignments']),60)
    def test_insufficient_today_material_never_deletes_old_files(self):
        next(self.pool.glob('*.mp4')).unlink()
        with self.assertRaisesRegex(ValueError,'素材不足'):self.execute()
        self.assertTrue(self.old_video.exists());self.assertTrue(self.old_staged.exists());self.assertTrue((self.old/'1.mp4').exists());self.assertEqual(app.stage.upload.read_json(self.root/'logs/publish_state.json',{})[self.old_key]['status'],'needs_review')
    def test_corrupt_new_staged_copy_stops_before_old_deletion(self):
        native=app.stage.prepare
        def corrupt(*args,**kwargs):
            path,value=native(*args,**kwargs);row=value['payload']['distribution']['payload']['assignments'][0];(path.parent/'videos'/row['account']/row['target']/'inbox'/row['files'][-1]['name']).write_bytes(b'corruption');return path,value
        with patch.object(app.stage,'prepare',side_effect=corrupt),self.assertRaisesRegex(ValueError,'暂存副本'):self.execute()
        self.assertTrue(self.old_video.exists());self.assertTrue((self.old/'1.mp4').exists())
    def test_busy_old_worker_only_prepares_new_staging_until_it_exits(self):
        count=[0]
        def workers(root):count[0]+=1;return [dict(pid=123)] if count[0]==1 else []
        def wait(seconds):self.assertTrue(self.old_video.exists());self.assertTrue((self.old/'1.mp4').exists());self.assertEqual(seconds,15)
        with patch.object(app,'inspect_workers',side_effect=workers),patch.object(app.time,'sleep',side_effect=wait):self.assertEqual(app.execute(self.root,self.pool),0)
    def test_rerun_reuses_same_plan_and_preserves_current25_state(self):
        self.execute();pointer,plan=self.selected();path=self.root/pointer['manifest'];before=path.read_bytes()
        row=plan['payload']['distribution']['payload']['assignments'][0];video=app.stage.materials.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name'];key=app.stage.upload.job_key(dict(url=row['url']),video)
        state=app.stage.upload.read_json(self.root/'logs/publish_state.json',{});state[key]=dict(account=row['account'],target=row['target'],url=row['url'],video=str(video),status='needs_review',post_intent_at='today',created='2026-11-25T01:00:00Z');app.stage.upload.save_json(self.root/'logs/publish_state.json',state)
        with patch.object(app.stage.materials,'choose_source',side_effect=AssertionError('Do not choose again')),patch.object(app,'inspect_workers',return_value=[]):self.assertEqual(app.execute(self.root),0)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(app.stage.upload.read_json(self.root/'logs/publish_state.json',{})[key],state[key]);self.assertTrue(video.exists())
    def test_old_dated_prefix_in_paused_folder_is_deleted_but_no_new_allocation(self):
        old=self.root/'videos/fb23/personal/inbox/20261124-12345678-eligible60-old.mp4';old.parent.mkdir(parents=True,exist_ok=True);old.write_bytes(b'old paused clip')
        self.execute();self.assertFalse(old.exists());self.assertFalse(list(old.parent.glob('20261125-*.mp4')))
    def test_future_scheduled_video_and_unknown_raw_video_are_retained(self):
        future=self.root/'videos/fb04/personal/scheduled/2026-11-26/inbox/camera.mp4';future.parent.mkdir(parents=True,exist_ok=True);future.write_bytes(b'future scheduled')
        raw=self.root/'videos/fb04/personal/inbox/2026-11-01_camera.mp4';raw.write_bytes(b'unknown possibly fresh')
        self.execute();self.assertTrue(future.exists());self.assertTrue(raw.exists())

if __name__=='__main__':unittest.main()
