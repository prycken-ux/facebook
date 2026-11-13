import copy,hashlib,unittest
from unittest.mock import patch
import publish_all_distributed_nov13 as app
from test_publish_distributed_nov13_first24 import DistributedFirst24Tests


class TwoWavePublicationTests(unittest.TestCase):
    def setUp(self):
        self.fx=DistributedFirst24Tests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root
        path=self.root/'additional_personal_accounts.json'
        value=app.first.upload.read_json(path,{})
        value['batches'][app.BATCH_ID]=dict(accounts=sorted(app.NEW),count=50,minimum_number=25)
        for account in app.NEW:value['slots'][account]=dict(batch_id=app.BATCH_ID,state='pending',type='personal')
        app.first.upload.save_json(path,value)
    def discover(self,account):
        config=app.first.upload.read_json(app.first.upload.CONFIG,{})
        entry=next(e for e in config['targets'] if e['account']==account)
        identity=app.first.upload.target_key(entry['url'])
        return copy.deepcopy(entry),dict(target_url=entry['url'],name=entry['name'],method='personal_actor_id_match',
                                         checked_at=self.fx.now.isoformat(),session_marker=hashlib.sha256(('personal:'+identity[3:]).encode()).hexdigest(),verified_aliases=[])
    def run_all(self,fail_account=None):
        def discover(account):
            if account==fail_account:raise ValueError('Login required for this exact profile')
            return self.discover(account)
        with patch.object(app.registration,'discover',side_effect=discover) as probe,patch.object(app.first,'execute',side_effect=app.execute):
            result,events,comments=self.fx.core(include_new=True)
        return result,events,comments,probe

    def test_all94_in_order_with_comments_for_both_waves_and_no_repost_on_resume(self):
        result,events,comments,probe=self.run_all();self.assertEqual(result,0)
        posts=[e[1] for e in events if e[0]=='post']
        self.assertEqual(len(posts),94)
        self.assertTrue(all(int(a[2:])<=24 for a,t in posts[:44]))
        self.assertEqual([a for a,t in posts[44:]],sorted(app.NEW))
        self.assertEqual([len(x) for x in comments],[44,50])
        self.assertEqual(probe.call_count,50)
        self.assertEqual(events[44],('comment-pass',44))
        registry=app.reservation()
        self.assertTrue(all(registry['slots'][a]['publishing_ready'] for a in app.NEW))
        result,events,_,probe=self.run_all();self.assertEqual(result,0)
        self.assertFalse(any(e[0]=='post' for e in events));probe.assert_not_called()

    def test_late_login_can_add_a_second_new_account_wave_without_reposting_previous93(self):
        result,events,_,_=self.run_all(fail_account='fb74');self.assertEqual(result,3)
        self.assertEqual(sum(e[0]=='post' for e in events),93)
        result,events,_,probe=self.run_all();self.assertEqual(result,0)
        self.assertEqual([e[1] for e in events if e[0]=='post'],[('fb74','personal')])
        self.assertEqual([c.args[0] for c in probe.call_args_list],['fb74'])

    def test_new_generation_guard_does_not_allow_old_deleted_fb25_or_shared_identity(self):
        entry,proof=self.discover('fb25')
        proof['session_marker']='wrong owner'
        with self.assertRaisesRegex(ValueError,'确切本人身份'):app.register_one('fb25',entry,proof)
        path=self.root/'additional_personal_accounts.json';value=app.first.upload.read_json(path,{})
        value['slots']['fb25']['batch_id']='deleted-old-generation';app.first.upload.save_json(path,value)
        with self.assertRaisesRegex(ValueError,'新50账号批次'):app.reservation()


if __name__=='__main__':unittest.main()
