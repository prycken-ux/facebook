import copy
import unittest
from unittest.mock import MagicMock,patch
import pending_video_comment_lookup_20261119 as pending
from test_publish_eligible60_materials_20261119 import Eligible60PublicationTests


class PendingLookupTests(unittest.TestCase):
    def setUp(self):
        self.f=Eligible60PublicationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.app=__import__('publish_eligible60_materials_20261119');self.first=self.app.first;self.root=self.f.root
        self.f.core(unknown=True)
        self.req=self.first.upload.read_json(self.root/self.app.REQUEST,{})
        control=self.first.upload.read_json(self.root/'logs'/('eligible60-real-publication-'+self.req['sha256'][:16]+'.json'),{})
        self.wave=control['waves'][0];self.control=control
        self.path=self.root/'logs'/self.wave['manifest'];self.value=self.first.archive.checked_json(self.path)
        self.job=self.value['payload']['jobs'][0]
        self.state_path=self.root/'logs/publish_state.json'
        self.before=copy.deepcopy(self.first.upload.read_json(self.state_path,{}))
        self.context=MagicMock();self.context.pages=[MagicMock()]
        self.link='https://www.facebook.com/reel/9988776655'

    def locate(self,found=True,allowed=True,seen=None,through_backfill=False):
        _,source,journal,material=self.app.allocation(self.root)
        def finder(*args,**kwargs):
            if not found:raise ValueError('No unique video match')
            self.assertEqual(args[3],self.app.content_today.CAPTION)
            return self.link,'verified_owner_caption_time'
        with patch.object(self.first.batch,'excluded_accounts',side_effect=self.app.exclusions), \
             patch.object(self.app.owned,'reservation',side_effect=self.app.active_reservation), \
             self.app.wave_context(self.req,source,journal,material,self.wave,self.control), \
             patch.object(self.first.upload,'launch_context',return_value=self.context) as launch, \
             patch.object(self.first.upload,'ensure_identity',return_value={}), \
             patch.object(self.first,'close_selected_window'), \
             patch.object(self.first.priority.actual,'inspect_video',return_value=(False,{})), \
             patch.object(self.first.priority.actual,'make_finder',return_value=finder) as factory, \
             patch.object(self.first.upload,'run_entry',side_effect=AssertionError('Comment lookup cannot upload')):
            if through_backfill:
                def native(value,*args,**kwargs):
                    row=self.first.upload.read_json(self.state_path,{})[self.job['key']]
                    self.assertEqual(row['status'],'published')
                    self.assertEqual(row['comment_link_job_key'],self.job['key'])
                    self.assertEqual(value['payload']['comment_text'],self.app.content_today.COMMENT)
                    return ['comment-gate-reached']
                with patch.object(self.first.priority.daily,'backfill',side_effect=native),pending.installed(self.first,self.app.queued.validate_run_manifest,lambda job:allowed):
                    result=self.first.priority.daily.backfill(self.value,None,only_keys={self.job['key']},future_only=True)
                self.assertEqual(result,['comment-gate-reached'])
            else:
                pending.resolve(self.first,self.value,{self.job['key']},self.app.queued.validate_run_manifest,
                                lambda job:allowed,set() if seen is None else seen)
        return launch,factory

    def test_exact_video_promoted_and_bound_for_comment_without_touching_other_jobs(self):
        self.locate()
        state=self.first.upload.read_json(self.state_path,{})
        row=state[self.job['key']]
        self.assertEqual(row['status'],'published',row.get('comment_error'));self.assertEqual(row['permalink'],self.link)
        self.assertEqual(row['comment_link_job_key'],self.job['key'])
        self.assertEqual(row['comment_status'],'deferred')
        self.assertEqual(row['video_status_before_comment_lookup'],'needs_review')
        for key,before in self.before.items():
            if key!=self.job['key']:self.assertEqual(state[key],before)

    def test_failed_lookup_remains_pending_and_no_comment_or_upload(self):
        self.locate(found=False)
        row=self.first.upload.read_json(self.state_path,{})[self.job['key']]
        self.assertEqual(row['status'],'needs_review');self.assertEqual(row['comment_status'],'lookup_pending')
        self.assertNotEqual(row.get('permalink'),self.link)

    def test_installed_backfill_resolves_pending_before_the_comment_gate(self):
        self.locate(through_backfill=True)

    def test_paused_target_never_opens_a_browser(self):
        launch,factory=self.locate(allowed=False)
        launch.assert_not_called();factory.assert_not_called()
        self.assertEqual(self.first.upload.read_json(self.state_path,{}),self.before)

    def test_changed_source_binding_rejected_before_browser(self):
        state=copy.deepcopy(self.before);state[self.job['key']]['source_frozen_sha256']='a'*64
        self.first.upload.save_json(self.state_path,state)
        launch,_=self.locate();launch.assert_not_called()
        row=self.first.upload.read_json(self.state_path,{})[self.job['key']]
        self.assertEqual(row['status'],'needs_review')

    def test_existing_uncertain_comment_is_only_verified_after_video_resolution(self):
        state=copy.deepcopy(self.before);state[self.job['key']]['comment_status']='needs_review'
        self.first.upload.save_json(self.state_path,state);self.locate()
        state=self.first.upload.read_json(self.state_path,{})
        self.assertEqual(state[self.job['key']]['comment_status'],'needs_review')
        candidates,_=self.first.priority.comment_retry.candidates(self.value,state,{},dict(jobs={}))
        self.assertEqual([(j['key'],mode) for j,key,mode in candidates],[(self.job['key'],'verify_only')])

    def test_unique_explicit_published_metadata_needs_no_browser_or_local_media(self):
        state=copy.deepcopy(self.before)
        state[self.job['key']].update(fresh_publication_candidate=self.link,
             fresh_publication_job_key=self.job['key'],fresh_publication_candidate_count=1,
             fresh_publication_explicit_published=True)
        self.first.upload.save_json(self.state_path,state)
        (self.root/'videos'/self.job['account']/self.job['target']/'inbox'/self.job['filename']).unlink()
        launch,factory=self.locate();launch.assert_not_called();factory.assert_not_called()
        row=self.first.upload.read_json(self.state_path,{})[self.job['key']]
        self.assertEqual(row['status'],'published');self.assertEqual(row['permalink'],self.link)

    def test_lookup_is_bounded_once_per_same_submission_and_resumes_later(self):
        seen=set();self.locate(found=False,seen=seen)
        launch,factory=self.locate(found=False,seen=seen)
        launch.assert_not_called();factory.assert_not_called()
        self.locate(found=True,seen=set())
        self.assertEqual(self.first.upload.read_json(self.state_path,{})[self.job['key']]['status'],'published')


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.f=Eligible60PublicationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.app=__import__('publish_eligible60_materials_20261119');self.root=self.f.root

    def test_exact_corrected_links_historical_revisions_and_idempotent_backup(self):
        content=self.app.content_today;prefs=self.app.first.batch.preferences
        old=prefs.content_policy('2026-11-18');policy=prefs.load('2026-11-18')
        value=content.save_authorized(self.root)
        self.assertEqual(prefs.content_policy('2026-11-18'),old)
        self.assertEqual(prefs.load('2026-11-18'),policy)
        self.assertEqual(value['payload']['caption'],content.CAPTION)
        self.assertIn('/gp/product/B0GYJ55PH6?',content.COMMENT)
        self.assertIn('maas_adg_B2F4D52E550EDAC7E6A92C0290F501F6',content.COMMENT)
        self.assertIn('maas_adg_2C08551FB464224E2CDB58F74A72570A',content.CAPTION)
        self.assertNotIn('B0GYCWL9HS',content.COMMENT)
        self.assertNotIn('\\',content.CAPTION+content.COMMENT)
        before=(self.root/'publication_preferences.json').read_bytes()
        backups=list((self.root/'backups').glob('publication-content-nov19-*'))
        content.save_authorized(self.root)
        self.assertEqual((self.root/'publication_preferences.json').read_bytes(),before)
        self.assertEqual(list((self.root/'backups').glob('publication-content-nov19-*')),backups)


if __name__=='__main__':unittest.main()
