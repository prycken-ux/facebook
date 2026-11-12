import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import distribute_video_materials as app
import add_fb_accounts as legacy
import fb_upload as upload


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.pool=self.root/'总素材';self.pool.mkdir()
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        for mod in (app,legacy,upload):self.stack.enter_context(patch.object(mod,'ROOT',self.root))
        self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        entries=[]
        for n in range(1,25):
            personal=n not in {1,2,5,6,12,13}
            row=dict(account=f'fb{n:02d}',target='personal' if personal else 'page01',type='personal' if personal else 'page',
                     name='Target '+str(n),url='https://www.facebook.com/profile.php?id='+str(10000+n),enabled=False)
            if personal:row['workflow']='personal_recording_v1'
            entries.append(row)
        primary=copy.deepcopy(entries)
        for account in ('fb09','fb10'):
            for n in range(1,11):
                entries.append(dict(account=account,target=f'page{n:02d}',type='page',name=account+' Page '+str(n),
                                    url='https://www.facebook.com/profile.php?id='+str(20000+int(account[2:])*100+n)))
        slots={f'fb{n:02d}':dict(type='personal',state='pending',batch_id='fifty') for n in range(25,75)}
        for account in slots:(self.root/'profiles'/account).mkdir(parents=True)
        upload.save_json(upload.CONFIG,dict(targets=entries))
        upload.save_json(self.root/'account_registry.json',dict(accounts=primary))
        upload.save_json(self.root/'additional_personal_accounts.json',dict(schema='additional-personal-logins-v1',slots=slots,batches={}))
        upload.save_json(self.root/'logs/publish_state.json',dict(older=dict(status='needs_review',account='fb16',target='personal')))
        self.preserved={p:p.read_bytes() for p in (upload.CONFIG,self.root/'account_registry.json',self.root/'additional_personal_accounts.json',self.root/'logs/publish_state.json')}

    def videos(self,count=94,start=1):
        for n in range(start,start+count):(self.pool/f'{n}.mp4').write_bytes(('unique video '+str(n)).encode())

    def run_copy(self,day='2026-11-12'):
        return app.distribute(self.root,self.pool,day=day)

    def test_all_74_accounts_and_20_registered_pages_receive_one_in_natural_order_and_text_follows(self):
        self.videos()
        (self.pool/'1.txt').write_text('原文案',encoding='utf-8')
        (self.pool/'1.comment.txt').write_text('规定评论',encoding='utf-8')
        inbox=self.root/'videos/fb01/page01/inbox';inbox.mkdir(parents=True)
        old=inbox/'1.mp4';old.write_bytes(b'old unfinished video')
        result=self.run_copy()
        rows=result['payload']['assignments']
        self.assertEqual(len(rows),94)
        self.assertEqual([r['video_filename'] for r in rows],[f'{n}.mp4' for n in range(1,95)])
        self.assertEqual(len({(r['account'],r['target']) for r in rows}),94)
        self.assertEqual(len([r for r in rows if r['pending']]),50)
        self.assertEqual(rows[0]['files'][-1]['destination_name'],'20261112-1-1.mp4')
        self.assertEqual(old.read_bytes(),b'old unfinished video')
        self.assertEqual((inbox/'20261112-1-1.txt').read_text(encoding='utf-8'),'原文案')
        self.assertEqual((inbox/'20261112-1-1.comment.txt').read_text(encoding='utf-8'),'规定评论')
        for row in rows:
            dst=app.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name']
            self.assertEqual(dst.read_bytes(),(self.pool/row['video_filename']).read_bytes())
        for path,data in self.preserved.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(len(list(self.pool.glob('*.mp4'))),94)

    def test_same_day_rerun_does_not_refill_archived_video_or_assign_new_pool_additions(self):
        self.videos();first=self.run_copy()
        row=first['payload']['assignments'][0]
        target=app.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name']
        target.unlink()
        self.videos(1,start=95)
        self.assertEqual(self.run_copy(),first)
        self.assertFalse(target.exists())
        self.assertFalse(list((self.root/'videos').rglob('95.mp4')))

    def test_next_day_skips_old_sources_even_when_the_originals_are_retained(self):
        self.videos();self.run_copy();self.videos(start=95)
        second=self.run_copy('2026-11-13')
        self.assertEqual(second['payload']['assignments'][0]['video_filename'],'95.mp4')
        self.assertEqual(second['payload']['assignments'][-1]['video_filename'],'188.mp4')

    def test_insufficient_materials_stop_before_any_destination_is_created(self):
        self.videos(93)
        with self.assertRaisesRegex(ValueError,'还差1条'):
            self.run_copy()
        self.assertFalse((self.root/'videos').exists())

    def test_interrupted_copy_resumes_exact_plan_and_does_not_reshuffle_when_pool_changes(self):
        self.videos()
        original=app.copy_exact
        def interrupt(source,destination,info):
            original(source,destination,info)
            raise OSError('interrupted after commit, before progress')
        with patch.object(app,'copy_exact',side_effect=interrupt):
            with self.assertRaises(OSError):self.run_copy()
        (self.pool/'0.mp4').write_bytes(b'new first file')
        result=self.run_copy()
        self.assertEqual(result['payload']['assignments'][0]['video_filename'],'1.mp4')
        self.assertFalse(list((self.root/'videos').rglob('0.mp4')))
        self.assertFalse(list((self.root/'videos').rglob('*.part')))

    def test_existing_publication_record_is_never_refilled_after_a_crash(self):
        self.videos()
        row=app.targets(upload)[0]
        key=upload.job_key(dict(url=row['url']),self.pool/'1.mp4')
        state=upload.read_json(self.root/'logs/publish_state.json',{})
        state[key]=dict(account=row['account'],target=row['target'],status='published')
        upload.save_json(self.root/'logs/publish_state.json',state)
        self.run_copy()
        self.assertFalse(app.safe_inbox(row['account'],row['target']).exists())
        self.assertEqual(upload.read_json(self.root/'logs/publish_state.json',{}),state)

    def test_active_upload_lock_and_changed_planned_source_preserve_all_originals(self):
        self.videos()
        lock=self.root/'logs/upload.lock';lock.write_text('active publisher')
        with self.assertRaises(RuntimeError):self.run_copy()
        self.assertEqual(lock.read_text(),'active publisher');lock.unlink()
        app.plan(upload,self.pool,'2026-11-12',app.targets(upload))
        (self.pool/'1.mp4').write_bytes(b'replaced source')
        with self.assertRaisesRegex(ValueError,'原视频发生变化'):self.run_copy()
        self.assertFalse((self.root/'videos').exists())

    def test_windows_folder_picker_uses_static_code_and_returns_unicode_path_as_data(self):
        result=type('Result',(),dict(stdout='E:\\中文 素材\\视频\r\n'))()
        with patch.object(app.sys,'platform','win32'),patch.object(app.subprocess,'run',return_value=result) as call:
            self.assertEqual(app.choose_source(),'E:\\中文 素材\\视频')
        self.assertIn('-STA',call.call_args.args[0])
        self.assertTrue(call.call_args.kwargs['check'])


if __name__=='__main__':unittest.main()
