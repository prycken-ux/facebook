import contextlib,copy,ctypes,hashlib,io,json,os,sys,tempfile,types,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
import cleanup_confirmed_published_videos as app
import fb_upload as upload


class PublishedStorageCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        (self.root/'logs').mkdir();(self.root/'upload_config.json').write_text('{"targets":[]}')
        self.now=datetime(2026,11,16,6,tzinfo=timezone.utc);self.old=self.now-timedelta(days=3);self.state={}
        self.video,self.key=self.add_video('fb01','page01',b'old successful video')
    def save(self):
        self.state_path=self.root/'logs/publish_state.json';self.state_path.write_text(json.dumps(self.state),encoding='utf-8')
    def add_video(self,account,target,data,folder='completed',status='published',name='clip.mp4'):
        file=self.root/'videos'/account/target/folder/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
        os.utime(file,(self.old.timestamp(),)*2)
        url='https://www.facebook.com/profile.php?id=61595182473231';key=hashlib.sha256((upload.target_key(url)+'\0').encode()+data).hexdigest()
        self.state[key]=dict(account=account,target=target,url=url,video=str(file.parent.parent/'inbox'/name),archived_video=str(file),
                             status=status,published_at=self.old.isoformat(),created=self.old.isoformat(),confirmation_method='fresh_success_ui_and_composer_closed',comment_status='manual_required')
        self.save();return file,key
    def run_cleanup(self,apply=True):return app.cleanup(self.root,upload.target_key,apply=apply,now=self.now)
    def test_deletes_only_matching_old_success_archives_and_keeps_every_program_and_queue_byte(self):
        texts=[self.video.with_suffix('.txt'),self.video.with_suffix('.comment.txt')]
        for path in texts:path.write_text('approved caption or comment')
        protected=['.venv/Scripts/python.exe','profiles/fb01/Default/Cookies','browsers/chrome.exe','browser-profile/proxy.dat',
                   'backups/old-profile/important.mp4','material-staging/2026-11-14/new.mp4','videos/fb01/page01/inbox/today.mp4',
                   'fb_upload.py','account_registry.json','logs/video_comments.json','logs/upload.lock','logs/batch.lock']
        for name in protected:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'preserve exactly')
        original={p:p.read_bytes() for p in texts+[self.root/p for p in protected]+[self.state_path]}
        result=self.run_cleanup();self.assertEqual(len(result['deleted']),1);self.assertFalse(self.video.exists())
        for path,data in original.items():self.assertEqual(path.read_bytes(),data,str(path))
        report=[json.loads(line) for line in Path(result['report']).read_text().splitlines()]
        self.assertEqual([r['event'] for r in report],['plan','delete_intent','deleted','finished'])
        self.assertEqual(report[0]['original_success_records'][self.key],self.state[self.key])
        self.assertEqual(self.run_cleanup()['deleted'],[])
    def test_dry_run_never_deletes(self):
        result=self.run_cleanup(apply=False);self.assertEqual(len(result['planned']),1);self.assertTrue(self.video.exists())
        self.assertFalse((self.root/'logs/storage-cleanup').exists())
    def test_needs_review_failed_and_recent_successes_preserved(self):
        for status in ['needs_review','failed_before_post','posting','preparing','paused']:
            self.state[self.key]['status']=status;self.save();self.assertEqual(self.run_cleanup()['deleted'],[])
        self.state[self.key]['status']='published';self.state[self.key]['published_at']=self.now.isoformat();self.save()
        self.assertEqual(self.run_cleanup()['deleted'],[]);self.assertTrue(self.video.exists())
    def test_recent_file_unknown_proof_or_naive_timestamp_preserved(self):
        os.utime(self.video,(self.now.timestamp(),)*2);self.assertEqual(self.run_cleanup()['deleted'],[])
        os.utime(self.video,(self.old.timestamp(),)*2)
        for field,value in [('confirmation_method',''),('published_at','2026-11-12T06:00:00')]:
            before=copy.deepcopy(self.state);self.state[self.key][field]=value;self.save()
            self.assertEqual(self.run_cleanup()['deleted'],[]);self.state=before
        self.assertTrue(self.video.exists())
    def test_missing_success_timestamp_is_preserved_even_if_creation_is_old(self):
        self.state[self.key].pop('published_at');self.save()
        self.assertEqual(self.run_cleanup()['deleted'],[]);self.assertTrue(self.video.exists())
    def test_changed_media_and_other_owner_or_account_are_not_deleted(self):
        self.video.write_bytes(b'new content with same name');os.utime(self.video,(self.old.timestamp(),)*2)
        self.assertEqual(self.run_cleanup()['deleted'],[])
        self.video.write_bytes(b'old successful video');os.utime(self.video,(self.old.timestamp(),)*2)
        self.state[self.key]['url']='https://www.facebook.com/profile.php?id=10009999';self.save()
        self.assertEqual(self.run_cleanup()['deleted'],[])
    def test_pending_record_path_reference_blocks_cleanup(self):
        self.state['c'*64]=dict(status='needs_review',video=str(self.video),account='fb99',target='personal');self.save()
        self.assertEqual(self.run_cleanup()['deleted'],[]);self.assertTrue(self.video.exists())
    def test_material_source_folder_is_retained(self):
        (self.root/'material_distribution_settings.json').write_text(json.dumps(dict(source=str(self.video.parent))))
        self.assertEqual(self.run_cleanup()['deleted'],[])
        (self.root/'material_distribution_settings.json').unlink()
        path=self.root/'material-staging/2026-11-14/source/manifest.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(payload=dict(distribution=dict(payload=dict(source=str(self.video.parent)))))))
        self.assertEqual(self.run_cleanup()['deleted'],[])
    def test_symlink_hardlink_and_junction_style_paths_are_retained(self):
        outside=self.root/'outside.mp4';outside.write_bytes(b'outside')
        self.video.unlink();self.video.symlink_to(outside)
        self.assertEqual(self.run_cleanup()['deleted'],[]);self.assertEqual(outside.read_bytes(),b'outside')
        self.video.unlink();self.video.write_bytes(b'old successful video');os.utime(self.video,(self.old.timestamp(),)*2)
        os.link(self.video,self.video.with_name('hardlink.mp4'))
        self.assertEqual(self.run_cleanup()['deleted'],[])
    def test_state_change_after_hash_and_missing_original_proof_prevents_deletion(self):
        real=app.eligible;calls=[]
        def checked(*args,**kwargs):
            value=real(*args,**kwargs);calls.append(1)
            if kwargs.get('stream') is not None:
                self.state[self.key]['status']='needs_review';self.save()
            return value
        with patch.object(app,'eligible',side_effect=checked):self.assertEqual(self.run_cleanup()['deleted'],[])
        self.assertTrue(self.video.exists());self.assertGreaterEqual(len(calls),2)
    def test_duplicate_or_corrupt_state_refuses_all_deletion(self):
        for text in ['{bad json','{"key":{},"key":{}}','[]']:
            self.state_path.write_text(text)
            with self.assertRaises(ValueError):self.run_cleanup()
            self.assertTrue(self.video.exists())
    def test_audit_must_be_durable_before_unlink(self):
        real=app.append_event
        def fail_intent(stream,value):
            if value['event']=='delete_intent':raise OSError('disk full writing audit')
            return real(stream,value)
        with patch.object(app,'append_event',side_effect=fail_intent):self.assertEqual(self.run_cleanup()['deleted'],[])
        self.assertTrue(self.video.exists())


