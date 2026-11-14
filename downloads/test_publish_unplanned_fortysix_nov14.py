import copy,unittest
from datetime import datetime
from unittest.mock import MagicMock,patch
import publish_unplanned_fortysix_nov14 as app
from test_resume_nov13_two_waves_on_nov14 import CrossDayResumeTests


class FortySixPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fx=CrossDayResumeTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root;self.fx.advance_day()
        def only_four(account):
            if account not in app.EXISTING_FOUR:raise ValueError('owner verified but no display name')
            return self.fx.fx.discover(account)
        with patch.object(app.original.registration,'discover',side_effect=only_four),patch.object(app.first,'execute',side_effect=lambda real:app.resume.execute()):
            _,events,_=self.fx.fx.fx.core(include_new=True)
        self.assertEqual(sum(e[0]=='post' for e in events),48)
        self.before=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        self.parents={p:p.read_bytes() for p in (self.root/'logs').glob('frozen-material-2026-11-1[34]-*.json')}
        self.config=app.first.upload.read_json(app.first.upload.CONFIG,{})
        clock=self.enterContext(patch.object(app,'datetime',wraps=datetime));clock.now.return_value=self.fx.fx.fx.now
        self.today=self.root/'videos/fb25/personal/inbox/new-Nov14-material.mp4';self.today.write_bytes(b'never select or move this file')
    def discover(self,account):
        entry,proof=self.fx.fx.discover(account)
        # An observed name is cosmetic; synthetic IDs still bind the identity.
        entry['name']=account+' [verified ID '+entry['url'].split('=')[-1]+']';proof.update(name=entry['name'],display_name_source='verified_id_local_label')
        return entry,proof
    def core(self,fail_account=None,unknown=False,manual=True):
        self.fx.clock.now.return_value=self.fx.fx.fx.now
        tick=self.fx.fx.fx.tick
        def advance(*args):
            tick(*args);self.fx.clock.now.return_value=self.fx.fx.fx.now
        def background(account,*args):
            if account==fail_account:raise app.guided.LoginIssue('login_or_checkpoint','requires owner login')
            return self.discover(account)
        def foreground(account):
            entry,proof=self.discover(account);return entry,proof,'foreground_minimized'
        with patch.object(app,'discover_background',side_effect=background) as discover, \
             patch.object(app,'discover_manual',side_effect=foreground) as assisted, \
             patch.object(app.guided,'prompt',return_value='' if manual else 'S'), \
             patch.object(self.fx.fx.fx,'tick',side_effect=advance), \
             patch.object(app.first,'execute',side_effect=lambda real:app.execute()):
            result,events,comments=self.fx.fx.fx.core(include_new=True,unknown=unknown)
        return result,events,comments,discover,assisted
    def test_only_original46_publish_with_comments_no_old_targets_or_newer_material_and_rerun_no_duplicates(self):
        result,events,comments,discover,assisted=self.core();self.assertEqual(result,0)
        posts=[e[1] for e in events if e[0]=='post'];self.assertEqual(len(posts),46);self.assertEqual({a for a,t in posts},app.REQUESTED)
        self.assertEqual(discover.call_count,46);assisted.assert_not_called();self.assertEqual([len(k) for k in comments],[46])
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in self.before.items():self.assertEqual(state[key],row)
        for path,data in self.parents.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(self.today.read_bytes(),b'never select or move this file')
        summary=app.first.upload.read_json(self.root/'logs'/app.SUMMARY,{})
        self.assertEqual(len(summary['rows']),46);self.assertEqual(summary['unplanned_accounts'],[])
        result,events,_,discover,_=self.core();self.assertEqual(result,0);self.assertFalse(any(e[0]=='post' for e in events));discover.assert_not_called()
    def test_automatic45_are_published_before_manual_account_and_only_that_account_posts_in_second_wave(self):
        result,events,comments,_,assisted=self.core(fail_account='fb25');self.assertEqual(result,0)
        posts=[e[1] for e in events if e[0]=='post'];self.assertEqual(len(posts),46);self.assertEqual(posts[-1],('fb25','personal'))
        self.assertEqual([len(k) for k in comments],[45,1]);assisted.assert_called_once_with('fb25')
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in self.before.items():self.assertEqual(state[key],row)
    def test_submitted_unknowns_are_preserved_without_second_upload(self):
        result,events,_,_,_=self.core(unknown=True);self.assertEqual(result,3);self.assertEqual(sum(e[0]=='post' for e in events),46)
        result,events,_,_,_=self.core(unknown=True);self.assertEqual(result,3);self.assertFalse(any(e[0]=='post' for e in events))
    def test_manual_skip_leaves_one_unplanned_and_never_blocks_other45(self):
        result,events,_,_,assisted=self.core(fail_account='fb25',manual=False)
        self.assertEqual(result,3);self.assertEqual(sum(e[0]=='post' for e in events),45);assisted.assert_not_called()
        summary=app.first.upload.read_json(self.root/'logs'/app.SUMMARY,{})
        self.assertEqual(summary['unplanned_accounts'],['fb25'])


class VerifiedIdNameTests(unittest.TestCase):
    def test_missing_cosmetic_name_uses_local_label_only_after_full_owner_proof(self):
        page=MagicMock();page.context.cookies.return_value=[dict(name='c_user',value='1001')]
        proof=dict(session_marker='verified-actor',recovery_login_marker='verified-login',method='personal_actor_id_match',target_url='https://www.facebook.com/profile.php?id=1001',verified_aliases=[])
        with patch.object(app.guided.base,'wait_session'),patch.object(app.first.upload,'personal_actor_fingerprint'),patch.object(app.first.upload,'navigate_profile'), \
             patch.object(app.first.personals,'ensure_personal',return_value=copy.deepcopy(proof)) as verify, \
             patch.object(app.original.registration,'automatic_name',return_value=None),patch.object(app.first.personals,'stable_actor',return_value='verified-actor'), \
             patch.object(app.time,'monotonic',side_effect=[0,4]):
            entry,result=app.identify_current(page,'fb25',expected='id:1001')
        verify.assert_called_once();self.assertEqual(entry['name'],'fb25 [verified ID 1001]')
        self.assertEqual(result['display_name_source'],'verified_id_local_label');self.assertEqual(result['session_marker'],'verified-actor')
    def test_wrong_owner_or_actor_never_gets_a_placeholder_registration(self):
        page=MagicMock();page.context.cookies.return_value=[dict(name='c_user',value='1001')]
        with patch.object(app.guided.base,'wait_session'),patch.object(app.first.personals,'ensure_personal') as verify:
            with self.assertRaises(app.guided.LoginIssue):app.identify_current(page,'fb25',expected='id:2002')
        verify.assert_not_called()
        with patch.object(app.guided.base,'wait_session'),patch.object(app.first.upload,'personal_actor_fingerprint',side_effect=app.first.upload.PageActorActive),patch.object(app.first.personals,'ensure_personal') as verify:
            with self.assertRaises(app.first.upload.PageActorActive):app.identify_current(page,'fb25')
        verify.assert_not_called()


if __name__=='__main__':unittest.main()
