import contextlib,io,json,unittest
from datetime import datetime
from unittest.mock import MagicMock,patch
import diagnose_login_and_resume_fifteen_nov14 as app
from test_retry_nov13_prepost_fifteen_on_nov14 import ExplicitFifteenTests


OK=dict(ok=True,code='verified_owner',message='verified')
MISSING=dict(ok=False,code='session_missing',message='missing saved session')


class DiagnosticFlowTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.entry=dict(account='fb09',target='personal',type='personal',name='Original owner',url='https://www.facebook.com/profile.php?id=1001',auto_switch_personal=True)
    def test_healthy_background_needs_no_visible_window_or_prompt(self):
        with patch.object(app,'probe_background',return_value=OK),patch.object(app,'manual_foreground') as manual,patch.object(app,'prompt') as prompt:
            row=app.diagnose_account(self.entry)
        self.assertEqual(row['mode'],'background');manual.assert_not_called();prompt.assert_not_called()
    def test_manual_repair_rechecks_background_before_choosing_mode(self):
        with patch.object(app,'probe_background',side_effect=[MISSING,OK]),patch.object(app,'manual_foreground',return_value=OK),patch.object(app,'prompt') as prompt:
            row=app.diagnose_account(self.entry)
        self.assertEqual(row['mode'],'background');prompt.assert_not_called()
    def test_background_compatibility_requires_explicit_choice_and_wrong_owner_is_never_accepted(self):
        with patch.object(app,'probe_background',return_value=MISSING),patch.object(app,'manual_foreground',return_value=OK),patch.object(app,'prompt',return_value='F') as prompt:
            row=app.diagnose_account(self.entry)
        self.assertEqual(row['mode'],'foreground_minimized');self.assertEqual(prompt.call_count,1)
        conflict=dict(ok=False,code='wrong_owner',message='wrong account')
        with patch.object(app,'probe_background',side_effect=[MISSING,conflict]),patch.object(app,'manual_foreground',return_value=OK),patch.object(app,'prompt') as prompt:
            row=app.diagnose_account(self.entry)
        self.assertIsNone(row['mode']);prompt.assert_not_called()
    def test_wrong_cookie_owner_stops_before_identity_lookup_and_no_cookie_contents_are_reported(self):
        page=MagicMock();page.context.cookies.return_value=[dict(name='c_user',value='2002')]
        with patch.object(app.first.upload,'checkpoint'),patch.object(app.first.upload,'require_no_advanced_protection'),patch.object(app.first.personals,'ensure_personal') as identity:
            with self.assertRaises(app.LoginIssue) as result:app.verify_session(page,self.entry)
        self.assertEqual(result.exception.code,'wrong_owner');identity.assert_not_called()
        self.assertNotIn('2002',json.dumps(app.brief(result.exception)))
        self.assertEqual(app.brief(app.base.SessionNotReady('登录者身份不唯一或无效'))['code'],'conflicting_login')
        self.assertEqual(app.brief(RuntimeError('net::ERR_PROXY_CONNECTION_FAILED at https://example.com/?secret=value'))['message'],'net::ERR_PROXY_CONNECTION_FAILED')
    def test_login_window_stays_open_for_human_and_closes_only_after_verified_or_skipped(self):
        context=MagicMock();page=MagicMock()
        with patch('playwright.sync_api.sync_playwright'),patch.object(app,'open_for_check',return_value=(context,page)), \
             patch.object(app,'verify_session',side_effect=[app.LoginIssue('login_or_checkpoint','manual verification needed'),OK]), \
             patch.object(app,'prompt',return_value='') as prompt:
            self.assertTrue(app.manual_foreground(self.entry)['ok'])
        prompt.assert_called_once();context.close.assert_called_once()
    def test_background_network_navigation_failure_is_classified_without_claiming_logout(self):
        context=MagicMock();page=MagicMock();page._manual_check_navigation_issue=dict(ok=False,code='network_error',message='net::ERR_CONNECTION_CLOSED')
        with patch('playwright.sync_api.sync_playwright'),patch.object(app,'open_for_check',return_value=(context,page)),patch.object(app.base,'wait_session') as wait:
            row=app.probe_background(self.entry)
        self.assertEqual(row['code'],'network_error');wait.assert_not_called();context.close.assert_called_once()
    def test_minimized_mode_is_scoped_and_preserves_profile_proxy_and_extension_flags(self):
        flags_before=app.first.normal.background.arguments('background')
        real_popen=MagicMock();real_popen.return_value='chrome-process'
        args=['chrome.exe','--user-data-dir='+str(app.first.upload.ROOT/'profiles/fb09'),'--new-window']
        with patch.object(app.sys,'platform','win32'),patch.object(app.first.normal.subprocess,'STARTUPINFO',create=True) as startup, \
             patch.object(app.first.normal.subprocess,'STARTF_USESHOWWINDOW',1,create=True),patch.object(app.first.normal.subprocess,'Popen',real_popen):
            startup.return_value.dwFlags=0
            with app.minimized_chrome(self.entry):
                self.assertEqual(app.first.normal.background.mode(None),'foreground')
                flags=app.first.normal.background.arguments('foreground');self.assertIn('--start-minimized',flags)
                self.assertEqual(app.first.normal.subprocess.Popen(args,stdout=-3,stderr=-3),'chrome-process')
            self.assertEqual(real_popen.call_args.kwargs['startupinfo'].wShowWindow,7)
        self.assertEqual(app.first.normal.background.arguments('background'),flags_before)
        self.assertNotIn('--headless=new',flags)
        self.assertFalse(any(v.startswith(('--proxy-server','--disable-extensions','--no-sandbox')) for v in flags))