class WindowsDeletionHandleTests(unittest.TestCase):
    def test_exclusive_read_and_delete_handle_is_used_without_path_unlink(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'safe.mp4';path.write_bytes(b'proof')
            kernel=MagicMock();kernel.CreateFileW.return_value=123;kernel.SetFileInformationByHandle.return_value=True
            module=types.SimpleNamespace(open_osfhandle=lambda handle,flags:os.open(path,os.O_RDONLY))
            with patch.object(app.os,'name','nt'),patch.object(app.os,'O_BINARY',0,create=True),patch.dict(sys.modules,msvcrt=module), \
                 patch.object(app.ctypes,'WinDLL',return_value=kernel,create=True):
                with app.deletion_handle(path) as (stream,remove):
                    self.assertEqual(stream.read(),b'proof');remove()
            args=kernel.CreateFileW.call_args.args
            self.assertEqual(args[1:3],(0x80010000,1));self.assertEqual(args[4:6],(3,0x08200000))
            self.assertEqual(kernel.SetFileInformationByHandle.call_args.args[:2],(123,4));self.assertTrue(path.exists())
    def test_busy_windows_file_is_skipped(self):
        kernel=MagicMock();kernel.CreateFileW.return_value=ctypes.c_void_p(-1).value
        with patch.object(app.os,'name','nt'),patch.dict(sys.modules,msvcrt=types.SimpleNamespace()),patch.object(app.ctypes,'WinDLL',return_value=kernel,create=True):
            with self.assertRaises(OSError):
                with app.deletion_handle('safe.mp4'):self.fail('Must not return a handle for an occupied file')
        kernel.SetFileInformationByHandle.assert_not_called()


if __name__=='__main__':unittest.main()
