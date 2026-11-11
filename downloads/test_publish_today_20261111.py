import copy
import unittest
from datetime import datetime,timezone
from unittest.mock import patch

import publish_today_20261111 as today
import fb_upload as upload
import test_scheduled_material_batch as fixtures


class Nov11DirectTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ScheduledMaterialTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        # Build the established 33 targets, ten new fb09 Pages, and fresh fb24.
        self.entries=[]
        for number in range(1,25):
            account=f'fb{number:02d}';target='page01' if number in (1,2,5,6,12,13) else 'personal'
            row=dict(account=account,target=target,type='page' if target=='page01' else 'personal',name='Owner '+account,url='https://www.facebook.com/profile.php?id='+str(10000+number),enabled=False)
            if target=='personal':row['workflow']='personal_recording_v1'
            self.entries.append(row);(self.f.root/'profiles'/account).mkdir(parents=True,exist_ok=True)
        for number in range(1,11):self.entries.append(dict(account='fb10',target=f'page{number:02d}',type='page',name='fb10 page '+str(number),url='https://www.facebook.com/profile.php?id='+str(20000+number),enabled=False))
        config,added=today.fb09.plan(dict(custom={'keep':True},targets=self.entries));self.entries=config['targets'];upload.save_json(upload.CONFIG,config)
        self.config=upload.CONFIG.read_bytes();self.assertEqual(len(self.entries),44)
        mapping=next(e for e in self.entries if e['account']=='fb24')
        batch_id='personal-20261110-one-fb24'
        self.registry=dict(schema='additional-personal-logins-v1',slots=dict(fb24=dict(state='registered',publishing_ready=True,identity_verified_at='2026-11-10T09:00:00+00:00',batch_id=batch_id,mapping=mapping)),batches={batch_id:dict(accounts=['fb24'],count=1)})
        upload.save_json(self.f.root/'additional_personal_accounts.json',self.registry);self.registry_bytes=(self.f.root/'additional_personal_accounts.json').read_bytes()
        # Remove the earlier fixture's unrelated sample media.
        for path in (self.f.root/'videos').rglob('*'):
            if path.is_file():path.unlink()
        old_entry=self.entries[0];self.old=upload.inbox_for(old_entry)/'nov10-old.mp4';self.old.parent.mkdir(parents=True,exist_ok=True);self.old.write_bytes(b'old pending bytes');self.old.with_suffix('.txt').write_text('Original Nov10 caption')
        today.preferences.save_authorized(resume_from='2026-11-11')
        self.old_path,_=today.batch.freeze('2026-11-10','17:00',True,today.priority.daily.COMMENT,datetime(2026,11,10,8,tzinfo=timezone.utc),report_format='text')
        self.old_caption=self.old.with_suffix('.txt').read_bytes();self.old_manifest=self.old_path.read_bytes();key=upload.job_key(old_entry,self.old)
        self.history={key:dict(status='needs_review',comment_status='needs_review',account='fb01',target='page01',post_intent_at='2026-11-10T17:00:00+08:00')};upload.save_json(self.f.state_path,self.history)
        self.claim_path=self.f.root/'logs/automatic_comment_retry_claims.json';upload.save_json(self.claim_path,dict(schema='automatic-comment-retry-claims-v1',jobs={'old':dict(mode='verify_only')}));self.claim_before=self.claim_path.read_bytes()
        for row in self.entries:
            video=upload.inbox_for(row)/'nov11.mp4';video.parent.mkdir(parents=True,exist_ok=True);video.write_bytes((row['account']+'/'+row['target']).encode());video.with_suffix('.txt').write_text('Replace generic caption')
        for module in (today,today.priority):
            clock=self.f.stack.enter_context(patch.object(module,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,11,8,tzinfo=timezone.utc)
        self.f.stack.enter_context(patch.object(today.workflow,'register',side_effect=AssertionError('no scheduler')))
        self.f.stack.enter_context(patch.object(today.workflow.previous,'execute',side_effect=AssertionError('do not confirm old videos')))

    def preserved(self):
        self.assertEqual(upload.CONFIG.read_bytes(),self.config);self.assertEqual((self.f.root/'additional_personal_accounts.json').read_bytes(),self.registry_bytes)
        self.assertEqual(upload.read_json(self.f.state_path,{}),self.history);self.assertEqual(self.claim_path.read_bytes(),self.claim_before)
        self.assertEqual(self.old_path.read_bytes(),self.old_manifest);self.assertEqual(self.old.with_suffix('.txt').read_bytes(),self.old_caption)

    def test_all_44_targets_include_restored_four_new_fb24_and_ten_fb09_pages(self):
        def run(path):
            value=upload.read_json(path,{});payload=value['payload'];jobs=payload['jobs']
            self.assertEqual(len(jobs),44);self.assertEqual(payload['date'],'2026-11-11');self.assertEqual(payload['excluded_accounts'],[])
            self.assertEqual(payload['comment_text'],today.preferences.EVERYDAY_COMMENT);self.assertEqual(payload['comment_retry_policy'],today.COMMENT_RETRY_VERSION)
            self.assertTrue(all(j['caption_text']==today.preferences.EVERYDAY_CAPTION and j['filename']=='nov11.mp4' for j in jobs))
            self.assertEqual({j['target'] for j in jobs if j['account']=='fb09'},{'personal'}|{f'page{n:02d}' for n in range(1,11)})
            self.assertTrue(today.RESTORED|{'fb24'}<={j['account'] for j in jobs})
            today.workflow.validate(path,value);return 3
        with patch.object(today.workflow,'run',side_effect=run):self.assertEqual(today.execute(True),3)
        self.preserved()

    def test_rerun_resumes_original_today_source_without_adding_later_material(self):
        with patch.object(today.workflow,'run',return_value=3) as run:
            today.execute(True);path=run.call_args.args[0];before=path.read_bytes()
            (upload.inbox_for(self.entries[0])/'later.mp4').write_bytes(b'late material')
            today.execute(True);self.assertEqual(run.call_args.args[0],path);self.assertEqual(path.read_bytes(),before)
        self.preserved()

    def test_unverified_fb24_is_not_silently_skipped_or_forged(self):
        registry=copy.deepcopy(self.registry);registry['slots']['fb24']['publishing_ready']=False;upload.save_json(self.f.root/'additional_personal_accounts.json',registry)
        with patch.object(today.workflow,'run') as run:
            with self.assertRaisesRegex(ValueError,'fb24'):today.execute(True)
        run.assert_not_called();self.assertFalse((self.f.root/'logs/priority-batch-2026-11-11.json').exists())

    def test_fb09_mapping_collision_stops_before_freezing_new_source(self):
        config=upload.read_json(upload.CONFIG,{});row=next(e for e in config['targets'] if (e['account'],e['target'])==('fb09','page10'));row['url']='https://www.facebook.com/profile.php?id=99999';upload.save_json(upload.CONFIG,config)
        with self.assertRaisesRegex(ValueError,'未覆盖'):today.execute(True)
        self.assertFalse((self.f.root/'logs/priority-batch-2026-11-11.json').exists())

    def test_other_reserved_account_is_preserved_but_not_in_todays_scope(self):
        extra=dict(account='fb27',target='personal',type='personal',workflow='personal_recording_v1',name='Other registration',url='https://www.facebook.com/profile.php?id=10027',enabled=False)
        config=upload.read_json(upload.CONFIG,{});config['targets'].append(extra);upload.save_json(upload.CONFIG,config)
        registry=copy.deepcopy(self.registry);registry['slots']['fb27']=dict(state='registered',publishing_ready=True,identity_verified_at='verified',mapping=extra);upload.save_json(self.f.root/'additional_personal_accounts.json',registry)
        video=upload.inbox_for(extra)/'other.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'unrelated account material');video.with_suffix('.txt').write_text('Keep other caption')
        with patch.object(today.workflow,'run',return_value=3) as run:today.execute(True)
        value=upload.read_json(run.call_args.args[0],{});self.assertNotIn('fb27',{j['account'] for j in value['payload']['jobs']});self.assertEqual(video.with_suffix('.txt').read_text(),'Keep other caption')
        self.assertTrue(today.batch.eligible(extra,True,date=today.DATE))

    def test_existing_old_copy_batch_is_not_replaced_or_rewritten(self):
        path,value=today.priority.prepare(today.DATE);before=path.read_bytes()
        with patch.object(today.workflow,'run') as run:
            with self.assertRaisesRegex(ValueError,'已有其他文案'):today.execute(True)
        run.assert_not_called();self.assertEqual(path.read_bytes(),before)

    def test_real_footage_date_and_active_lock_are_required(self):
        with self.assertRaises(ValueError):today.execute(False)
        today.datetime.now.return_value=datetime(2026,11,12,8,tzinfo=timezone.utc)
        with self.assertRaises(ValueError):today.execute(True)
        today.datetime.now.return_value=datetime(2026,11,11,8,tzinfo=timezone.utc)
        lock=self.f.root/'logs/upload.lock';lock.write_bytes(b'active')
        with self.assertRaises(RuntimeError):today.execute(True)
        self.assertEqual(lock.read_bytes(),b'active');self.preserved()

    def test_windows_root_argument_entry_logs_without_starting_historical_jobs(self):
        with patch.object(today.sys,'platform','win32'),patch.object(today,'recover_locks') as recover,patch.object(today,'execute',return_value=3) as execute:
            self.assertEqual(today.start(self.f.root,True),3)
        recover.assert_called_once_with(self.f.root);execute.assert_called_once_with(True)
        self.assertTrue((self.f.root/'logs/direct-priority-2026-11-11.log').is_file())


if __name__=='__main__':unittest.main()
