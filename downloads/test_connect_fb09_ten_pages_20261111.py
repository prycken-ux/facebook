import contextlib
import copy
import io
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

import connect_fb09_ten_pages_20261111 as app
import scheduled_material_batch as batch


class ConnectFb09PagesTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        for module in (app.upload,app.accounts):stack.enter_context(patch.object(module,'ROOT',self.root))
        stack.enter_context(patch.object(app.upload,'CONFIG',self.root/'upload_config.json'))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.owner=dict(account='fb09',target='personal',type='personal',name='Original owner',url='https://www.facebook.com/profile.php?id=100009',workflow='personal_recording_v1',enabled=True,prepared_at='original-proof',ai_label=False)
        self.other=dict(account='fb10',target='page01',type='page',name='Existing page',url='https://www.facebook.com/profile.php?id=100010',enabled=True,prepared_at='keep-page-proof')
        self.config=dict(custom={'keep':True},targets=[self.owner,self.other]);app.upload.save_json(app.upload.CONFIG,self.config)
        self.before=app.upload.CONFIG.read_bytes()
        for relative,data in [('profiles/fb09/login-fixture',b'login'),('videos/fb09/personal/inbox/old.mp4',b'old-video'),('videos/fb09/page01/inbox/new.mp4',b'new-video'),('logs/publish_state.json',b'{"old":{"status":"needs_review"}}'),('logs/video_comments.json',b'{"old":{"status":"sent"}}'),('account_registry.json',b'{"keep":true}')]:
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.untouched={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p!=app.upload.CONFIG}

    def preserved(self):
        for path,data in self.untouched.items():self.assertEqual(path.read_bytes(),data)

    def test_register_all_ten_with_backup_and_future_batch_selection(self):
        updated=app.connect(self.root)
        self.assertEqual(updated['targets'][:2],self.config['targets']);self.assertEqual(updated['custom'],self.config['custom'])
        self.assertEqual(len(updated['targets']),12)
        for target,name,number in app.PAGES:
            row=next(x for x in updated['targets'] if (x['account'],x['target'])==('fb09',target))
            self.assertEqual((row['name'],row['url']),(name,'https://www.facebook.com/profile.php?id='+number))
            self.assertEqual(row['type'],'page');self.assertEqual(row['workflow'],'page_flow_configured')
            self.assertNotIn('prepared_at',row);self.assertFalse(row['enabled'])
            self.assertTrue(batch.eligible(row,True,date='2026-11-11'))
            for folder in ('inbox','completed','failed'):self.assertTrue((self.root/'videos/fb09'/target/folder).is_dir())
        backups=list((self.root/'backups').glob('*/upload_config.json'));self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),self.before)
        self.preserved()

    def test_repeat_preserves_existing_page_flags_and_no_extra_backup(self):
        updated=app.connect(self.root);updated['targets'][-1].update(enabled=True,prepared_at='existing-real-proof')
        app.upload.save_json(app.upload.CONFIG,updated);before=app.upload.CONFIG.read_bytes();backups=list((self.root/'backups').iterdir())
        app.connect(self.root)
        self.assertEqual(app.upload.CONFIG.read_bytes(),before);self.assertEqual(list((self.root/'backups').iterdir()),backups);self.preserved()

    def test_last_slot_collision_blocks_all_new_config_and_folders(self):
        changed=copy.deepcopy(self.config);changed['targets'].append(dict(self.other,account='fb09',target='page10'))
        app.upload.save_json(app.upload.CONFIG,changed);before=app.upload.CONFIG.read_bytes()
        with self.assertRaisesRegex(ValueError,'未覆盖'):app.connect(self.root)
        self.assertEqual(app.upload.CONFIG.read_bytes(),before);self.assertFalse((self.root/'videos/fb09/page02').exists());self.preserved()

    def test_duplicate_page_id_on_another_account_blocks_before_mutation(self):
        changed=copy.deepcopy(self.config);changed['targets'][1]['url']='https://www.facebook.com/profile.php?id='+app.PAGES[-1][2]
        app.upload.save_json(app.upload.CONFIG,changed);before=app.upload.CONFIG.read_bytes()
        with self.assertRaisesRegex(ValueError,'重复添加'):app.connect(self.root)
        self.assertEqual(app.upload.CONFIG.read_bytes(),before);self.assertFalse((self.root/'videos/fb09/page02').exists());self.preserved()

    def test_active_lock_is_preserved_and_no_registration_is_performed(self):
        lock=self.root/'logs/upload.lock';lock.write_bytes(b'active-worker')
        with self.assertRaises(RuntimeError):app.connect(self.root)
        self.assertEqual(lock.read_bytes(),b'active-worker');self.assertEqual(app.upload.CONFIG.read_bytes(),self.before);self.preserved()

    def test_failed_save_restores_exact_original_config(self):
        def failure(path,value):path.write_bytes(b'partial');raise OSError('write failed')
        with patch.object(app.upload,'save_json',side_effect=failure):
            with self.assertRaises(OSError):app.connect(self.root)
        self.assertEqual(app.upload.CONFIG.read_bytes(),self.before);self.preserved()

    def test_main_passes_explicit_root_and_does_not_start_a_publication(self):
        with patch.object(app.sys,'platform','win32'),patch.object(app.sys,'argv',['verified-entry',str(self.root)]),patch.object(app,'connect') as connect:
            self.assertEqual(app.main(),0)
        connect.assert_called_once_with(self.root)

    def test_normal_batch_freezes_new_material_for_all_ten_page_targets(self):
        app.connect(self.root)
        for target,_,_ in app.PAGES:
            video=self.root/'videos/fb09'/target/'inbox/nov11.mp4'
            video.write_bytes(('new material '+target).encode());video.with_suffix('.txt').write_text('Original caption',encoding='utf-8')
        path,value=batch.freeze('2026-11-11','17:00',True,'Approved comment',datetime(2026,11,11,8,tzinfo=timezone.utc),report_format='text')
        jobs=[j for j in value['payload']['jobs'] if j['account']=='fb09' and j['target'].startswith('page')]
        self.assertEqual({j['target'] for j in jobs},{p[0] for p in app.PAGES})
        self.assertEqual(len(jobs),10)
        for job in jobs:self.assertEqual(batch.validate_job(job,date='2026-11-11')['target'],job['target'])
        self.preserved()


if __name__=='__main__':unittest.main()
