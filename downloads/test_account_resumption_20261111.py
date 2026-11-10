import copy,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import publication_preferences as preferences
import scheduled_material_batch as batch
import publish_priority_batch as priority
import automatic_batch_retry as retry
import fb_upload as upload
import test_scheduled_material_batch as fixtures


class AccountResumptionTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ScheduledMaterialTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        row=dict(account='fb17',target='personal',type='personal',workflow='personal_recording_v1',name='Recovered Person',url='https://www.facebook.com/profile.php?id=1017',enabled=False)
        self.f.entries.append(row);video=upload.inbox_for(row)/'held.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'held personal video');video.with_suffix('.txt').write_text('keep until tomorrow')
        self.f.videos[('fb17','personal')]=video;upload.save_json(upload.CONFIG,dict(targets=self.f.entries));self.config=upload.CONFIG.read_bytes()
        self.old=preferences.save_authorized();self.old_hash=self.old['sha256']
    def freeze(self,date):
        now=datetime.fromisoformat(date+'T08:00:00+00:00')
        return batch.freeze(date,'17:00',True,priority.daily.COMMENT,now,report_format='text',exclude_previous_plans=False)
    def test_today_skip_tomorrow_resume_has_exact_boundary_and_keeps_old_fingerprints(self):
        path,old=self.freeze('2026-11-09');old.update(workflow='future-video-comments-v1',auto_retry_policy=retry.POLICY,comment_timing=priority.TIMING,priority_workflow=priority.PRIORITY_WORKFLOW_VERSION)
        preferences.save_authorized(resume_from='2026-11-11')
        self.assertEqual(preferences.load('2026-11-09')['sha256'],self.old_hash);priority.validate(path,old,'2026-11-09')
        self.assertEqual(batch.excluded_accounts('2026-11-10'),{'fb16','fb17','fb18','fb21'})
        self.assertEqual(batch.excluded_accounts('2026-11-11'),set())
        for row in self.f.entries:
            if row['account'] in preferences.EXCLUDED:
                self.assertFalse(batch.eligible(row,True,date='2026-11-10'));self.assertTrue(batch.eligible(row,True,date='2026-11-11'))
        self.assertEqual(upload.CONFIG.read_bytes(),self.config)
        with patch.object(batch,'datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,11,10,8,tzinfo=timezone.utc)
            self.assertEqual(batch.excluded_accounts(),set(preferences.EXCLUDED))
            clock.now.return_value=datetime(2026,11,11,8,tzinfo=timezone.utc)
            self.assertEqual(batch.excluded_accounts(),set())
    def test_held_four_account_media_and_captions_are_untouched_today_then_eligible_tomorrow(self):
        preferences.save_authorized(resume_from='2026-11-11');video=self.f.videos[('fb17','personal')];before=video.with_suffix('.txt').read_bytes()
        _,today=self.freeze('2026-11-10');self.assertFalse({j['account'] for j in today['payload']['jobs']}&set(preferences.EXCLUDED));self.assertEqual(video.with_suffix('.txt').read_bytes(),before)
        path,tomorrow=self.freeze('2026-11-11');self.assertTrue(set(preferences.EXCLUDED).issubset({j['account'] for j in tomorrow['payload']['jobs']}))
        self.assertEqual(tomorrow['payload']['excluded_accounts'],[]);self.assertTrue(all(j['caption_text']==preferences.CAPTION for j in tomorrow['payload']['jobs']))
        tomorrow.update(workflow='future-video-comments-v1',auto_retry_policy=retry.POLICY,comment_timing=priority.TIMING,priority_workflow=priority.PRIORITY_WORKFLOW_VERSION)
        priority.validate(path,tomorrow,'2026-11-11')
        upload.save_json(path,tomorrow)
        with patch.object(retry,'datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,11,11,8,tzinfo=timezone.utc)
            self.assertEqual(retry.load_source(path)[0],path)
    def test_later_generic_preference_save_does_not_reexclude_restored_accounts(self):
        preferences.save_authorized(resume_from='2026-11-11');before=(self.f.root/'publication_preferences.json').read_bytes();active=preferences.load('2026-11-11')
        self.assertNotEqual(active['sha256'],self.old_hash)
        preferences.save_authorized();self.assertEqual((self.f.root/'publication_preferences.json').read_bytes(),before)
        self.assertEqual(preferences.load('2026-11-11'),active);self.assertEqual(batch.excluded_accounts('2026-11-12'),set())
    def test_tampered_date_or_unrelated_account_cannot_be_resumed(self):
        preferences.save_authorized(resume_from='2026-11-11');path=self.f.root/'publication_preferences.json';original=path.read_bytes()
        value=upload.read_json(path,{});value['account_resumption']['payload']['effective_from']='2026-11-10';upload.save_json(path,value)
        with self.assertRaises(ValueError):preferences.load('2026-11-10')
        path.write_bytes(original);value=upload.read_json(path,{});value['account_resumption']['payload']['accounts']=['fb99'];value['account_resumption']['sha256']=preferences.digest(value['account_resumption']['payload']);upload.save_json(path,value)
        with self.assertRaises(ValueError):preferences.load('2026-11-11')
        path.write_bytes(original)
        with self.assertRaises(ValueError):preferences.save_authorized(resume_from='2026-11-05')
        self.assertEqual(path.read_bytes(),original)
