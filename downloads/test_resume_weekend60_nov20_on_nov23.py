import contextlib,copy,io,json,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import resume_weekend60_nov20_on_nov23 as resume
import test_weekend60_schedule_20261120 as fixture

class ResumeNov20Tests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.Weekend60Tests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root;_,self.value=self.fx.prepare();self.app=resume.app
        self.enterContext(patch.object(resume,'EXPECTED_MASTER_PREFIX',self.value['sha256'][:8]))
        self.enterContext(patch.object(resume,'EXPECTED_SOURCE_PREFIX',self.value['payload']['batches'][resume.SOURCE_DAY]['source_id'][:8]))
        self.clock=self.enterContext(patch.object(resume,'datetime',wraps=datetime))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        (self.root/'normal_chrome_batch.py').write_text("STARTUP_WAIT_VERSION='1.0-wait-for-endpoint-after-launcher-exit'\n")
    def run_resume(self,unknown=False):
        stamp=datetime(2026,11,23,3,tzinfo=timezone.utc)
        self.fx.fx.runfx.now=stamp
        for clock in self.fx.fx.runfx.clocks:clock.now.return_value=stamp
        self.fx.clock.now.return_value=stamp;self.clock.now.return_value=stamp
        self.fx.fx.runfx.material=resume.schedule.allocation(self.root,resume.SOURCE_DAY,self.value)[3]
        with patch.object(resume,'inspect_workers',return_value=[]),patch.object(self.app.workers,'active_workers',return_value=[]), \
             patch.object(self.app.browser.staged.lock_recovery,'recover_locks'),patch.object(self.app.extra,'wait_session'), \
             patch.object(self.app.extra,'ensure_background_identity',side_effect=lambda prev,p,e:prev(p,e)), \
             patch.object(self.app.owners,'discover_background',side_effect=self.fx.fx.fx.discover), \
             patch.object(self.app.first,'execute',side_effect=lambda real:resume.execute(self.root)):
            return self.fx.fx.runfx.core(unknown=unknown,include_new=True)
    def test_published_twenty_is_not_reuploaded_and_other_dates_untouched(self):
        self.fx.integration_run(resume.SOURCE_DAY)
        before={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file() and ('2026-11-21' in str(p) or '2026-11-22' in str(p))}
        result,events,_=self.run_resume();self.assertEqual(result,0);self.assertFalse(any(e=='post' for e,p in events))
        for p,data in before.items():self.assertEqual(p.read_bytes(),data)
        audit=resume.first.upload.read_json(self.root/resume.AUDIT,{})
        self.assertEqual(audit['payload']['material_date'],'2026-11-20');self.assertTrue(audit['payload']['created_at'].startswith('2026-11-23'))
    def test_unknown_twenty_submissions_not_reuploaded(self):
        self.fx.integration_run(resume.SOURCE_DAY,unknown=True)
        result,events,_=self.run_resume(unknown=True);self.assertEqual(result,3);self.assertFalse(any(e=='post' for e,p in events))
    def test_interruption_at_fb10_recovers_pending_and_posts_only_unstarted_originals(self):
        native=self.app.first.upload.run_entry
        def interrupt(entry,*args,**kwargs):
            try:return native(entry,*args,**kwargs)
            finally:
                if (entry['account'],entry['target'])==('fb10','page09'):
                    path=self.root/'logs/publish_state.json';state=self.app.first.upload.read_json(path,{})
                    key=kwargs['expected_job_key'];self.assertTrue(state[key].get('post_intent_at'))
                    state[key]['status']='posting';self.app.first.upload.save_json(path,state)
                    raise KeyboardInterrupt
        with patch.object(self.app.first.upload,'run_entry',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):self.fx.integration_run(resume.SOURCE_DAY,unknown=True)
        state=self.app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        attempted={(r['account'],r['target']) for r in state.values() if str(r.get('video','')).split('/')[-1].startswith('20261120-')}
        self.assertIn(('fb10','page09'),attempted)
        result,events,_=self.run_resume(unknown=True)
        posts=[p for e,p in events if e=='post'];self.assertEqual(set(posts),self.app.EXPECTED-attempted)
        self.assertEqual(len(posts),31)
        state=self.app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        record=next(r for r in state.values() if r.get('account')=='fb10' and r.get('target')=='page09' and '20261120-' in str(r.get('video','')))
        self.assertEqual(record['status'],'needs_review')
        self.assertFalse(any(r.get('status') in {'posting','preparing'} and r.get('account')=='fb10' for r in state.values()))
    def test_changed_source_master_and_content_fail_closed(self):
        self.fx.integration_run(resume.SOURCE_DAY)
        with patch.object(resume,'EXPECTED_SOURCE_PREFIX','wrong'):
            with self.assertRaisesRegex(ValueError,'20日d036b4ae'):resume.check_source(self.root,self.value)
        with patch.object(resume,'EXPECTED_MASTER_PREFIX','wrong'):
            with self.assertRaisesRegex(ValueError,'原三天计划'):resume.check_source(self.root,self.value)
    def test_worker_blocks_before_writing_authorization_or_running_browser(self):
        self.fx.integration_run(resume.SOURCE_DAY)
        self.clock.now.return_value=datetime(2026,11,23,3,tzinfo=timezone.utc)
        with patch.object(resume,'inspect_workers',return_value=[dict(pid=123)]),patch.object(self.app,'execute',side_effect=AssertionError('No upload')):
            with self.assertRaisesRegex(ValueError,'仍有发布'):resume.execute(self.root)
        self.assertFalse((self.root/resume.AUDIT).exists())
    def test_source_scope_does_not_change_clock_and_keeps_all_safeguards(self):
        real_today=self.app.today();root=self.root
        with resume.source_context(root,self.value):
            self.assertEqual(self.app.today(),real_today)
            self.assertEqual(self.app.content_today.DAY,'2026-11-20')
            self.assertTrue(str(self.app.first.upload.inbox_for(dict(account='fb04',target='personal'))).endswith('/scheduled/2026-11-20/inbox'))
            self.assertEqual(self.app.owners.guided.prompt('test'),'S')
            self.assertTrue(self.app.queued.retry.RECOVER.search('查看所有个人主页入口未加载，未选择视频或点击发布。'))
            self.assertTrue(self.app.queued.retry.DENY.search('遇到登录或安全验证'))
            for status in ('posting','published','needs_review'):
                self.assertTrue(self.app.queued.has_submission(dict(status=status)))

if __name__=='__main__':unittest.main()
