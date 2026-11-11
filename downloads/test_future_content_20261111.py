import copy
import unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch

import fb_upload as upload
import publication_preferences as prefs
import scheduled_material_batch as batch
import publish_priority_batch as priority
import daily_publish_and_comments as daily
import automatic_batch_retry as retry
import test_scheduled_material_batch as fixtures


class FutureContentTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ScheduledMaterialTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        prefs.save_authorized(resume_from='2026-11-11')
        self.base=prefs.load('2026-11-11');self.config=upload.CONFIG.read_bytes()

    def prepare(self,date='2026-11-11'):
        with patch.object(priority,'datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime.fromisoformat(date+'T08:00:00+00:00')
            return priority.prepare(date)

    def test_exact_new_copy_and_comment_are_saved_without_changing_account_rules(self):
        item=prefs.save_content_authorized()
        self.assertTrue(item['payload']['caption'].startswith('Everyday moments can offer a new perspective.\nWhat stood out'))
        self.assertTrue(item['payload']['caption'].endswith('#EverydayMoments #NewPerspectives #Prycken'))
        self.assertEqual(item['payload']['comment'],daily.COMMENT+'\nShop on Shopfy https://prycken.com/')
        self.assertEqual(item['sha256'],prefs.digest(item['payload']))
        self.assertIsNone(prefs.content_policy('2026-11-10'));self.assertEqual(prefs.content_policy('2026-11-11'),item)
        self.assertEqual(prefs.load('2026-11-11'),self.base)
        self.assertEqual(batch.excluded_accounts('2026-11-10'),set(prefs.EXCLUDED));self.assertEqual(batch.excluded_accounts('2026-11-11'),set())
        self.assertEqual(upload.CONFIG.read_bytes(),self.config)

    def test_new_frozen_jobs_bind_both_texts_and_retry_retains_the_version(self):
        item=prefs.save_content_authorized();path,value=self.prepare();payload=value['payload']
        self.assertEqual(payload['comment_text'],prefs.EVERYDAY_COMMENT)
        self.assertEqual(payload['publication_content_sha256'],item['sha256'])
        self.assertTrue(all(j['caption_text']==prefs.EVERYDAY_CAPTION and j['publication_content_sha256']==item['sha256'] for j in payload['jobs']))
        priority.validate(path,value,'2026-11-11')
        for job in payload['jobs']:batch.validate_job(job,date='2026-11-11')
        with patch.object(retry,'datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,11,11,8,tzinfo=timezone.utc)
            self.assertEqual(retry.load_source(path)[1],value)

    def test_existing_same_day_frozen_batch_keeps_old_copy_comment_and_pointer(self):
        path,old=self.prepare();before=path.read_bytes();pointer=path.parent/'priority-batch-2026-11-11.json';pointer_before=pointer.read_bytes()
        captions={upload.ROOT/'videos'/j['account']/j['target']/'inbox'/j['filename']:j['caption_text'] for j in old['payload']['jobs']}
        prefs.save_content_authorized()
        same,value=self.prepare();self.assertEqual(same,path);self.assertEqual(value,old)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(pointer.read_bytes(),pointer_before)
        priority.validate(path,old,'2026-11-11')
        for job in old['payload']['jobs']:batch.validate_job(job,date='2026-11-11')
        self.assertEqual(old['payload']['comment_text'],daily.COMMENT)
        for video,text in captions.items():self.assertEqual(video.with_suffix('.txt').read_text().strip(),text)

    def test_old_attempted_and_old_frozen_sidecars_are_not_rewritten(self):
        path,old=self.prepare('2026-11-10');before=path.read_bytes()
        state={old['payload']['jobs'][0]['key']:dict(status='needs_review',comment_status='sending')};upload.save_json(self.f.state_path,state)
        captions={v.with_suffix('.txt'):v.with_suffix('.txt').read_bytes() for v in self.f.videos.values() if v.with_suffix('.txt').is_file()}
        prefs.save_content_authorized();fresh=self.f.videos[('fb01','page01')].parent/'fresh.mp4';fresh.write_bytes(b'new future bytes')
        _,value=self.prepare();self.assertIn('fresh.mp4',[j['filename'] for j in value['payload']['jobs']])
        self.assertFalse({j['key'] for j in value['payload']['jobs']}&{j['key'] for j in old['payload']['jobs']})
        self.assertEqual(path.read_bytes(),before);self.assertEqual(upload.read_json(self.f.state_path,{}),state)
        for path,data in captions.items():self.assertEqual(path.read_bytes(),data)

    def test_default_save_preserves_revision_and_repeated_update_is_idempotent(self):
        prefs.save_content_authorized();path=upload.ROOT/'publication_preferences.json';before=path.read_bytes();common=(upload.ROOT/'common_caption_today.txt').read_bytes();backups=list((upload.ROOT/'backups').iterdir())
        prefs.save_content_authorized();prefs.save_authorized()
        self.assertEqual(path.read_bytes(),before);self.assertEqual((upload.ROOT/'common_caption_today.txt').read_bytes(),common)
        self.assertEqual(list((upload.ROOT/'backups').iterdir()),backups)

    def test_tampered_revision_or_manifest_comment_stops_before_sending(self):
        prefs.save_content_authorized();path,value=self.prepare()
        bad=copy.deepcopy(value);bad['payload']['comment_text']='Changed comment'
        with self.assertRaises(ValueError):batch.content_for_payload(bad['payload'])
        bad=copy.deepcopy(value);bad['payload']['jobs'][0].pop('publication_content_sha256')
        with self.assertRaises(ValueError):batch.content_for_payload(bad['payload'])
        settings=upload.ROOT/'publication_preferences.json';stored=upload.read_json(settings,{});stored['content_updates'][0]['payload']['comment']='Changed without checksum';upload.save_json(settings,stored)
        with self.assertRaises(ValueError):batch.content_for_payload(value['payload'])

    def test_failed_content_write_restores_exact_prior_preferences_and_common_caption(self):
        path=upload.ROOT/'publication_preferences.json';common=upload.ROOT/'common_caption_today.txt';before=path.read_bytes();common_before=common.read_bytes()
        with patch.object(upload,'save_json',side_effect=OSError('write failed')):
            with self.assertRaises(OSError):prefs.save_content_authorized()
        self.assertEqual(path.read_bytes(),before);self.assertEqual(common.read_bytes(),common_before)

    def test_comment_sender_and_reload_verifier_use_exact_frozen_new_comment(self):
        prefs.save_content_authorized();_,value=self.prepare();job=value['payload']['jobs'][0]
        state={job['key']:dict(account=job['account'],target=job['target'],url=job['url'],video=str(upload.ROOT/'videos'/job['account']/job['target']/'inbox'/job['filename']),status='published',created='2026-11-11T08:00:00+00:00',published_at='2026-11-11T08:01:00+00:00',permalink='https://www.facebook.com/reel/9001',comment_link_job_key=job['key'])}
        upload.save_json(self.f.state_path,state);browser=MagicMock();browser.pages=[MagicMock()]
        with patch('playwright.sync_api.sync_playwright'),patch.object(upload,'launch_context',return_value=browser),patch.object(upload,'ensure_identity',return_value={}),patch.object(daily,'close_selected_window'),patch.object(daily.comments,'after_publication',return_value={'status':'verifying','permalink':'https://www.facebook.com/reel/9001'}) as send,patch.object(daily.comments,'verify_after_reload',return_value={'status':'sent'}) as verify:
            rows=daily.backfill(value,None,only_keys={job['key']},future_only=True)
        self.assertEqual(rows[0]['status'],'sent');self.assertEqual(send.call_args.args[6],prefs.EVERYDAY_COMMENT);self.assertEqual(verify.call_args.args[4],prefs.EVERYDAY_COMMENT)
        with patch.object(daily,'close_selected_window') as close:
            rows=daily.backfill(value,None,only_keys={job['key']},future_only=True)
        close.assert_not_called();self.assertEqual(rows[0]['status'],'sent')

    def test_new_comment_intent_ledger_prevents_duplicate_send(self):
        prefs.save_content_authorized();_,value=self.prepare();job=value['payload']['jobs'][0]
        record=dict(account=job['account'],target=job['target'],url=job['url'],video=str(upload.ROOT/'videos'/job['account']/job['target']/'inbox'/job['filename']),status='published',created='2026-11-11T08:00:00+00:00')
        upload.save_json(self.f.state_path,{job['key']:record})
        key=daily.comments.hashlib.sha256((job['key']+'\0'+daily.comments.text_hash(prefs.EVERYDAY_COMMENT)).encode()).hexdigest()
        upload.save_json(upload.ROOT/'logs/video_comments.json',{key:dict(status='sending')})
        with patch.object(daily,'close_selected_window') as close:
            rows=daily.backfill(value,None,only_keys={job['key']},future_only=True)
        close.assert_not_called();self.assertEqual(rows[0]['status'],'sending')


if __name__=='__main__':unittest.main()
