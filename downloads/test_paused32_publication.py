import copy,unittest
from unittest.mock import patch
import publish_eligible78_materials_20261117 as app
from test_paused29_publication import CURRENT_PAUSED,Paused29PublicationTests
CURRENT32=CURRENT_PAUSED|{'fb56','fb65','fb67'}

class Paused32PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fx=Paused29PublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
    def test_latest32_defaults_are_exact_and_fresh_only62_publish_without_windows_for_new_three(self):
        with patch.object(app,'PAUSED',set(CURRENT32)),patch.object(app,'manual_existing',side_effect=AssertionError('No paused popup')),patch.object(app,'manual_new',side_effect=AssertionError('No paused popup')):
            result,events,_,calls,_,prompts=self.fx.fx.core()
        self.assertEqual(result,0);self.assertEqual(sum(e=='post' for e,p in events),62);self.assertFalse(set(calls)&CURRENT32);self.assertFalse(prompts)
        req,path,control=self.fx.control();self.assertEqual(control['active_target_count'],62);self.assertEqual(control['paused_target_count'],16)
        self.assertEqual(app.first.upload.read_json(self.root/app.AVAILABILITY,{})['payload']['excluded_accounts'],sorted(CURRENT32))
    def test_old65_unknown_results_keep_state_and_frozen_shas_after_three_more_are_paused(self):
        with patch.object(app,'PAUSED',set(CURRENT_PAUSED)):self.fx.fx.core(unknown=True)
        req,path,control=self.fx.control();saved=(self.root/app.REQUEST).read_bytes();frozen={self.root/'logs'/w['manifest']:(self.root/'logs'/w['manifest']).read_bytes() for w in control['waves']}
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{});protected={k:copy.deepcopy(r) for k,r in state.items() if r.get('account') in {'fb56','fb65','fb67'}}
        self.assertEqual(len(protected),3)
        with patch.object(app,'PAUSED',set(CURRENT32)):result,events,_,calls,_,_=self.fx.fx.core(unknown=True)
        self.assertEqual(result,3);self.assertFalse(any(e=='post' for e,p in events));self.assertFalse(set(calls)&CURRENT32)
        current=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in protected.items():self.assertEqual(current[key],row)
        self.assertEqual((self.root/app.REQUEST).read_bytes(),saved)
        for file,data in frozen.items():self.assertEqual(file.read_bytes(),data)

if __name__=='__main__':unittest.main()
