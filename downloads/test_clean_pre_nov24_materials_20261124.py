import contextlib,copy,hashlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import clean_pre_nov24_materials_20261124 as app

class CleanupTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)/'project';self.root.mkdir();self.external=Path(tmp.name)/'sources';self.external.mkdir()
        self.enterContext(patch.object(app.upload,'ROOT',self.root));self.enterContext(patch.object(app.workers,'active_workers',return_value=[]));self.enterContext(patch.object(app.recovery,'recover_locks'));self.enterContext(patch.object(app,'locked',side_effect=contextlib.nullcontext));self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.write('upload_config.json',b'{}');self.write('profiles/fb01/Default/Login Data',b'credentials');self.write('material-staging/tools/fixture.mp4',b'tool fixture')
        self.old=self.make_distribution('2026-11-23','old.mp4',b'old source',stage=True)
        self.current=self.make_distribution('2026-11-24','2026-11-11_camera.mp4',b'current real video',stage=True)
        self.later=self.make_distribution('2026-11-25','future.mp4',b'future video',stage=True)
        self.key='a'*64;self.newkey='b'*64;self.state={self.key:dict(account='fb01',target='personal',video=str(self.old['inbox']),status='needs_review',post_intent_at='old-submission',comment_status='not_started'),self.newkey:dict(account='fb01',target='personal',video=str(self.current['inbox']),status='posting',post_intent_at='today-submission')}
        self.save(self.root/'logs/publish_state.json',self.state);self.write('logs/video_comments.json',b'{"receipt":"keep"}')
        self.job=dict(key=self.key,account='fb01',target='personal',filename=self.old['inbox'].name,video_size=len(b'old source'),video_sha256=hashlib.sha256(b'old source').hexdigest())
        self.freeze(dict(date='2026-11-24',material_source_date='2026-11-23',jobs=[self.job]))
    def write(self,name,data):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path
    def save(self,path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    def signed(self,p):return dict(payload=p,sha256=app.media.digest(p))
    def freeze(self,p):
        value=self.signed(p);self.save(self.root/'logs'/('frozen-material-'+p['date']+'-'+value['sha256'][:16]+'.json'),value)
    def make_distribution(self,d,name,data,stage=False):
        source=self.external/d;source.mkdir(exist_ok=True);original=source/name;original.write_bytes(data)
        dest=d.replace('-','')+'-12345678-eligible60-'+name
        info=dict(name=name,destination_name=dest,size=len(data),sha256=hashlib.sha256(data).hexdigest())
        p=dict(date=d,source=str(source),assignments=[dict(account='fb01',target='personal',files=[info])]);distribution=self.signed(p)
        self.save(self.root/'logs/material-distribution/pool'/(d+'-eligible60.json'),distribution)
        inbox=self.write('videos/fb01/personal/inbox/'+dest,data)
        folder=self.root/'material-staging'/d/'pool-eligible60';manifest=folder/'manifest.json';value=self.signed(dict(date=d,source=str(source),distribution=distribution));self.save(manifest,value)
        staged=folder/'videos/fb01/personal/inbox'/name;staged.parent.mkdir(parents=True);staged.write_bytes(data)
        if d=='2026-11-24':self.save(self.root/'material-staging/eligible60-20261124-pending-import.json',dict(complete=True,manifest=str(manifest.relative_to(self.root)),sha256=value['sha256']))
        return dict(inbox=inbox,source=original,staged=staged,manifest=manifest)
    def test_deletes_old_failed_pending_and_original_copies_protects_current_and_future(self):
        before=self.state[self.newkey].copy();app.execute(self.root)
        for p in ('inbox','source','staged'):self.assertFalse(self.old[p].exists(),p)
        for row in (self.current,self.later):
            for p in ('inbox','source','staged'):self.assertTrue(row[p].exists(),p)
        state=app.read(self.root/'logs/publish_state.json');self.assertEqual(state[self.newkey],before)
        self.assertEqual(state[self.key]['status'],'archived');self.assertEqual(state[self.key]['publication_status_before_user_archive'],'needs_review');self.assertEqual(state[self.key]['post_intent_at'],'old-submission')
        self.assertEqual((self.root/'logs/video_comments.json').read_bytes(),b'{"receipt":"keep"}')
        self.assertEqual((self.root/'profiles/fb01/Default/Login Data').read_bytes(),b'credentials')
        self.assertTrue((self.root/'material-staging/tools/fixture.mp4').exists())
        self.assertTrue(self.old['manifest'].exists())
    def test_old_camera_date_alone_never_qualifies(self):
        raw=self.write('videos/fb02/personal/inbox/2026-11-01_camera.mp4',b'unassigned unknown');app.execute(self.root);self.assertTrue(raw.exists())
    def test_current_content_hash_protects_a_duplicate_in_an_old_folder(self):
        p=self.write('material-staging/2026-11-20/old/current-copy.mp4',b'current real video');app.execute(self.root);self.assertTrue(p.exists())
    def test_external_unassigned_original_is_preserved(self):
        unknown=self.old['source'].parent/'unassigned.mp4';unknown.write_bytes(b'unknown');app.execute(self.root);self.assertTrue(unknown.exists())
    def test_changed_external_source_is_preserved(self):
        self.old['source'].write_bytes(b'replaced new file');app.execute(self.root);self.assertEqual(self.old['source'].read_bytes(),b'replaced new file')
    def test_link_to_unrelated_video_is_preserved(self):
        other=self.external/'other.mp4';other.write_bytes(b'other');link=self.root/'videos/fb01/personal/inbox/20261120-12345678-eligible60-link.mp4';link.symlink_to(other);app.execute(self.root);self.assertTrue(link.is_symlink());self.assertTrue(other.exists())
    def test_missing_current_pointer_blocks_all_deletion(self):
        (self.root/'material-staging/eligible60-20261124-pending-import.json').unlink()
        with self.assertRaisesRegex(ValueError,'24号素材未正式'):app.execute(self.root)
        self.assertTrue(self.old['source'].exists());self.assertEqual(app.read(self.root/'logs/publish_state.json'),self.state)
    def test_live_project_task_blocks_all_changes(self):
        with patch.object(app.workers,'active_workers',return_value=[dict(pid=123)]),self.assertRaisesRegex(ValueError,'仍有项目'):app.execute(self.root)
        self.assertTrue(self.old['inbox'].exists());self.assertEqual(app.read(self.root/'logs/publish_state.json'),self.state)
    def test_later_frozen_key_wins_over_historical_key(self):
        self.freeze(dict(date='2026-11-24',material_source_date='2026-11-24',jobs=[self.job]));app.execute(self.root)
        self.assertTrue(self.old['inbox'].exists());self.assertEqual(app.read(self.root/'logs/publish_state.json')[self.key],self.state[self.key])
    def test_scheduled_old_date_without_filename_date_is_cleaned(self):
        old=self.write('videos/fb02/personal/scheduled/2026-11-22/inbox/camera.mp4',b'old scheduled')
        new=self.write('videos/fb02/personal/scheduled/2026-11-24/inbox/camera.mp4',b'current scheduled');app.execute(self.root);self.assertFalse(old.exists());self.assertTrue(new.exists())
    def test_native_frozen_job_without_raw_sha_uses_owner_bound_key(self):
        video=self.write('videos/fb03/personal/completed/legacy-camera.mp4',b'legacy unknown-camera content')
        entry=dict(url='https://www.facebook.com/profile.php?id=100000000000003')
        key=app.upload.job_key(entry,video)
        job=dict(key=key,url=entry['url'],account='fb03',target='personal',filename=video.name,video_size=video.stat().st_size)
        self.freeze(dict(date='2026-11-22',jobs=[job]));app.execute(self.root);self.assertFalse(video.exists())
    def test_repeat_is_idempotent_preserves_original_outcome(self):
        app.execute(self.root);app.execute(self.root)
        self.assertEqual(app.read(self.root/'logs/publish_state.json')[self.key]['publication_status_before_user_archive'],'needs_review')

if __name__=='__main__':unittest.main()
