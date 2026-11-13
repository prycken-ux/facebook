import unittest
from unittest.mock import patch

import distribute_video_materials as app
import fb_upload as upload
from test_distribute_video_materials import DistributionTests


class DistributionScopeTests(unittest.TestCase):
    def setUp(self):
        self.fx=DistributionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root;self.pool=self.fx.pool

    def test_existing24_includes_20_pages_and_restored_personals_without_fifty_reserved_accounts(self):
        self.fx.videos(44)
        (self.pool/'1.txt').write_text('文案跟随视频',encoding='utf-8')
        value=app.distribute(self.root,self.pool,day='2026-11-13',scope='existing24')
        rows=value['payload']['assignments']
        self.assertEqual(len(rows),44)
        self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(1,45)])
        pairs={(r['account'],r['target']) for r in rows}
        self.assertTrue({('fb16','personal'),('fb17','personal'),('fb18','personal'),('fb21','personal'),('fb24','personal')}<=pairs)
        self.assertEqual(sum(r['target'].startswith('page') and r['account'] in {'fb09','fb10'} for r in rows),20)
        self.assertTrue(all(int(r['account'][2:])<=24 for r in rows))
        self.assertFalse((self.root/'videos/fb25').exists())
        self.assertEqual((self.root/'videos/fb01/page01/inbox/1.txt').read_text(encoding='utf-8'),'文案跟随视频')
        for path,data in self.fx.preserved.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(len(list(self.pool.glob('*.mp4'))),44)

    def test_scope_and_source_are_remembered_and_repeat_does_not_refill_consumed_material(self):
        self.fx.videos(44)
        first=app.distribute(self.root,self.pool,day='2026-11-13',scope='existing24')
        firstrow=first['payload']['assignments'][0]
        target=app.safe_inbox(firstrow['account'],firstrow['target'])/firstrow['files'][-1]['destination_name']
        target.unlink()
        self.assertEqual(app.distribute(self.root,day='2026-11-13'),first)
        self.assertFalse(target.exists())
        self.assertEqual(upload.read_json(self.root/app.SETTINGS,{})['target_scope'],'existing24')

    def test_changing_same_day_scope_never_reassigns_existing_batch(self):
        self.fx.videos(94)
        app.distribute(self.root,self.pool,day='2026-11-13',scope='existing24')
        settings=(self.root/app.SETTINGS).read_bytes()
        with self.assertRaisesRegex(ValueError,'目标范围已变化'):
            app.distribute(self.root,self.pool,day='2026-11-13',scope='all')
        self.assertEqual((self.root/app.SETTINGS).read_bytes(),settings)
        self.assertFalse((self.root/'videos/fb25').exists())

    def test_insufficient_scope_material_aborts_before_any_copy_or_settings_change(self):
        self.fx.videos(43)
        with self.assertRaisesRegex(ValueError,'共有44个发布目标.*还差1条'):
            app.distribute(self.root,self.pool,day='2026-11-13',scope='existing24')
        self.assertFalse((self.root/'videos').exists())
        self.assertFalse((self.root/app.SETTINGS).exists())

    def test_unused_reservation_profile_does_not_block_original_targets(self):
        (self.root/'profiles/fb25').rmdir()
        self.assertEqual(len(app.targets(upload,scope='existing24')),44)
        with self.assertRaisesRegex(ValueError,'资料目录'):
            app.targets(upload,scope='all')

    def test_two_waves_use_the_next_fifty_without_reassigning_first_wave(self):
        self.fx.videos(94)
        first=app.distribute(self.root,self.pool,day='2026-11-13',scope='existing24')
        first_files={app.safe_inbox(r['account'],r['target'])/r['files'][-1]['destination_name']
                     for r in first['payload']['assignments']}
        before={p:p.read_bytes() for p in first_files}
        second=app.distribute(self.root,self.pool,day='2026-11-13',scope='reserved50')
        rows=second['payload']['assignments']
        self.assertEqual(len(rows),50)
        self.assertEqual([r['account'] for r in rows],[f'fb{n:02d}' for n in range(25,75)])
        self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(45,95)])
        for path,data in before.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(app.distribute(self.root,self.pool,day='2026-11-13',scope='reserved50'),second)
        self.fx.videos(94,start=95)
        tomorrow=app.distribute(self.root,self.pool,day='2026-11-14',scope='existing24')
        self.assertEqual(tomorrow['payload']['assignments'][0]['video_filename'],'95.mp4')

    def test_second_wave_waits_for_first_copy_to_finish(self):
        self.fx.videos(94)
        with patch.object(app,'copy_exact',side_effect=OSError('interrupted copy')):
            with self.assertRaises(OSError):app.distribute(self.root,self.pool,day='2026-11-13',scope='existing24')
        with self.assertRaisesRegex(ValueError,'未完成的素材分配'):
            app.distribute(self.root,self.pool,day='2026-11-13',scope='reserved50')
        self.assertFalse((self.root/'videos/fb25').exists())

    def test_all_scope_copies_all_targets_and_records_original_accounts_first_for_publication(self):
        self.fx.videos(94)
        value=app.distribute(self.root,self.pool,day='2026-11-13',scope='all')
        rows=value['payload']['assignments']
        self.assertEqual(len(rows),94)
        self.assertTrue(all(int(r['account'][2:])<=24 for r in rows[:44]))
        self.assertEqual([r['account'] for r in rows[44:]],[f'fb{n:02d}' for n in range(25,75)])
        self.assertEqual(value['payload']['publication_order'],['fb01-fb24-and-registered-pages','fb25-fb74'])
        self.assertEqual(upload.read_json(self.root/app.SETTINGS,{})['publication_order'],value['payload']['publication_order'])


if __name__=='__main__':unittest.main()
