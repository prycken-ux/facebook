import contextlib,copy,io,json,unittest
from pathlib import Path
from unittest.mock import patch
import repair_nov25_comments_only as repair
import publish_eligible60_real_20261125 as day
import comment_target_watchdog_20261125 as watchdog
import test_publish_eligible60_real_20261125 as fixture

class CommentRepairTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.Nov25PublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.fx.core()
        first=day.first;self.req=first.upload.read_json(self.root/day.REQUEST,{})
        self.controller=first.upload.read_json(self.root/'logs'/('eligible60-real-publication-'+self.req['sha256'][:16]+'.json'),{})
        self.jobs,self.waves=repair.checked_jobs(day,self.root,self.req,self.controller)
        state=first.upload.read_json(self.root/'logs/publish_state.json',{})
        for j in self.jobs:
            row=state[j['key']];row['comment_status']='deferred'
            for field in ['permalink','comment_link_job_key','comment_link_method']:row.pop(field,None)
        first.upload.save_json(self.root/'logs/publish_state.json',state)
        first.upload.save_json(self.root/'logs/video_comments.json',{})
        self.before=copy.deepcopy(state)
        for path in (self.root/'videos').rglob('*.mp4'):path.unlink()
        self.assertFalse(list((self.root/'videos').rglob('*.mp4')))
        self.progress=self.root/'logs/progress.json';self.operation=self.root/'logs/operation.json'
        self.verify=self.enterContext(patch.object(repair,'verified',side_effect=lambda f,r,k,t:f.upload.read_json(r/'logs/publish_state.json',{}).get(k,{}).get('comment_status')=='sent'))
    def core(self):
        watchdog.files.save(self.progress,watchdog.progress_new('run',self.req['sha256']))
        with repair.installed(day),watchdog.guarded_worker(day,self.root,'run','attempt',self.progress,self.operation):return self.fx.core()
    def test_comments_only60_without_mp4_and_replay_does_not_send_or_upload(self):
        result,events,comments,calls=self.core();self.assertEqual(result,0);self.assertEqual(calls,[]);self.assertFalse(any(e=='post' for e,p in events))
        self.assertEqual(set().union(*comments),{j['key'] for j in self.jobs})
        state=day.first.upload.read_json(self.root/'logs/publish_state.json',{})
        today={j['key'] for j in self.jobs}
        for k,row in self.before.items():
            if k not in today:self.assertEqual(state[k],row)
        result,events,comments,calls=self.core();self.assertFalse(events);self.assertFalse(comments);self.assertFalse(calls)
        self.assertEqual(day.first.upload.read_json(self.root/repair.RESULT,{})['automatic_verified'],60)
    def test_first_comment_unverified_stops_bulk_and_exports_diagnostics(self):
        self.verify.side_effect=lambda *args:False
        result,events,comments,calls=self.core();self.assertEqual(result,3);self.assertFalse(any(e=='post' for e,p in events));self.assertEqual(calls,[])
        self.assertEqual(len(set().union(*comments)),1)
        self.assertIn('首条',day.first.upload.read_json(self.root/repair.RESULT,{})['blocked_reason'])
        self.assertTrue(list((self.root/'logs').glob('FB-comments-1125-*.zip')))
    def test_paused_and_unsubmitted_and_prepost_failure_never_comment(self):
        state=day.first.upload.read_json(self.root/'logs/publish_state.json',{});skip={self.jobs[0]['key'],self.jobs[1]['key']}
        state[self.jobs[0]['key']]['status']='failed_before_post';state[self.jobs[0]['key']].pop('post_intent_at',None)
        state.pop(self.jobs[1]['key']);day.first.upload.save_json(self.root/'logs/publish_state.json',state)
        result,events,comments,calls=self.core();self.assertEqual(set().union(*comments),{j['key'] for j in self.jobs}-skip);self.assertFalse(calls)
    def test_other_date_manifest_rejected_before_state_changes_or_comment(self):
        value=copy.deepcopy(self.req);value['payload']['material_date']='2026-11-24';value['sha256']=day.first.batch.digest(value['payload'])
        with self.assertRaisesRegex(ValueError,'11月25'):repair.checked_jobs(day,self.root,value,self.controller)
        self.assertEqual(day.first.upload.read_json(self.root/'logs/publish_state.json',{}),self.before)
    def test_upload_is_explicitly_forbidden(self):
        with repair.installed(day),self.assertRaisesRegex(ValueError,'禁止上传'):day.first.upload.run_entry({},None,None,True)

class EvidenceAndVerificationTests(unittest.TestCase):
    def test_diagnostic_drops_secrets_raw_response_and_limits_size(self):
        payload={'headers':{'Authorization':'secret'},'cookies':['secret'],'data':[dict(__typename='Video',id=str(i),owner={'id':'owner'},description='caption',creation_time=i,cookie='secret') for i in range(100)]}
        rows=repair.evidence_rows(payload);self.assertEqual(len(rows),60);self.assertNotIn('secret',json.dumps(rows));self.assertEqual(rows[0]['description'],'caption')
    def test_sent_status_without_reload_ledger_is_not_verified(self):
        from types import SimpleNamespace as N
        import safe_video_comments as comments
        first=N(priority=N(daily=N(comments=comments)),upload=N(read_json=lambda p,d:{}))
        self.assertFalse(repair.verified(first,Path('/tmp'),'key','original comment'))

if __name__=='__main__':unittest.main()
