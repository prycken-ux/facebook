import copy,os,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import fb_upload as upload
import scheduled_material_batch as batch
import publication_preferences as prefs
import test_scheduled_material_batch as fixtures


class PublicationPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ScheduledMaterialTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        entry=dict(account='fb17',target='personal',type='personal',workflow='personal_recording_v1',name='Darlene Lake',url='https://www.facebook.com/profile.php?id=1017',enabled=False)
        self.f.entries.append(entry);video=upload.inbox_for(entry)/'skipped.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'never publish fb17');video.with_suffix('.txt').write_text('keep fb17 caption');self.fb17=video
        upload.save_json(upload.CONFIG,dict(targets=self.f.entries));self.config=upload.CONFIG.read_bytes()
        self.now=datetime(2026,11,6,8,tzinfo=timezone.utc)
    def test_persistent_policy_overrides_only_new_captions_and_skips_all_four(self):
        state={'known':dict(account='fb99',status='published',comment_status='sent')};upload.save_json(self.f.state_path,state)
        policy=prefs.save_authorized();path,value=batch.freeze('2026-11-06','17:00',True,self.f.comment,self.now,report_format='text',exclude_previous_plans=True)
        self.assertEqual(value['payload']['start'],'2026-11-06T17:00:00+08:00')
        self.assertEqual(value['payload']['publication_preferences_sha256'],policy['sha256'])
        self.assertEqual(set(value['payload']['excluded_accounts']),{'fb16','fb17','fb18','fb21'})
        self.assertTrue(all(j['caption_text']==prefs.CAPTION for j in value['payload']['jobs']))
        self.assertEqual(self.fb17.with_suffix('.txt').read_text(),'keep fb17 caption')
        for pair in [('fb16','personal'),('fb18','personal'),('fb21','personal')]:self.assertFalse(self.f.videos[pair].with_suffix('.txt').exists())
        self.assertEqual(upload.read_json(self.f.state_path,{}),state);self.assertEqual(upload.CONFIG.read_bytes(),self.config)
        self.assertTrue(any(p.read_bytes()==self.f.custom for p in (self.f.root/'backups').rglob('today.txt')))
        self.assertEqual((self.f.root/'common_caption_today.txt').read_text().strip(),prefs.CAPTION)
        self.assertNotIn('**',prefs.CAPTION);self.assertNotIn('\\',prefs.CAPTION)
    def test_published_unknown_and_old_plan_sources_are_not_rewritten(self):
        old=self.f.videos[('fb23','personal')];entry=next(e for e in self.f.entries if e['account']=='fb23');key=upload.job_key(entry,old)
        upload.save_json(self.f.state_path,{key:dict(status='needs_review',account='fb23',target='personal')})
        prefs.save_authorized();_,value=batch.freeze('2026-11-06','17:00',True,self.f.comment,self.now,report_format='text',exclude_previous_plans=True)
        self.assertEqual(old.with_suffix('.txt').read_bytes(),self.f.custom);self.assertNotIn(key,{j['key'] for j in value['payload']['jobs']})
    def test_historical_source_validation_keeps_previous_three_exclusions(self):
        prefs.save_authorized();self.assertIsNone(prefs.load('2026-11-05'))
        self.assertEqual(batch.excluded_accounts('2026-11-05'),{'fb16','fb18','fb21'})
        self.assertTrue(batch.eligible(self.f.entries[-1],True,date='2026-11-05'))
        self.assertFalse(batch.eligible(self.f.entries[-1],True,date='2026-11-06'))
    def test_future_date_inherits_policy_and_tampering_blocks(self):
        prefs.save_authorized();self.assertEqual(prefs.load('2026-11-07')['payload']['caption'],prefs.CAPTION)
        path=self.f.root/'publication_preferences.json';value=upload.read_json(path,{});value['payload']['caption']='changed without checksum';upload.save_json(path,value)
        with self.assertRaises(ValueError):batch.freeze('2026-11-06','17:00',True,self.f.comment,self.now)
    def test_unreadable_old_new_video_caption_is_backed_up_before_exact_replacement(self):
        file=self.f.videos[('fb01','page01')].with_suffix('.txt');file.write_bytes(b'\xff\xfeold non-utf8')
        prefs.save_authorized();batch.freeze('2026-11-06','17:00',True,self.f.comment,self.now)
        self.assertEqual(file.read_text().strip(),prefs.CAPTION)
        self.assertTrue(any(p.read_bytes()==b'\xff\xfeold non-utf8' for p in (self.f.root/'backups').rglob('today.txt')))
