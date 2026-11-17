import copy,os,subprocess,unittest
from pathlib import Path
from unittest.mock import patch
import archive_all_user_confirmed_20261117 as app
from test_distribute_video_materials import DistributionTests

class All74UserArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fx=DistributionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        self.enterContext(patch.object(app,'inspect_workers',return_value=[]));self.enterContext(patch.object(app.recovery,'recover_locks'))
        self.entries={(r['account'],r['target']):r for r in app.upload.read_json(self.root/'upload_config.json',{})['targets']}
        self.files=[]
        for account,target,name in [('fb01','page01','new.mp4'),('fb09','page10','needs.mp4'),('fb17','personal','paused.mp4'),('fb23','personal','manual.mp4'),('fb28','personal','pending.mp4'),('fb74','personal','last.mp4')]:
            base=self.root/'videos'/account/target/'inbox';base.mkdir(parents=True,exist_ok=True)
            video=base/name;video.write_bytes(('video '+account+target).encode());video.with_suffix('.txt').write_text('caption '+account);video.with_suffix('.comment.txt').write_text('comment '+account)
            self.files.append(video)
        self.completed=self.root/'videos/fb01/page01/completed/old.mp4';self.completed.parent.mkdir(parents=True);self.completed.write_bytes(b'old published footage')
        self.archived=self.root/'videos/fb17/personal/archive/older.mp4';self.archived.parent.mkdir(parents=True);self.archived.write_bytes(b'older review footage')
        self.foreign=self.root/'videos/fb75/personal/inbox/keep.mp4';self.foreign.parent.mkdir(parents=True);self.foreign.write_bytes(b'outside scope')
        self.pool=self.root/'总素材/source.mp4';self.pool.write_bytes(b'original source retained')
        self.program=self.root/'fake-program.py';self.program.write_text('program must stay')
        self.profile=self.root/'profiles/fb01/Default/Cookies';self.profile.parent.mkdir(parents=True);self.profile.write_bytes(b'profile bytes must not be opened')
        state=app.upload.read_json(self.root/'logs/publish_state.json',{})
        self.keys={}
        for video,status in [(self.files[0],'failed_before_post'),(self.files[1],'needs_review'),(self.files[2],'posting'),(self.completed,'published')]:
            account,target=video.relative_to(self.root).parts[1:3];entry=self.entries[account,target];key=app.upload.job_key(entry,video);self.keys[video]=key
            state[key]=dict(account=account,target=target,url=entry['url'],video=str(video),status=status,ai_label_requested=True,comment_status='needs_review',comment_error='old comment error',error='old video error',post_intent_at='2026-11-16T10:00:00+00:00')
            if status=='published':state[key].update(confirmation_method='fresh_success_ui_and_composer_closed',published_at='2026-11-16T10:00:03+00:00',success_message='real receipt')
        app.upload.save_json(self.root/'logs/publish_state.json',state);self.state=copy.deepcopy(state)
        self.protected={p:p.read_bytes() for p in (self.foreign,self.pool,self.program,self.profile,self.root/'upload_config.json',self.root/'account_registry.json',self.root/'additional_personal_accounts.json')}
    def run_archive(self):return app.execute(self.root)
    def plan(self):return app.checked_plan(self.root,self.root/app.JOURNAL)
    def test_all_media_include_manual23_paused17_pending28_and74_preserve_comments_program_and_sources(self):
        self.assertEqual(self.run_archive(),0);plan=self.plan();rows=plan['payload']['rows'];self.assertEqual(len(rows),8)
        self.assertTrue({'fb17','fb23','fb28','fb74'}<={r['account'] for r in rows})
        state=app.upload.read_json(self.root/'logs/publish_state.json',{})
        for video,key in self.keys.items():
            record=state[key];self.assertEqual(record['status'],'published');self.assertEqual(record['comment_status'],'needs_review');self.assertEqual(record['comment_error'],'old comment error');self.assertIs(record['ai_label_requested'],True)
            if video!=self.completed:
                self.assertEqual(record['confirmation_method'],app.METHOD);self.assertEqual(record['status_before_user_confirmation'],self.state[key]['status']);self.assertNotIn('published_at',record);self.assertNotIn('permalink',record)
            else:
                for field in ('confirmation_method','published_at','success_message'):self.assertEqual(record[field],self.state[key][field])
        self.assertEqual(state['older'],self.state['older'])
        manual=next(r for r in rows if r['account']=='fb23');newkey=manual['bindings'][0]['key'];self.assertEqual(state[newkey]['status'],'published');self.assertNotIn('ai_label_requested',state[newkey])
        for row in rows:
            for item in row['files']:
                dest=self.root/item['destination'];self.assertTrue(dest.is_file());self.assertEqual(app.info(self.root,dest)[0],{k:item[k] for k in ('size','sha256')})
                if item['source']!=item['destination']:self.assertFalse((self.root/item['source']).exists())
        for path,data in self.protected.items():self.assertEqual(path.read_bytes(),data)
        backup=self.root/plan['backup'];self.assertEqual(app.upload.read_json(backup/'publish_state.json',{}),self.state)
        ledger=app.upload.read_json(self.root/app.LEDGER,{})['rows'];self.assertEqual(len(ledger),8)
        pending=[r for r in rows if r['account'] in {'fb28','fb74'}];self.assertTrue(all(not r['bindings'] for r in pending));self.assertTrue(all(ledger[r['id']]['status']=='published' for r in pending))
    def test_replay_fixed_snapshot_does_not_take_future_new_video_or_change_timestamps(self):
        self.run_archive();state=(self.root/'logs/publish_state.json').read_bytes();ledger=(self.root/app.LEDGER).read_bytes()
        video=self.files[0].parent/'future.mp4';video.parent.mkdir(parents=True,exist_ok=True);video.write_bytes(b'new after snapshot')
        self.assertEqual(self.run_archive(),0);self.assertTrue(video.exists());self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),state);self.assertEqual((self.root/app.LEDGER).read_bytes(),ledger)
    def test_moved_but_unmarked_interruption_resumes_without_duplicate_or_loss(self):
        original=app.mark_row;count=0
        def interrupt(*args):
            nonlocal count
            count+=1
            if count==1:raise KeyboardInterrupt
            return original(*args)
        with patch.object(app,'mark_row',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):self.run_archive()
        plan=(self.root/app.JOURNAL).read_bytes();self.assertEqual(self.run_archive(),0);self.assertEqual((self.root/app.JOURNAL).read_bytes(),plan)
        self.assertEqual(len(app.upload.read_json(self.root/app.LEDGER,{})['rows']),8)
    def test_busy_task_makes_no_plan_move_or_state_change_until_exit(self):
        def wait(seconds):
            self.assertEqual(seconds,15);self.assertFalse((self.root/app.JOURNAL).exists());self.assertTrue(all(p.exists() for p in self.files));self.assertEqual(app.upload.read_json(self.root/'logs/publish_state.json',{}),self.state)
        with patch.object(app,'inspect_workers',side_effect=[[dict(pid=777)],[]]),patch.object(app.time,'sleep',side_effect=wait) as sleep:
            self.assertEqual(self.run_archive(),0)
        sleep.assert_called_once()
    def test_changed_video_never_gets_marked_success_or_moved(self):
        with app.locked():app.prepare(self.root)
        video=self.files[0];video.write_bytes(b'changed after snapshot')
        self.assertEqual(self.run_archive(),3);self.assertTrue(video.exists())
        state=app.upload.read_json(self.root/'logs/publish_state.json',{});self.assertEqual(state[self.keys[video]]['status'],'failed_before_post')
    def test_symlink_inside_selected_tree_aborts_before_any_move(self):
        link=self.files[0].parent/'link.mp4';link.symlink_to(self.foreign)
        with self.assertRaisesRegex(ValueError,'链接'):self.run_archive()
        self.assertTrue(all(p.exists() for p in self.files));self.assertFalse((self.root/app.JOURNAL).exists())
    def test_unknown_owner_never_gets_guessed_state_identity(self):
        self.run_archive();state=app.upload.read_json(self.root/'logs/publish_state.json',{})
        self.assertFalse(any(r.get('account') in {'fb28','fb74'} for r in state.values()))
    def test_plan_tamper_stops_before_any_move(self):
        with app.locked():app.prepare(self.root)
        path=self.root/app.JOURNAL;value=app.upload.read_json(path,{});value['payload']['rows'][0]['account']='fb75';app.upload.save_json(path,value)
        with self.assertRaisesRegex(ValueError,'清单校验失败'):self.run_archive()
        self.assertTrue(all(p.exists() for p in self.files))
    def test_four_layer_venv_chain_exempts_only_archive_entry(self):
        from test_nov16_venv_process_chain import VenvProcessChainTests
        f=VenvProcessChainTests();f.setUp();rows=copy.deepcopy(f.rows)
        body=f.body.replace('start_finish_first24_nov16','start_archive_all_user_confirmed_20261117').replace('verified-nov16-first24-and-nov14-stage','verified-user-confirmed-all74-archive')
        for row in rows[2:]:row['command']=subprocess.list2cmdline([f.exe,'-u','-c',body,f.root])
        rows.append(f.row(96,1,['-u',f.root+r'\publish_queued_new50_20261116.py',f.root]))
        with patch.object(app.workers,'BOOTSTRAP',app.BOOTSTRAP):workers,allowed=app.workers.classify_workers(rows,f.root,100,f.runner)
        self.assertEqual(allowed,[97,98,99,100]);self.assertEqual([r['pid'] for r in workers],[96])

if __name__=='__main__':unittest.main()
