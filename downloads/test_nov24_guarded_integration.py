import copy,unittest
from pathlib import Path
from unittest.mock import patch
import publish_eligible60_real_20261124 as day
import publication_target_watchdog_20261124 as watchdog
from test_publish_eligible60_real_20261124 import Nov24PublicationTests

class GuardedIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fx=Nov24PublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root
        with day.authorized_context():
            _,source,journal,material=day.allocation(self.root);self.req=day.app.request(self.root,source,journal,material)
        self.progress=self.root/'logs/guarded-fixture.json';self.operation=self.root/'logs/guarded-operation-fixture.json'
        watchdog.files.save(self.progress,watchdog.progress_new('run',self.req['sha256']))
    def core(self,**kwargs):
        with watchdog.guarded_worker(day,self.root,'run','attempt',self.progress,self.operation):return self.fx.core(**kwargs)
    def test_all60_publish_and_comment_with_guard_hooks_and_remain_idempotent(self):
        entry=next(e for e in day.first.upload.read_json(self.root/'upload_config.json',{})['targets'] if (e['account'],e['target'])==('fb01','page01'))
        old_file=day.first.upload.inbox_for(entry)/'20261123-protected.mp4';old_file.write_bytes(b'Nov23 source must stay protected')
        key=day.first.upload.job_key(entry,old_file);path=self.root/'logs/publish_state.json';state=day.first.upload.read_json(path,{})
        old=dict(account='fb01',target='page01',url=entry['url'],video=str(old_file),status='needs_review',post_intent_at='2026-11-23T10:00:00+00:00',created='2026-11-23T09:59:00+00:00',uploader_version='2.47',ai_label_requested=False)
        state[key]=old;day.first.upload.save_json(path,state)
        result,events,comments,calls=self.core();self.assertEqual(result,0);self.assertEqual(sum(e=='post' for e,p in events),60)
        state=day.first.upload.read_json(self.root/'logs/publish_state.json',{})
        own=[r for r in state.values() if '20261124-' in r.get('video','')];self.assertEqual(len(own),60);self.assertTrue(all(r.get('comment_status')=='sent' for r in own))
        self.assertEqual(state[key],old);self.assertEqual(old_file.read_bytes(),b'Nov23 source must stay protected')
        result,events,_,_=self.core();self.assertEqual(sum(e=='post' for e,p in events),0)
    def test_network_safe_retry_and_pending_submit_protection_remain_effective(self):
        result,events,_,calls=self.core(network=True);self.assertEqual(result,0);self.assertEqual(sum(e=='post' for e,p in events),60);self.assertEqual(calls.count(('fb02','page01')),2)
    def test_skipped_video_never_uses_a_new_claim_or_posts_but_other59_continue(self):
        _,_,_,material=day.allocation(self.root)
        row=next(a for a in material['payload']['assignments'] if (a['account'],a['target'])==('fb02','page01'))
        entry=next(e for e in day.first.upload.read_json(self.root/'upload_config.json',{})['targets'] if (e['account'],e['target'])==('fb02','page01'))
        key=day.first.upload.job_key(entry,day.first.upload.inbox_for(entry)/row['files'][-1]['destination_name'])
        p=watchdog.read(self.progress);p['skipped_video'][key]={'reason':'simulated timeout'};watchdog.files.save(self.progress,p)
        result,events,_,calls=self.core();self.assertEqual(sum(e=='post' for e,pair in events),59);self.assertNotIn(('fb02','page01'),calls)
        claims=day.first.upload.read_json(self.root/'logs/automatic_before_post_retry_claims.json',{'jobs':{}});self.assertNotIn(key,claims['jobs'])

if __name__=='__main__':unittest.main()
