import copy,hashlib,unittest
from unittest.mock import patch
import archive_nov12_materials_20261113 as app
from test_scheduled_material_batch import ScheduledMaterialTests


class ArchiveNov12Tests(unittest.TestCase):
    def setUp(self):
        self.fx=ScheduledMaterialTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.root=self.fx.root;records=[];jobs=[];state={};self.videos={}
        statuses=['published','failed_before_post','needs_review','preparing','posting',None,'published',None,None,None]
        for n,status in enumerate(statuses,1):
            account=f'fb{n:02d}';target='personal';filename='yesterday.mp4'
            video=self.root/'videos'/account/target/'inbox'/filename;video.parent.mkdir(parents=True,exist_ok=True)
            video.write_bytes(('Nov12 original '+account).encode());caption=video.with_suffix('.txt');caption.write_text('Original caption '+account)
            checksum=hashlib.sha256(video.read_bytes()).hexdigest();url='https://www.facebook.com/profile.php?id='+str(90000+n)
            key=app.upload.job_key(dict(url=url),video)
            records.append(dict(account=account,target=target,filename=filename,video_sha256=checksum,size=video.stat().st_size))
            job=dict(account=account,target=target,filename=filename,key=key,url=url,video_sha256=checksum,
                     video_size=video.stat().st_size,caption_sha256=hashlib.sha256(caption.read_bytes()).hexdigest())
            if n!=10:jobs.append(job)
            if status:state[key]=dict(account=account,target=target,url=url,video=str(video),status=status,
                                     comment_status='sent' if n==1 else 'needs_review',post_intent_at='old intent' if n in (3,5) else '')
            self.videos[n]=video
        payload=dict(scope=app.SCOPE,date=app.DAY,records=records)
        checksum=app.batch.digest(payload)
        self.control=self.root/'logs/nov12-current-materials-original-accounts.json'
        app.upload.save_json(self.control,dict(payload=payload,sha256=checksum,plans=[]))
        frozen=dict(schema=app.batch.SCHEMA,date=app.DAY,current_material_scope=app.SCOPE,current_snapshot_sha256=checksum,jobs=jobs)
        checksum=app.batch.digest(frozen)
        self.manifest=self.root/'logs'/('frozen-material-'+app.DAY+'-'+checksum[:16]+'.json')
        app.upload.save_json(self.manifest,dict(payload=frozen,sha256=checksum))
        completed=self.videos[7].parent.parent/'completed';completed.mkdir()
        self.videos[7].rename(completed/self.videos[7].name)
        self.videos[7].with_suffix('.txt').rename(completed/'yesterday.txt')
        self.videos[9].write_bytes(b'Nov13 newer video with the old filename')
        today=dict(schema='one-video-per-target-distribution-v1',date=app.TODAY,
                   assignments=[dict(account='fb08',target='personal',files=[dict(destination_name='yesterday.mp4'),dict(destination_name='yesterday.txt')])])
        folder=self.root/'logs/material-distribution/sourceid';folder.mkdir(parents=True)
        app.upload.save_json(folder/(app.TODAY+'.json'),dict(payload=today,sha256=app.batch.digest(today)))
        self.state_before=copy.deepcopy(state);app.upload.save_json(self.fx.state_path,state)
        self.comments=self.root/'logs/video_comments.json';self.comments.write_bytes(b'{"manual-comments":"preserve"}')
        self.preserved={p:p.read_bytes() for p in (self.control,self.manifest,self.comments,app.upload.CONFIG)}

    def test_archives_exact_old_bytes_with_statuses_unchanged_and_preserves_today_and_changed_files(self):
        with patch.object(app.upload,'run_entry',side_effect=AssertionError('No publication')):
            self.assertEqual(app.execute(),3)
        state=app.upload.read_json(self.fx.state_path,{})
        self.assertEqual(set(state),set(self.state_before))
        for key,old in self.state_before.items():
            self.assertEqual(state[key]['status'],old['status'])
            self.assertEqual(state[key]['comment_status'],old['comment_status'])
            self.assertEqual(state[key]['post_intent_at'],old['post_intent_at'])
        for n in (1,2,3,4,5,6,10):self.assertFalse(self.videos[n].exists())
        self.assertTrue(list((self.root/'videos/fb01/personal/completed'/app.DAY).rglob('yesterday.mp4')))
        self.assertTrue(list((self.root/'videos/fb03/personal/archive'/app.DAY).rglob('yesterday.mp4')))
        self.assertTrue(self.videos[8].exists());self.assertTrue(self.videos[9].exists())
        self.assertEqual(self.videos[9].read_bytes(),b'Nov13 newer video with the old filename')
        for path,data in self.preserved.items():self.assertEqual(path.read_bytes(),data)
        files={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
        app.execute()
        self.assertEqual(files,{p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()})

    def test_interruption_after_committed_move_resumes_without_overwriting(self):
        original=app.move_exact;calls=[]
        def interrupt(item):
            original(item);calls.append(item);raise KeyboardInterrupt
        with patch.object(app,'move_exact',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):app.execute()
        self.assertEqual(len(calls),1)
        self.assertEqual(app.execute(),3)
        self.assertFalse(self.videos[1].exists())
        self.assertEqual(self.comments.read_bytes(),self.preserved[self.comments])

    def test_tampered_snapshot_aborts_before_moving_any_video(self):
        value=app.upload.read_json(self.control,{})
        value['payload']['records'][0]['filename']='new-file.mp4'
        app.upload.save_json(self.control,value)
        before=self.fx.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError,'校验失败'):app.execute()
        self.assertTrue(self.videos[1].exists());self.assertEqual(self.fx.state_path.read_bytes(),before)

    def test_later_today_assignment_protects_an_already_planned_source(self):
        records,jobs,origin=app.source()
        app.prepare(records,jobs,origin,app.upload.read_json(self.fx.state_path,{}))
        path=next((self.root/'logs/material-distribution').glob('*/*.json'))
        value=app.upload.read_json(path,{})
        value['payload']['assignments'].append(dict(account='fb01',target='personal',files=[dict(destination_name='yesterday.mp4')]))
        value['sha256']=app.batch.digest(value['payload']);app.upload.save_json(path,value)
        app.execute()
        self.assertTrue(self.videos[1].exists())
        self.assertTrue(self.videos[1].with_suffix('.txt').exists())


if __name__=='__main__':unittest.main()
