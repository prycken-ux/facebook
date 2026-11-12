import copy,hashlib
import unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

import recover_nov11_missed_20261112 as app
import publish_existing_20261111 as existing
import test_publish_today_20261111 as fixtures


class YesterdayMissedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.Nov11DirectTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.f.root;self.stack=self.fx.f.stack
        config=app.upload.read_json(app.upload.CONFIG,{})
        config['targets']=[e for e in config['targets'] if e['account'] not in {'fb16','fb18','fb21'}]
        app.upload.save_json(app.upload.CONFIG,config)
        app.upload.save_json(self.root/'account_registry.json',dict(accounts=copy.deepcopy(config['targets'])))
        with patch.object(existing.base.workflow,'run',return_value=3) as run:existing.execute(True)
        self.path=run.call_args.args[0];self.parent=app.upload.read_json(self.path,{})
        self.assertEqual(len(self.parent['payload']['jobs']),30)
        self.stack.enter_context(patch.object(app,'PARENT_PREFIX',self.parent['sha256'][:8]))
        clock=self.stack.enter_context(patch.object(app,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,12,4,tzinfo=timezone.utc)
        self.state={}
        for index,job in enumerate(self.parent['payload']['jobs']):
            status='failed_before_post' if job['account']=='fb17' else 'published' if index%2==0 else 'needs_review'
            self.state[job['key']]=dict(account=job['account'],target=job['target'],url=job['url'],video=str(self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']),status=status,created='2026-11-11T09:00:00+00:00')
            if status!='failed_before_post':self.state[job['key']]['post_intent_at']='2026-11-11T09:01:00+00:00'
        app.upload.save_json(self.fx.f.state_path,self.state);self.state_before=self.fx.f.state_path.read_bytes()
        self.old=next(j for j in self.parent['payload']['jobs'] if j['account']=='fb17')
        app.upload.save_json(self.path.with_name(self.path.stem+'-results.json'),dict(manifest=self.path.name,attempts=[dict(key=j['key'],action='finished') for j in self.parent['payload']['jobs']]))
        self.main_pointer=self.root/'logs/priority-batch-2026-11-11.json';self.pointer_before=self.main_pointer.read_bytes();self.parent_before=self.path.read_bytes()
        self.today_pointer=self.root/'logs/priority-batch-2026-11-12.json';self.today_pointer.write_text('{"untouched":"today primary"}');self.today_before=self.today_pointer.read_bytes()
        self.old_ledger=self.root/'logs/video_comments.json';self.old_ledger.write_text('{"old":{"status":"needs_review"}}');self.ledger_before=self.old_ledger.read_bytes()

    def discovered(self,account):
        number=99017 if account=='fb17' else 10000+int(account[2:])
        entry=dict(account=account,target='personal',type='personal',workflow='personal_recording_v1',name='Current '+account,url='https://www.facebook.com/profile.php?id='+str(number),auto_switch_personal=True)
        proof=dict(target_url=entry['url'],name=entry['name'],method='personal_actor_id_match',session_marker=hashlib.sha256(('personal:'+str(number)).encode()).hexdigest(),checked_at='2026-11-12T04:00:00+00:00')
        return entry,proof

    def prepare(self,discovery=None):
        with patch.object(app,'yesterday_file',return_value=True),patch.object(app,'discover_personal',side_effect=discovery or self.discovered):return app.prepare(self.path,self.parent)

    def assert_history_preserved(self):
        self.assertEqual(self.fx.f.state_path.read_bytes(),self.state_before);self.assertEqual(self.path.read_bytes(),self.parent_before)
        self.assertEqual(self.main_pointer.read_bytes(),self.pointer_before);self.assertEqual(self.today_pointer.read_bytes(),self.today_before);self.assertEqual(self.old_ledger.read_bytes(),self.ledger_before)

    def test_correct_parent_and_failed_fb17_are_bound_to_exact_original_material(self):
        self.assertEqual(app.parent_source(),(self.path,self.parent))
        self.assertEqual(app.safe_failed_fb17(self.parent,self.state),self.old)
        self.state[self.old['key']]['post_intent_at']='uncertain submission'
        with self.assertRaises(ValueError):app.safe_failed_fb17(self.parent,self.state)

    def test_timestamp_rule_excludes_todays_copies_and_older_unrelated_backlog(self):
        yesterday=datetime(2026,11,11,4,tzinfo=timezone.utc).timestamp();today=yesterday+86400
        self.assertTrue(app.yesterday_file(SimpleNamespace(st_ctime=yesterday,st_mtime=yesterday-86400)))
        self.assertTrue(app.yesterday_file(SimpleNamespace(st_ctime=yesterday-86400,st_mtime=yesterday)))
        self.assertFalse(app.yesterday_file(SimpleNamespace(st_ctime=today,st_mtime=yesterday)))
        self.assertFalse(app.yesterday_file(SimpleNamespace(st_ctime=yesterday,st_mtime=today)))
        self.assertFalse(app.yesterday_file(SimpleNamespace(st_ctime=yesterday-86400,st_mtime=yesterday-86400)))

    def test_prepares_only_15_missed_targets_and_rebinds_failed_video_to_new_fb17(self):
        path,value=self.prepare();jobs=value['payload']['jobs']
        self.assertEqual(len(jobs),15);self.assertEqual({(j['account'],j['target']) for j in jobs},app.PAIRS)
        self.assertEqual(value['payload']['date'],app.RUN_DATE);self.assertEqual(value['payload']['source_date'],app.DAY)
        self.assertFalse({j['key'] for j in jobs}&{j['key'] for j in self.parent['payload']['jobs']})
        new=next(j for j in jobs if j['account']=='fb17');self.assertEqual(new['source_old_key'],self.old['key']);self.assertNotEqual(new['url'],self.old['url']);self.assertEqual(new['filename'],self.old['filename'])
        app.validate(path,value,self.parent)
        for job in jobs:app.batch.validate_job(job,date=app.RUN_DATE)
        self.assert_history_preserved()

    def test_rerun_resumes_frozen_recovery_without_connecting_or_adding_new_files(self):
        path,value=self.prepare();before=path.read_bytes()
        (self.root/'videos/fb09/page01/inbox/later.mp4').write_bytes(b'todays fresh material')
        with patch.object(app,'discover_personal',side_effect=AssertionError('must not rewrite frozen owner')):
            again,second=app.prepare(self.path,self.parent)
        self.assertEqual(again,path);self.assertEqual(second,value);self.assertEqual(path.read_bytes(),before);self.assert_history_preserved()

    def test_failed_new_fb17_verification_cannot_fall_back_to_old_owner(self):
        def discover(account):
            if account=='fb17':raise ValueError('new login not ready')
            return self.discovered(account)
        path,value=self.prepare(discover)
        self.assertEqual(len(value['payload']['jobs']),14);self.assertNotIn('fb17',{j['account'] for j in value['payload']['jobs']});self.assert_history_preserved()

    def test_duplicate_owner_or_invalid_proof_cannot_replace_registry(self):
        config=app.upload.read_json(app.upload.CONFIG,{});registry=app.upload.read_json(self.root/'account_registry.json',{});extra=app.upload.read_json(self.root/'additional_personal_accounts.json',{})
        entry,proof=self.discovered('fb17');entry['url']='https://www.facebook.com/profile.php?id=10013';proof.update(target_url=entry['url'],session_marker=hashlib.sha256(b'personal:10013').hexdigest())
        with self.assertRaisesRegex(ValueError,'其他编号'):app.registration_plan(config,registry,extra,'fb17',entry,proof,self.old)
        entry,proof=self.discovered('fb17');proof['session_marker']='wrong'
        with self.assertRaises(ValueError):app.registration_plan(config,registry,extra,'fb17',entry,proof,self.old)
        self.assert_history_preserved()

    def test_fb24_cannot_adopt_deleted_legacy_reservation(self):
        config=app.upload.read_json(app.upload.CONFIG,{});registry=app.upload.read_json(self.root/'account_registry.json',{});extra=app.upload.read_json(self.root/'additional_personal_accounts.json',{})
        extra['slots']['fb24']['batch_id']='deleted-legacy-account';entry,proof=self.discovered('fb24')
        with self.assertRaisesRegex(ValueError,'不是这次预留'):app.registration_plan(config,registry,extra,'fb24',entry,proof,self.old)

    def test_connection_write_failure_restores_original_config_and_registration(self):
        paths=[app.upload.CONFIG,self.root/'account_registry.json',self.root/'additional_personal_accounts.json'];before={p:p.read_bytes() for p in paths};original=app.upload.save_json
        def save(path,value):
            if path==paths[1]:raise OSError('registration write failed')
            return original(path,value)
        with patch.object(app,'discover_personal',side_effect=self.discovered),patch.object(app.upload,'save_json',side_effect=save):
            with self.assertRaises(OSError):app.connect('fb17',self.old)
        for path,data in before.items():self.assertEqual(path.read_bytes(),data)
        self.assert_history_preserved()

    def test_changed_original_failed_file_is_never_replaced_by_another_mp4(self):
        file=self.root/'videos/fb17/personal/inbox'/self.old['filename'];file.write_bytes(b'changed data')
        with patch.object(app,'yesterday_file',return_value=True):
            with self.assertRaisesRegex(ValueError,'内容已变化'):app.snapshot(self.parent)

    def test_parent_success_or_uncertain_job_cannot_be_injected_into_recovery(self):
        path,value=self.prepare();bad=copy.deepcopy(value);victim=next(j for j in self.parent['payload']['jobs'] if j['account']!='fb17')
        bad['payload']['jobs'][0]['key']=victim['key'];checksum=app.batch.digest(bad['payload']);bad['sha256']=checksum
        newpath=path.with_name('frozen-material-'+app.RUN_DATE+'-'+checksum[:16]+'.json')
        with self.assertRaises(ValueError):app.validate(newpath,bad,self.parent)

    def test_pipeline_orders_only_recovery_jobs_and_preserves_both_daily_pointers(self):
        path,value=self.prepare();events=[];context=MagicMock();original_launch=app.upload.launch_context
        def videos(*args,**kwargs):
            events.append('videos');self.assertEqual(args[0],path);self.assertTrue(kwargs['retry_before_post']);self.assertTrue(kwargs['defer_comments'])
            state=app.upload.read_json(self.fx.f.state_path,{})
            for job in value['payload']['jobs']:state[job['key']]=dict(status='published',comment_status='deferred')
            app.upload.save_json(self.fx.f.state_path,state)
        def comments(*args,**kwargs):
            events.append('comments');self.assertEqual(args[0],value);self.assertTrue(kwargs['future_only'])
            state=app.upload.read_json(self.fx.f.state_path,{})
            for job in value['payload']['jobs']:state[job['key']]['comment_status']='sent'
            app.upload.save_json(self.fx.f.state_path,state)
        def tick(*args):app.datetime.now.return_value+=timedelta(seconds=76)
        with patch.object(app,'require_day'),patch.object(app,'recover_locks'),patch.object(app,'prepare',return_value=(path,value)),patch.object(app.normal,'launcher_for_jobs',return_value=lambda *a:context) as launcher,patch.object(app,'close_selected_window'),patch('playwright.sync_api.sync_playwright'),patch.object(app.local,'self_check') as check,patch.object(app.time,'sleep',side_effect=tick),patch.object(app.batch,'run',side_effect=videos),patch.object(app.priority.retry,'run',side_effect=lambda *a:events.append('video-retry')),patch.object(app.priority.daily,'backfill',side_effect=comments),patch.object(app.priority.comment_retry,'run',side_effect=lambda *a,**k:events.append('comment-retry')),patch.object(app.batch,'results'):
            self.assertEqual(app.execute(),0)
        self.assertEqual(events,['videos','video-retry','comments','comment-retry']);check.assert_called_once();launcher.assert_called_once_with(value['payload']['jobs'],date=app.RUN_DATE)
        state=app.upload.read_json(self.fx.f.state_path,{})
        for key,row in self.state.items():self.assertEqual(state[key],row)
        self.assertEqual(self.main_pointer.read_bytes(),self.pointer_before);self.assertEqual(self.today_pointer.read_bytes(),self.today_before);self.assertIs(app.upload.launch_context,original_launch)

    def test_current_owner_discovery_reads_public_name_then_requires_identity_proof(self):
        context=MagicMock();page=MagicMock();context.pages=[page];context.cookies.return_value=[dict(name='c_user',value='99017')]
        heading=MagicMock();heading.is_visible.return_value=True;heading.inner_text.return_value='New logged-in person';page.get_by_role.return_value.all.return_value=[heading]
        marker=hashlib.sha256(b'personal:99017').hexdigest()
        def identity(page,entry):return dict(target_url=entry['url'],name=entry['name'],method='personal_actor_id_match',session_marker=marker)
        with patch('playwright.sync_api.sync_playwright'),patch.object(app,'close_selected_window'),patch.object(app.normal,'launch_normal',return_value=context),patch.object(app.upload,'navigate_profile'),patch.object(app.upload,'checkpoint'),patch.object(app.upload,'require_no_advanced_protection'),patch.object(app.upload,'ensure_personal_identity',side_effect=identity) as prove:
            entry,proof=app.discover_personal('fb17')
        self.assertEqual(entry['url'],'https://www.facebook.com/profile.php?id=99017');self.assertEqual(entry['name'],'New logged-in person');self.assertEqual(proof['session_marker'],marker);prove.assert_called_once();context.close.assert_called_once()


if __name__=='__main__':unittest.main()
