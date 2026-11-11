import unittest
from unittest.mock import patch

import publish_existing_20261111 as app
import test_publish_today_20261111 as fixtures


class ExistingTargetsFirstTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.Nov11DirectTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.base=app.base;self.root=self.fx.f.root

    def test_defers_new_targets_and_missing_restored_mapping_without_blocking_others(self):
        config=self.base.upload.read_json(self.base.upload.CONFIG,{})
        config['targets']=[e for e in config['targets'] if e['account']!='fb16']
        self.base.upload.save_json(self.base.upload.CONFIG,config);before=self.base.upload.CONFIG.read_bytes()
        # A pending fb24 must not block the original targets in this scope.
        registry=self.base.upload.read_json(self.root/'additional_personal_accounts.json',{});registry['slots']['fb24']['publishing_ready']=False;self.base.upload.save_json(self.root/'additional_personal_accounts.json',registry)
        with patch.object(self.base.workflow,'run',return_value=3) as run:self.assertEqual(app.execute(True),3)
        value=self.base.upload.read_json(run.call_args.args[0],{});jobs=value['payload']['jobs']
        self.assertEqual(len(jobs),32)
        self.assertFalse({(j['account'],j['target']) for j in jobs}&app.DEFERRED_NEW)
        self.assertIn(('fb09','personal'),{(j['account'],j['target']) for j in jobs})
        report=self.base.upload.read_json(self.root/'logs/deferred-targets-2026-11-11.json',{})
        self.assertIn(('fb16','未登记'),{(r['account'],r['target']) for r in report['targets']})
        self.assertEqual(self.base.upload.CONFIG.read_bytes(),before)
        self.assertEqual(self.base.upload.read_json(self.fx.f.state_path,{}),self.fx.history)
        self.assertEqual(self.fx.old.with_suffix('.txt').read_bytes(),self.fx.old_caption)
        for row in self.fx.entries:
            if (row['account'],row['target']) in app.DEFERRED_NEW:
                self.assertEqual((self.base.upload.inbox_for(row)/'nov11.txt').read_text(),'Replace generic caption')

    def test_restored_page_target_is_used_as_page_instead_of_requiring_personal(self):
        config=self.base.upload.read_json(self.base.upload.CONFIG,{})
        row=next(e for e in config['targets'] if e['account']=='fb16');row.update(target='page01',type='page',workflow='page_flow_configured')
        video=self.base.upload.inbox_for(row)/'nov11-page.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'restored page material')
        self.base.upload.save_json(self.base.upload.CONFIG,config)
        with patch.object(self.base.workflow,'run',return_value=3) as run:app.execute(True)
        value=self.base.upload.read_json(run.call_args.args[0],{})
        self.assertIn(('fb16','page01'),{(j['account'],j['target']) for j in value['payload']['jobs']})
        self.assertNotIn(('fb16','personal'),{(j['account'],j['target']) for j in value['payload']['jobs']})

    def test_resumes_same_source_and_keeps_new_target_material_untouched(self):
        with patch.object(self.base.workflow,'run',return_value=3) as run:
            app.execute(True);path=run.call_args.args[0];before=path.read_bytes();app.execute(True)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(run.call_args.args[0],path);self.fx.preserved()

    def test_prior_expanded_scope_is_not_replaced_or_reuploaded(self):
        with patch.object(self.base.workflow,'run',return_value=3) as run:self.base.execute(True)
        path=run.call_args.args[0];before=path.read_bytes()
        with patch.object(self.base.workflow,'run') as run:
            with self.assertRaisesRegex(ValueError,'不同范围'):app.execute(True)
        run.assert_not_called();self.assertEqual(path.read_bytes(),before)

    def test_entry_uses_confirmed_real_flag_and_correct_root(self):
        with patch.object(app.sys,'platform','win32'),patch.object(self.base,'recover_locks') as recover,patch.object(app,'execute',return_value=3) as execute:
            self.assertEqual(app.start(self.root,True),3)
        recover.assert_called_once_with(self.root);execute.assert_called_once_with(True)


if __name__=='__main__':unittest.main()
