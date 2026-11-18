import contextlib,copy,io,unittest
from unittest.mock import patch
import publish_eligible78_materials_20261117 as app
from test_publish_eligible78_materials_20261117 import Eligible78PublicationTests
CURRENT_PAUSED={f'fb{n:02d}' for n in (17,23,25,27,28,29,30,33,34,35,36,38,39,41,42,44,48,50,53,57,58,59,61,64,69,71,72,73,74)}

class Paused29PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fx=Eligible78PublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root
    def latest(self):return patch.object(app,'PAUSED',set(CURRENT_PAUSED))
    def control(self):
        req=app.first.upload.read_json(self.root/app.REQUEST,{})
        path=self.root/'logs'/('eligible78-real-publication-'+req['sha256'][:16]+'.json')
        return req,path,app.first.upload.read_json(path,{})
    def test_exact29_and65_fresh_run_never_register_post_comment_or_prompt_paused(self):
        files={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file() and p.relative_to(self.root).parts[1] in CURRENT_PAUSED}
        with self.latest(),patch.object(app,'manual_existing',side_effect=AssertionError('No paused verification window')),patch.object(app,'manual_new',side_effect=AssertionError('No paused registration window')):
            result,events,comments,calls,_,prompts=self.fx.core()
        for file,data in files.items():self.assertEqual(file.read_bytes(),data)
        self.assertEqual(len(CURRENT_PAUSED),29);self.assertEqual(result,0)
        posts=[p for e,p in events if e=='post'];expected={p for p in app.EXPECTED if p[0] not in CURRENT_PAUSED}
        self.assertEqual(len(posts),65);self.assertEqual(set(posts),expected);self.assertFalse(set(calls)&CURRENT_PAUSED);self.assertFalse(prompts)
        req,path,control=self.control();self.assertEqual(control['active_target_count'],65);self.assertEqual(control['paused_target_count'],13)
        self.assertTrue(all(r['user_paused'] for r in control['rows'] if r['account'] in CURRENT_PAUSED))
        self.assertEqual(req['payload']['excluded_accounts'],sorted(app.BLOCKED))
        available=app.first.upload.read_json(self.root/app.AVAILABILITY,{})['payload'];self.assertEqual(available['excluded_accounts'],sorted(CURRENT_PAUSED))
    def test_resume_original78_unknowns_keeps_frozen_shas_and_paused_states_without_lookup(self):
        self.fx.core(unknown=True);req,path,control=self.control();request_bytes=(self.root/app.REQUEST).read_bytes()
        snapshots={self.root/'logs'/w['manifest']:(self.root/'logs'/w['manifest']).read_bytes() for w in control['waves']}
        before=app.first.upload.read_json(self.root/'logs/publish_state.json',{});protected={k:copy.deepcopy(r) for k,r in before.items() if r.get('account') in CURRENT_PAUSED}
        extra=self.root/'additional_personal_accounts.json';value=app.first.upload.read_json(extra,{})
        for account in CURRENT_PAUSED&app.owned.NEW:value['slots'].pop(account,None)
        app.first.upload.save_json(extra,value)
        with self.latest():result,events,_,calls,_,prompts=self.fx.core(unknown=True)
        self.assertEqual(result,3);self.assertFalse(any(e=='post' for e,p in events));self.assertFalse(set(calls)&CURRENT_PAUSED)
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in protected.items():self.assertEqual(state[key],row)
        self.assertEqual((self.root/app.REQUEST).read_bytes(),request_bytes)
        for file,data in snapshots.items():self.assertEqual(file.read_bytes(),data)
        pending=prompts[0][0] if prompts else ''
        _,_,control=self.control();self.assertTrue(all(r['user_paused'] for r in control['rows'] if r['account'] in CURRENT_PAUSED))
    def test_preexisting_failure_gets_no_automatic_or_explicit_retry_and_original_record_is_kept(self):
        self.fx.core(login_account='fb27');req,path,control=self.control()
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{});protected={k:copy.deepcopy(r) for k,r in state.items() if r.get('account') in CURRENT_PAUSED}
        with self.latest():
            result,events,_,calls,_,_=self.fx.core();self.assertEqual(result,0);self.assertFalse(set(calls)&CURRENT_PAUSED);self.assertFalse(any(e=='post' for e,p in events))
            req,path,control=self.control()
            with patch.object(app.first.batch,'excluded_accounts',side_effect=app.exclusions),patch.object(app.owned,'reservation',side_effect=app.active_reservation),patch.object(app.first.normal,'launch_normal',side_effect=AssertionError('Paused explicit retry must not open Chrome')):
                for wave in control['waves']:app.run_phase('extra',req,self.fx.source,self.fx.journal,self.fx.material,wave,control,{})
        current=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in protected.items():self.assertEqual(current[key],row)
        for file in (self.root/'logs').glob('eligible78-real-extra-*-claims.json'):
            value=app.first.upload.read_json(file,{})
            self.assertFalse(set(value.get('jobs',{}))&set(protected))
    def test_first_attempt_skips_paused_before_window_close_or_upload(self):
        # Freeze all78 with the old policy, but execute the first pass only after
        # the new user pause list has taken effect.
        with patch.object(app,'run_phase',side_effect=lambda *a,**k:None),patch.object(app.owners.guided,'prompt',return_value='S'):
            self.fx.core()
        req,path,control=self.control();self.assertTrue(control['waves'])
        with self.latest():
            result,events,_,calls,_,_=self.fx.core()
        self.assertEqual(result,0);self.assertEqual(sum(e=='post' for e,p in events),65);self.assertFalse(set(calls)&CURRENT_PAUSED)
        with patch.object(app,'PAUSED',CURRENT_PAUSED-{'fb25'}):result,events,_,_,_,_=self.fx.core()
        self.assertEqual(result,0);self.assertEqual([p for e,p in events if e=='post'],[('fb25','personal')])
    def test_only_unpaused_account_with_login_issue_enters_last_manual_queue(self):
        with self.latest(),patch.object(app,'manual_new',return_value=None) as manual:
            result,events,_,calls,_,prompts=self.fx.core(fail_account='fb31',manual=True)
        self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),64);self.assertFalse(set(calls)&CURRENT_PAUSED)
        manual.assert_called_once_with('fb31');self.assertTrue(prompts)
    def test_direct_verification_helpers_return_without_any_browser_or_owner_probe(self):
        with self.latest(),contextlib.redirect_stdout(io.StringIO()),patch.object(app.owners.guided,'open_for_check',side_effect=AssertionError('No paused popup')),patch.object(app.owners,'known_owner',side_effect=AssertionError('No paused owner lookup')):
            for account in sorted(CURRENT_PAUSED):
                self.assertIsNone(app.manual_existing(dict(account=account,target='personal')));self.assertIsNone(app.manual_new(account))
        self.assertNotIn('fb40',CURRENT_PAUSED)

if __name__=='__main__':unittest.main()
