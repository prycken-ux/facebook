import copy,hashlib,shutil,unittest
from pathlib import Path
from unittest.mock import patch
import archive_history_through_20261119 as app
import test_archive_nov19_user_confirmed_20261120 as fixture

class HistoryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.Nov19ArchiveTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        self.fx.save('account_registry.json',dict(accounts=[]))
        self.enterContext(patch.object(app,'inspect_workers',return_value=[]))
        self.enterContext(patch.object(app.base.recovery,'recover_locks'))
        state=app.base.upload.read_json(self.root/'logs/publish_state.json',{})
        self.old=self.root/'videos/fb04/personal/inbox/old-before-nov19.mp4';self.old.write_bytes(b'Nov18 old unique video')
        self.old.with_suffix('.txt').write_text('old caption')
        old_entry=dict(url=self.fx.jobs[3]['url'])
        source=next(j for j in self.fx.jobs if (j['account'],j['target'])==('fb04','personal'));old_entry['url']=source['url']
        self.oldkey=app.base.upload.job_key(old_entry,self.old)
        job=dict(source,filename=self.old.name,key=self.oldkey,video_sha256=hashlib.sha256(self.old.read_bytes()).hexdigest(),video_size=self.old.stat().st_size)
        p=dict(date='2026-11-18',jobs=[job]);sha=app.base.digest(p);name='frozen-material-2026-11-18-'+sha[:16]+'.json'
        self.fx.save_signed('logs/'+name,p)
        state[self.oldkey]=dict(account='fb04',target='personal',url=old_entry['url'],video=str(self.old),status='needs_review',comment_status='not_started',created='2026-11-18T04:00:00+00:00',source_frozen_manifest=name)
        self.fx.save('logs/publish_state.json',state);self.before=copy.deepcopy(state)
        self.unknown=self.old.parent/'unknown-current-material.mp4';self.unknown.write_bytes(b'unknown may be today, retain')
        self.future=[]
        for d in ('2026-11-20','2026-11-21','2026-11-22'):
            f=self.root/'videos/fb04/personal/scheduled'/d/'inbox'/'same-old-name.mp4';f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(self.old.read_bytes());self.future.append(f)
        self.protected={p:p.read_bytes() for p in (*self.future,self.unknown,*self.fx.protected)}
    def run_archive(self):return app.execute(self.root)
    def test_all_known_history_archived_nov19_confirmed_older_outcomes_preserved_and_future_untouched(self):
        self.assertEqual(self.run_archive(),0)
        state=app.base.upload.read_json(self.root/'logs/publish_state.json',{})
        for job in self.fx.jobs:
            row=state[job['key']]
            self.assertEqual(row['status'],'published');self.assertEqual(row['archive_status'],'archived');self.assertEqual(row['comment_status'],self.before[job['key']]['comment_status']);self.assertEqual(row['comment_error'],self.before[job['key']]['comment_error'])
            self.assertTrue(Path(row['archived_video']).is_file())
            if self.before[job['key']]['status']=='published':self.assertEqual(row['confirmation_method'],'real_platform_receipt')
            else:self.assertEqual(row['confirmation_method'],app.METHOD);self.assertNotIn('published_at',row)
        self.assertEqual(state[self.oldkey]['status'],'archived');self.assertEqual(state[self.oldkey]['publication_status_before_user_archive'],'needs_review');self.assertEqual(state[self.oldkey]['comment_status'],'not_started')
        for p,raw in self.protected.items():self.assertEqual(p.read_bytes(),raw)
        self.assertFalse(self.old.exists())
        plan=app.base.upload.read_json(self.root/app.JOURNAL,{})
        self.assertEqual(len(plan['payload']['rows']),61);self.assertTrue(any(r['filename']==self.unknown.name for r in plan['payload']['retained_for_review']))
    def test_windows_record_paths_bind_correctly(self):
        state=copy.deepcopy(self.before)
        for row in state.values():
            if row.get('video'):row['video']=row['video'].replace('/',chr(92))
        self.fx.save('logs/publish_state.json',state)
        self.assertEqual(self.run_archive(),0)
        current=app.base.upload.read_json(self.root/'logs/publish_state.json',{})
        self.assertTrue(all(current[j['key']]['status']=='published' for j in self.fx.jobs))

    def test_replay_does_not_take_new_old_named_or_current_videos(self):
        self.run_archive();before=(self.root/'logs/publish_state.json').read_bytes();plan=(self.root/app.JOURNAL).read_bytes()
        later=self.old.parent/'late-manual.mp4';later.write_bytes(b'added after snapshot')
        self.assertEqual(self.run_archive(),0);self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),before);self.assertEqual((self.root/app.JOURNAL).read_bytes(),plan);self.assertTrue(later.exists())
    def test_interruption_after_move_resumes_original_snapshot(self):
        native=app.mark;calls=[]
        def stop(*args):
            if not calls:calls.append(True);raise KeyboardInterrupt
            return native(*args)
        with patch.object(app,'mark',side_effect=stop):
            with self.assertRaises(KeyboardInterrupt):self.run_archive()
        before=(self.root/app.JOURNAL).read_bytes();self.assertEqual(self.run_archive(),0);self.assertEqual((self.root/app.JOURNAL).read_bytes(),before)
    def test_future_manifest_protects_old_looking_name(self):
        job=next(j for j in self.fx.jobs if (j['account'],j['target'])==('fb04','personal'))
        p=dict(date='2026-11-20',material_source_date='2026-11-20',jobs=[job]);sha=app.base.digest(p)
        self.fx.save_signed('logs/frozen-material-2026-11-20-'+sha[:16]+'.json',p)
        original=Path(self.before[job['key']]['video']);self.run_archive();self.assertTrue(original.exists())
        self.assertEqual(app.base.upload.read_json(self.root/'logs/publish_state.json',{})[job['key']],self.before[job['key']])
    def test_same_video_old_archived_copy_does_not_overwrite_new_task_state(self):
        state=copy.deepcopy(self.before);state[self.oldkey].update(video=str(self.old.parent/'20261120-new.mp4'),created='2026-11-20T04:00:00+00:00',archived_video=str(self.old),status='posting');self.fx.save('logs/publish_state.json',state)
        self.run_archive();self.assertEqual(app.base.upload.read_json(self.root/'logs/publish_state.json',{})[self.oldkey],state[self.oldkey])
    def test_changed_file_after_snapshot_is_not_moved_or_marked(self):
        with app.base.locked():app.prepare(self.root)
        job=self.fx.jobs[3];p=Path(self.before[job['key']]['video']);p.write_bytes(b'changed')
        self.assertEqual(self.run_archive(),3);self.assertTrue(p.exists());self.assertEqual(app.base.upload.read_json(self.root/'logs/publish_state.json',{})[job['key']],self.before[job['key']])
    def test_archive_manifest_tamper_is_refused(self):
        with app.base.locked():app.prepare(self.root)
        p=self.root/app.JOURNAL;value=app.base.upload.read_json(p,{});value['payload']['cutoff']='2026-11-22';self.fx.save(app.JOURNAL,value)
        with self.assertRaisesRegex(ValueError,'清单异常'):self.run_archive()
    def test_busy_publisher_waits_and_does_not_terminate_it(self):
        def wait(seconds):self.assertEqual(seconds,15);self.assertFalse((self.root/app.JOURNAL).exists())
        with patch.object(app,'inspect_workers',side_effect=[[dict(pid=123)],[]]),patch.object(app.base.time,'sleep',side_effect=wait):self.assertEqual(self.run_archive(),0)

if __name__=='__main__':unittest.main()
