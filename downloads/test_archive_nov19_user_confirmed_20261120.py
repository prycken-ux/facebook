import copy,hashlib,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import archive_nov19_user_confirmed_20261120 as app
import add_fb_accounts

class Nov19ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for d in ('logs','backups','videos','profiles'):(self.root/d).mkdir()
        self.enterContext(patch.object(app.base.upload,'ROOT',self.root));self.enterContext(patch.object(add_fb_accounts,'ROOT',self.root))
        self.enterContext(patch.object(app,'inspect_workers',return_value=[]));self.enterContext(patch.object(app.base.recovery,'recover_locks'))
        self.jobs=[];state={}
        for i,(a,t) in enumerate(sorted(app.EXPECTED)):
            folder=self.root/'videos'/a/t/'inbox';folder.mkdir(parents=True,exist_ok=True)
            video=folder/('20261119-33a16789-eligible60-'+str(i)+'.mp4');video.write_bytes(('Nov19 '+a+'/'+t).encode())
            txt=video.with_suffix('.txt');txt.write_text('Nov19 immutable caption')
            video.with_suffix('.comment.txt').write_text('Original comment')
            url='https://www.facebook.com/profile.php?id='+str(100000000000000+i)
            key=app.base.upload.job_key(dict(url=url),video)
            job=dict(account=a,target=t,url=url,filename=video.name,key=key,video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),video_size=video.stat().st_size,caption_sha256=hashlib.sha256(txt.read_bytes()).hexdigest(),caption_text=txt.read_text())
            self.jobs.append(job)
            state[key]=dict(account=a,target=t,url=url,video=str(video),created='2026-11-19T04:00:00+00:00',status='needs_review' if i else 'published',ai_label_requested=False,comment_status='lookup_pending',comment_error='original lookup error',post_intent_at='2026-11-19T04:01:00+00:00')
            if not i:
                state[key].update(confirmation_method='real_platform_receipt',published_at='2026-11-19T04:02:00+00:00')
                completed=folder.parent/'completed';completed.mkdir();shutil.move(video,completed/video.name);shutil.move(txt,completed/txt.name)
                state[key]['archived_video']=str(completed/video.name)
        req=self.save_signed(app.REQUEST,dict(schema='eligible60-real-publication-request-v1',material_date=app.DAY,content_sha256=app.CONTENT_SHA,targets=[list(p) for p in sorted(app.EXPECTED)]))
        self.enterContext(patch.object(app,'SOURCE_PREFIX',req['sha256'][:16]))
        self.control='logs/eligible60-real-publication-'+req['sha256'][:16]+'.json';self.enterContext(patch.object(app,'CONTROLLER',self.control))
        p=dict(queue_id=req['sha256'],material_source_date=app.DAY,publication_content_sha256=app.CONTENT_SHA,jobs=self.jobs)
        sha=app.base.digest(p);name='frozen-material-2026-11-19-'+sha[:16]+'.json'
        self.save_signed('logs/'+name,p)
        self.save(self.control,dict(request_sha256=req['sha256'],waves=[dict(manifest=name,sha256=sha)]))
        for row in state.values():row.update(source_frozen_manifest=name,source_frozen_sha256=sha)
        self.save('logs/publish_state.json',state);self.before=copy.deepcopy(state)
        self.protected={}
        for relative,data in [('videos/fb04/personal/inbox/20261120-today.mp4',b'Friday new video'),('videos/fb17/personal/inbox/keep.mp4',b'Paused account media'),('profiles/fb63/Default/Cookies',b'original profile'),('upload_config.json',b'{"targets":[]}'),('fake-program.py',b'program')]:
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);self.protected[path]=data
    def save(self,name,value):app.base.upload.save_json(self.root/name,value)
    def save_signed(self,name,p):
        value=dict(payload=p,sha256=app.base.digest(p));self.save(name,value);return value
    def run_archive(self):return app.execute(self.root)
    def test_archive60_preserves_comments_and_new_media_and_tracks_two_manual_comments(self):
        self.assertEqual(self.run_archive(),0)
        state=app.base.upload.read_json(self.root/'logs/publish_state.json',{})
        self.assertEqual(len(state),60)
        for job in self.jobs:
            row=state[job['key']];old=self.before[job['key']]
            self.assertEqual(row['status'],'published');self.assertTrue(Path(row['archived_video']).is_file());self.assertIs(row['ai_label_requested'],False)
            self.assertEqual(row['source_frozen_manifest'],old['source_frozen_manifest'])
            pair=job['account'],job['target']
            if pair in app.MANUAL_COMMENTS:
                self.assertEqual(row['comment_status'],'already_present');self.assertEqual(row['user_supplied_permalink'],app.MANUAL_COMMENTS[pair]);self.assertEqual(row['comment_status_before_user_confirmation'],'lookup_pending')
            else:
                self.assertEqual(row['comment_status'],old['comment_status']);self.assertEqual(row['comment_error'],old['comment_error'])
            if old['status']=='published':self.assertEqual(row['confirmation_method'],'real_platform_receipt')
            else:self.assertEqual(row['confirmation_method'],app.METHOD);self.assertNotIn('published_at',row)
            self.assertNotIn('permalink',row)
        for path,data in self.protected.items():self.assertEqual(path.read_bytes(),data)
        value=app.base.upload.read_json(self.root/app.JOURNAL,{})
        self.assertEqual(app.base.upload.read_json(self.root/value['backup']/'publish_state.json',{}),self.before)
    def test_replay_does_not_include_new_files_or_change_state(self):
        self.run_archive();before=(self.root/'logs/publish_state.json').read_bytes();plan=(self.root/app.JOURNAL).read_bytes()
        new=self.root/'videos/fb04/personal/inbox/20261119-33a16789-eligible60-unlisted.mp4';new.write_bytes(b'unlisted file must stay')
        self.assertEqual(self.run_archive(),0);self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),before);self.assertEqual((self.root/app.JOURNAL).read_bytes(),plan);self.assertTrue(new.exists())
    def test_missing_or_changed_source_aborts_before_any_move(self):
        job=self.jobs[3];video=Path(self.before[job['key']]['video']);video.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'指纹变化'):self.run_archive()
        self.assertEqual(app.base.upload.read_json(self.root/'logs/publish_state.json',{}),self.before);self.assertFalse((self.root/app.JOURNAL).exists())
    def test_other_date_or_other_request_stops(self):
        with patch.object(app,'SOURCE_PREFIX','0'*16):
            with self.assertRaisesRegex(ValueError,'不是用户确认'):self.run_archive()
    def test_state_rebound_to_todays_media_is_not_marked(self):
        state=copy.deepcopy(self.before);state[self.jobs[3]['key']]['video']='20261120-today.mp4';self.save('logs/publish_state.json',state)
        with self.assertRaisesRegex(ValueError,'其他素材'):self.run_archive()
    def test_partial_move_resumes_original_snapshot(self):
        native=app.mark_with_manual_comments;calls=[]
        def interrupt(*args):
            if not calls:calls.append(True);raise KeyboardInterrupt
            return native(*args)
        with patch.object(app,'mark_with_manual_comments',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):self.run_archive()
        plan=(self.root/app.JOURNAL).read_bytes();self.assertEqual(self.run_archive(),0);self.assertEqual((self.root/app.JOURNAL).read_bytes(),plan)
    def test_manual_link_conflict_stops_before_move(self):
        job=next(j for j in self.jobs if (j['account'],j['target'])==('fb04','personal'))
        state=copy.deepcopy(self.before);state[job['key']]['permalink']='https://www.facebook.com/reel/999';self.save('logs/publish_state.json',state)
        with self.assertRaisesRegex(ValueError,'链接与原记录不同'):self.run_archive()
        self.assertFalse((self.root/app.JOURNAL).exists())
    def test_symlink_does_not_move_foreign_media(self):
        job=self.jobs[3];video=Path(self.before[job['key']]['video']);video.unlink();video.symlink_to(next(iter(self.protected)))
        with self.assertRaisesRegex(ValueError,'链接'):self.run_archive()
    def test_busy_worker_is_waited_out_without_changes(self):
        def wait(seconds):self.assertEqual(seconds,15);self.assertFalse((self.root/app.JOURNAL).exists())
        with patch.object(app,'inspect_workers',side_effect=[[dict(pid=777)],[]]),patch.object(app.base.time,'sleep',side_effect=wait):self.assertEqual(self.run_archive(),0)

if __name__=='__main__':unittest.main()
