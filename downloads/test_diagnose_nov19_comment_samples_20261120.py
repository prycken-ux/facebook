import contextlib,copy,json,unittest,zipfile
from unittest.mock import MagicMock,patch
import diagnose_nov19_comment_samples_20261120 as sample
import test_archive_nov19_user_confirmed_20261120 as fixture

class SampleReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.Nov19ArchiveTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        first=sample.app.first;self.first=first
        self.enterContext(patch.object(first.priority.daily,'configured',side_effect=lambda j:dict(j,name='Fixture owner',type='personal' if j['target']=='personal' else 'page')))
        for module,attribute in ((sample.app.response_guard,'installed'),(sample.app.background_policy,'installed'),(first.personals,'scoped'),(first.numeric,'scoped')):
            self.enterContext(patch.object(module,attribute,side_effect=lambda *a,**k:contextlib.nullcontext()))
        self.enterContext(patch('playwright.sync_api.sync_playwright'))
        self.enterContext(patch.object(first.upload,'ensure_identity'))
        self.browser=MagicMock();self.page=MagicMock();self.browser.pages=[self.page];self.page.evaluate.return_value={'visible_video':True,'textboxes':[]}
        self.enterContext(patch.object(first.normal,'launch_normal',return_value=self.browser))
        self.enterContext(patch.object(first.priority.actual,'inspect_video',return_value=(False,dict(owner=True,caption=False,time=True))))
        self.enterContext(patch.object(first.priority.daily.comments,'scan_comments',return_value=[]))
        self.enterContext(patch.object(first.upload,'run_entry',side_effect=AssertionError('Read-only diagnostic must never publish')))
        self.state=(self.root/'logs/publish_state.json').read_bytes()
    def test_two_fixed_links_and_report_without_mutating_state_or_sending(self):
        output=sample.collect(self.root)
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),self.state)
        self.assertEqual(self.first.normal.launch_normal.call_count,2);self.assertEqual(self.browser.close.call_count,2)
        with zipfile.ZipFile(output) as z:
            self.assertEqual(z.namelist(),['summary.json']);summary=json.loads(z.read('summary.json'))
        self.assertTrue(summary['read_only']);self.assertEqual(len(summary['samples']),2)
        self.assertEqual({r['permalink'] for r in summary['samples']},set(sample.archive.MANUAL_COMMENTS.values()))
        self.assertTrue(all(r['video_lookup_match'] is False and r['comment_match_count']==0 for r in summary['samples']))
    def test_login_issue_is_logged_and_other_sample_still_runs(self):
        with patch.object(self.first.upload,'ensure_identity',side_effect=[RuntimeError('Login required'),{}]):output=sample.collect(self.root)
        with zipfile.ZipFile(output) as z:summary=json.loads(z.read('summary.json'))
        self.assertEqual(summary['samples'][0]['error'],'Login required');self.assertIn('video_lookup_match',summary['samples'][1]);self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),self.state)
    def test_busy_task_does_not_open_browser_or_collect(self):
        with patch.object(sample.archive,'inspect_workers',return_value=[dict(pid=123)]):
            with self.assertRaisesRegex(ValueError,'其他发布'):sample.collect(self.root)
        self.first.normal.launch_normal.assert_not_called()
    def test_extra_user_pause_does_not_open_that_account(self):
        with patch.object(sample.app,'read_live_pauses',return_value=sample.app.BLOCKED|{'fb04'}):output=sample.collect(self.root)
        self.assertEqual(self.first.normal.launch_normal.call_count,1)
        with zipfile.ZipFile(output) as z:summary=json.loads(z.read('summary.json'))
        self.assertIn('用户暂停',summary['samples'][0]['error'])

if __name__=='__main__':unittest.main()