class GuidedRetryTests(unittest.TestCase):
    def setUp(self):
        self.fx=ExplicitFifteenTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        clock=self.enterContext(patch.object(app,'datetime',wraps=datetime));clock.now.return_value=self.fx.distributed.now
    def test_old_session_failures_can_continue_after_human_check_without_new_grant_or_other_targets(self):
        # Model the last Windows run: no core attempt or Post occurred.
        _,posts,_=self.fx.core(session_failure=True);self.assertEqual(posts,[])
        checked=[]
        def diagnosis(entry):
            checked.append(entry['account'])
            return dict(account=entry['account'],mode=None if entry['account']=='fb17' else 'foreground_minimized' if entry['account']=='fb09' else 'background',conclusion='synthetic owner action')
        with patch.object(app,'diagnose_account',side_effect=diagnosis),patch.object(app.base,'execute',side_effect=app.execute):
            result,posts,comments=self.fx.core()
        self.assertEqual(result,3);self.assertEqual(len(posts),14);self.assertNotIn(('fb17','personal'),posts)
        self.assertEqual(checked,list(app.ACCOUNTS))
        state=app.first.upload.read_json(self.fx.root/'logs/publish_state.json',{})
        skipped=self.fx.alljobs['fb17','personal'];self.assertEqual(state[skipped['key']],self.fx.before[skipped['key']])
        selected_keys={j['key'] for j in self.fx.jobs}
        for key,row in self.fx.before.items():
            if key not in selected_keys:self.assertEqual(state[key],row)
        for path,data in self.fx.original_parents.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(self.fx.protected.read_bytes(),b'never publish new material')
        checked.clear()
        with patch.object(app,'diagnose_account',side_effect=diagnosis),patch.object(app.base,'execute',side_effect=app.execute):
            _,posts,_=self.fx.core()
        self.assertEqual(posts,[]);self.assertEqual(checked,['fb17'])
        reports=app.first.upload.read_json(self.fx.root/'logs'/app.REPORT,{})
        self.assertEqual(len(reports['runs']),2)


if __name__=='__main__':unittest.main()
