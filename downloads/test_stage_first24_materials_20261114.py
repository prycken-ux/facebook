from unittest.mock import patch
from test_stage_next_materials_20261114_v1 import ParallelStagingTests
import stage_next_materials_20261114_v1 as app


class First24StagingTests(ParallelStagingTests):
    def stage44(self):
        # Same source as yesterday; only forty-four fresh clips remain today.
        for n in range(139,189):(self.pool/f'{n}.mp4').unlink(missing_ok=True)
        return app.prepare(self.root,self.pool,scope='existing24')
    def test_exact44_stage_and_import_leave_all_new50_live_folders_untouched(self):
        before={str(p.relative_to(self.root)):p.read_bytes() for n in range(25,75) for p in (self.root/f'videos/fb{n:02d}').rglob('*') if p.is_file()}
        locks=[]
        for name in ('batch.lock','upload.lock'):
            p=self.root/'logs'/name;p.write_bytes(b'active-publisher');locks.append(p)
        path,value=self.stage44();rows=value['payload']['distribution']['payload']['assignments']
        self.assertEqual(len(rows),44);self.assertTrue(all(int(r['account'][2:])<=24 for r in rows))
        self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(95,139)])
        self.assertEqual(sum(r['account']=='fb09' and r['target'].startswith('page') for r in rows),10)
        self.assertTrue(path.parent.name.endswith('-existing24'))
        self.assertFalse(list((path.parent/'videos').glob('fb2[5-9]')))
        for p in locks:self.assertEqual(p.read_bytes(),b'active-publisher');p.unlink()
        with patch.object(app,'active_workers',return_value=[]):app.import_stage(self.root,path)
        for key,data in before.items():self.assertEqual((self.root/key).read_bytes(),data)
        settings=app.upload.read_json(self.root/app.materials.SETTINGS,{})
        self.assertEqual(settings['target_scope'],'existing24')
        for row in rows:
            destination=app.materials.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name']
            self.assertEqual(destination.read_bytes(),(self.pool/row['video_filename']).read_bytes())
        state=(self.root/'logs/publish_state.json').read_bytes()
        with patch.object(app,'active_workers',return_value=[]):app.import_stage(self.root,path)
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),state)
    def test_previous_insufficient_all_attempt_does_not_block_first24_scope(self):
        for n in range(139,189):(self.pool/f'{n}.mp4').unlink()
        with self.assertRaisesRegex(ValueError,'94个目标'):app.prepare(self.root,self.pool)
        path,value=app.prepare(self.root,self.pool,scope='existing24')
        self.assertEqual(len(value['payload']['distribution']['payload']['assignments']),44)
        self.assertEqual(app.validate_stage(self.root,path)[1],value)
