import contextlib,copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import MagicMock
import nov25_publication_policy as policy

class ReceiptPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'state.json'
        self.entry=dict(account='fb04',target='personal',url='owner')
        self.row=dict(self.entry,status='needs_review',video='C:\\videos\\20261125-test.mp4',post_intent_at='stamp',review_reason='publication_receipt_timeout',failure_stage='wait_success_receipt',error='native timeout')
        class ReceiptNeedsReview(RuntimeError):pass
        self.upload=N(ReceiptNeedsReview=ReceiptNeedsReview,read_json=lambda p,d:json.loads(p.read_text()),save_json=lambda p,v:p.write_text(json.dumps(v)),target_key=lambda u:u)
    def run_policy(self,row=None,error=None,filename='20261125-test.mp4'):
        self.path.write_text(json.dumps({'key':self.row if row is None else row,'unrelated':{'status':'needs_review'}}));state=json.loads(self.path.read_text())
        native=MagicMock(side_effect=error or self.upload.ReceiptNeedsReview('native failure'))
        result=policy.wrap_upload(self.upload,native)(self.entry,state,self.path,True,filename=filename,expected_job_key='key')
        self.assertEqual(native.call_count,1);self.assertEqual(state['key'],json.loads(self.path.read_text())['key']);return result,json.loads(self.path.read_text())
    def test_only_returned_post_click_with_native_receipt_timeout_is_assumed(self):
        result,state=self.run_policy();row=state['key'];self.assertTrue(result);self.assertEqual(row['status'],'published');self.assertIs(row['assumed_published'],True)
        self.assertEqual(row['error'],'native timeout');self.assertEqual(row['video_status_before_policy'],'needs_review');self.assertEqual(row['comment_status'],'deferred')
        for field in ['confirmed_at','confirmation_method','success_message','permalink','archived_video']:self.assertNotIn(field,row)
        self.assertEqual(state['unrelated'],{'status':'needs_review'})
    def test_click_timeout_or_intent_only_or_old_day_cannot_be_assumed(self):
        for change in [dict(failure_stage='post_click'),dict(review_reason='other'),dict(post_intent_at=''),dict(status='failed_before_post'),dict(account='fb03')]:
            with self.subTest(change=change),self.assertRaises(self.upload.ReceiptNeedsReview):self.run_policy(dict(self.row,**change))
        with self.assertRaises(self.upload.ReceiptNeedsReview):self.run_policy(filename='20261124-test.mp4')
        with self.assertRaisesRegex(RuntimeError,'network'):self.run_policy(error=RuntimeError('network'))

class FinderTests(unittest.TestCase):
    def setUp(self):
        self.link='https://www.facebook.com/reel/123456789012345';self.entry=dict(account='fb04',target='personal',url='owner',name='actor')
        self.page=MagicMock();self.page.url=self.link;self.page.get_by_role.return_value.count.return_value=0
        self.actual=N(require_target_author=MagicMock());self.lookup=N(find_published=MagicMock(return_value=(self.link,'verified_owner_caption_time')))
        self.upload=N(english_url=lambda x:x,checkpoint=MagicMock(),require_no_advanced_protection=MagicMock(),ensure_identity=MagicMock(),save_json=MagicMock())
        self.comments=N(direct_link=lambda x:x if str(x).startswith('https://www.facebook.com/reel/') else None)
        self.fallback=MagicMock(return_value=('fallback','method'));self.native=MagicMock(return_value=self.fallback)
        self.find=policy.finder_factory(self.actual,self.lookup,self.upload,self.comments,self.native)([self.entry],True,total_timeout_ms=60000)
    def call(self):return self.find(self.page,MagicMock(),self.entry,'exact caption',10,20)
    def test_exact_profile_metadata_plus_author_allows_invisible_headless_player(self):
        self.assertEqual(self.call(),(self.link,'verified_owner_caption_time'));self.actual.require_target_author.assert_called_once_with(self.page,self.entry)
        self.page.locator.assert_not_called();self.fallback.assert_not_called()
        args=self.lookup.find_published.call_args;self.assertEqual(args.args[3:6],('exact caption',10,20))
    def test_ambiguity_wrong_actor_redirect_and_editor_stop_without_fallback(self):
        for kind in ['ambiguous','actor','redirect','editor']:
            with self.subTest(kind=kind):
                self.setUp()
                if kind=='ambiguous':self.lookup.find_published.side_effect=RuntimeError('作者、文案和时间匹配多个视频')
                if kind=='actor':self.actual.require_target_author.side_effect=ValueError('wrong actor')
                if kind=='redirect':self.page.url='https://www.facebook.com/reel/999999999999999'
                if kind=='editor':self.page.get_by_role.return_value.count.return_value=1;self.page.get_by_role.return_value.nth.return_value.is_visible.return_value=True
                with self.assertRaises((ValueError,RuntimeError)):self.call()
                self.fallback.assert_not_called()
    def test_missing_profile_evidence_falls_back_to_original_reels_verifier(self):
        self.lookup.find_published.side_effect=RuntimeError('未找到唯一匹配作者、完整文案、发布时间和视频编号的帖子')
        self.assertEqual(self.call(),('fallback','method'));self.fallback.assert_called_once()

if __name__=='__main__':unittest.main()
