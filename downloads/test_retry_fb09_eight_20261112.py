import copy
import contextlib
import os
import time
import unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch

import retry_fb09_eight_20261112 as app
from test_repair_nov11_identity_20261112 import IdentityRepairTests


class ExplicitEightRetryTests(unittest.TestCase):
    def setUp(self):
        self.base = IdentityRepairTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.root = self.base.root
        self.stack = self.base.fx.stack
        (path,value),_ = self.base.prepare()
        jobs = [j for j in value['payload']['jobs'] if j['account']=='fb09' or j['account']=='fb16']
        self.assertEqual(len(jobs),11)
        value = copy.deepcopy(value)
        value['payload']['jobs'] = jobs
        value['sha256'] = app.batch.digest(value['payload'])
        self.path = path.with_name('frozen-material-'+app.DAY+'-'+value['sha256'][:16]+'.json')
        self.value = value
        app.upload.save_json(self.path,value)
        app.upload.save_json(self.root/'logs/nov11-identity-repair-on-20261112.json',dict(manifest=self.path.name,sha256=value['sha256']))
        self.stack.enter_context(patch.object(app,'SOURCE_PREFIX',value['sha256'][:8]))
        selected = [j for j in jobs if j['target'] in app.TARGETS and j['account']=='fb09']
        self.jobs = selected
        self.stack.enter_context(patch.object(app,'TARGETS',{j['target']:(j['filename'],j['key'][:12]) for j in selected}))
        state = app.upload.read_json(self.root/'logs/publish_state.json',{})
        for job in jobs:
            row = dict(account=job['account'],target=job['target'],url=job['url'],video=str(self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']),
                       status='failed_before_post',ai_label_requested=False,uploader_version='2.47',today_first_retry_used=True,
                       created='2026-11-12T06:00:00+00:00',failure_stage='modern_caption_audience_ai')
            row['previous_before_post_attempt'] = dict(row,today_first_retry_used=False)
            if job['target'] in {'page01','page08'}:
                row.update(status='published',post_intent_at='2026-11-12T06:01:00+00:00')
            if job['account']=='fb16':
                row.update(status='needs_review',post_intent_at='2026-11-12T06:01:00+00:00')
            state[job['key']] = row
        app.upload.save_json(self.root/'logs/publish_state.json',state)
        self.state = state
        self.protected = {k:copy.deepcopy(v) for k,v in state.items() if k not in {j['key'] for j in selected}}
        app.upload.save_json(self.path.with_name(self.path.stem+'-results.json'),dict(manifest=self.path.name,attempts=[dict(key=j['key'],action='finished') for j in jobs]))
        self.source_before = self.path.read_bytes()
        self.config_before = app.upload.CONFIG.read_bytes()
        self.stack.enter_context(patch.object(app.sys,'platform','win32'))
        clock = self.stack.enter_context(patch.object(app,'datetime',wraps=datetime))
        clock.now.return_value = datetime(2026,11,12,7,tzinfo=timezone.utc)
        self.stack.enter_context(patch.object(app,'close_selected_window'))
        self.stack.enter_context(patch.object(app.priority.daily,'keep_awake',side_effect=contextlib.nullcontext))
        for file in self.root.rglob('*'):
            if file.is_file() and file.suffix in {'.mp4','.txt'}:
                os.utime(file,(time.time()-180,time.time()-180))

    def core(self,unknown=False,preflight_error=False):
        browser = MagicMock()
        page = MagicMock()
        browser.pages = [page]
        button = MagicMock()
        events = []
        button.click.side_effect = lambda **k:events.append('post')
        def comments(manifest,*a,**kwargs):
            events.append('comments')
            self.assertEqual(kwargs['only_keys'],{j['key'] for j in self.jobs})
            state = app.upload.read_json(self.root/'logs/publish_state.json',{})
            for job in self.jobs:
                if state[job['key']]['status']=='published':
                    state[job['key']]['comment_status']='sent'
            app.upload.save_json(self.root/'logs/publish_state.json',state)
        with patch('playwright.sync_api.sync_playwright'),patch.object(app.normal,'launcher_for_jobs',return_value=lambda *a:browser), \
             patch.object(app.upload,'prepare_reel',side_effect=RuntimeError('unknown editor') if preflight_error else None,return_value=(button,{})) as prepare, \
             patch.object(app.upload,'recheck_publish_identity'),patch.object(app.upload,'install_receipt_watch'), \
             patch.object(app.upload,'wait_for_receipt',side_effect=app.upload.ReceiptNeedsReview('unknown') if unknown else None,return_value='Your reel is published.'), \
             patch('safe_video_comments.resolve_published_link',return_value=('https://www.facebook.com/reel/9001','fresh_success_view_reel_link')), \
             patch.object(app.priority.daily,'backfill',side_effect=comments),patch.object(app.priority.comment_retry,'run',return_value=[]):
            result = app.execute()
        return result,button,prepare,events

    def test_exact_eight_real_core_reuses_prepared_editor_then_comments_retaining_original_records(self):
        result,button,prepare,events = self.core()
        self.assertEqual(result,0)
        self.assertEqual(button.click.call_count,8)
        self.assertEqual(prepare.call_count,8)
        self.assertEqual(events,['post']*8+['comments'])
        state = app.upload.read_json(self.root/'logs/publish_state.json',{})
        for job in self.jobs:
            row = state[job['key']]
            self.assertEqual(row['status'],'published')
            self.assertEqual(row['previous_before_post_attempt'],self.state[job['key']])
            self.assertTrue(row['post_intent_at'])
            self.assertTrue(row['today_first_retry_used'])
        for key,row in self.protected.items():
            self.assertEqual(state[key],row)
        self.assertEqual(app.upload.CONFIG.read_bytes(),self.config_before)
        self.assertEqual(self.path.read_bytes(),self.source_before)
        again,post,prep,_ = self.core()
        self.assertEqual(again,0)
        post.click.assert_not_called()
        prep.assert_not_called()

    def test_unknown_receipt_consumes_grant_and_rerun_never_posts_again(self):
        result,button,prepare,_ = self.core(unknown=True)
        self.assertEqual(result,3)
        self.assertEqual(button.click.call_count,8)
        again,button,prepare,_ = self.core()
        self.assertEqual(again,3)
        button.click.assert_not_called()
        prepare.assert_not_called()

    def test_first_editor_gate_failure_stops_other_seven_without_claim_or_state_changes(self):
        result,button,prepare,_ = self.core(preflight_error=True)
        self.assertEqual(result,3)
        self.assertEqual(prepare.call_count,1)
        button.click.assert_not_called()
        self.assertEqual(app.upload.read_json(self.root/'logs/publish_state.json',{}),self.state)
        self.assertFalse((self.root/'logs'/(app.GRANT+'-claims.json')).exists())

    def test_post_proof_in_previous_attempt_and_changed_source_are_not_retried(self):
        state = copy.deepcopy(self.state)
        job = self.jobs[0]
        state[job['key']]['previous_before_post_attempt']['post_intent_at'] = 'old submitted'
        with self.assertRaisesRegex(ValueError,'已有提交'):
            app.checked(job,state,dict(jobs={}))
        job = copy.deepcopy(job)
        job['filename'] = 'other.mp4'
        with self.assertRaises(ValueError):
            app.checked(job,self.state,dict(jobs={}))

    def test_active_upload_lock_stays_intact_and_blocks_retry(self):
        lock = self.root/'logs/upload.lock'
        lock.write_text('active uploader')
        with patch.object(app,'one') as post:
            with self.assertRaises(RuntimeError):
                app.execute()
        post.assert_not_called()
        self.assertEqual(lock.read_text(),'active uploader')

    def test_real_chromium_prepares_hidden_ai_once_then_core_uses_same_editor_for_one_post(self):
        from test_modern_editor import PROFILE,EDITOR
        from urllib.parse import urlparse
        source_path,source,jobs = app.source()
        with app.locked():
            path,value = app.plan(source_path,source,jobs)
            ledger_path,ledger = app.claims(value)
            job = jobs[0]
            entry,status = app.checked(job,self.state,ledger)
            self.assertEqual(status,'ready')
            calls = []
            browsers = []
            def factory(*args,**kwargs):
                def launch(pw,entry):
                    browser = pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
                    browsers.append(browser)
                    context = browser.new_context()
                    context.add_cookies([dict(name='c_user',value='1003',domain='.facebook.com',path='/'),
                                        dict(name='i_user',value=app.upload.target_key(entry['url'])[3:],domain='.facebook.com',path='/')])
                    context.expose_binding('testEvent',lambda source,value:calls.append(value))
                    profile = PROFILE.replace('location.href=',"window.testEvent('select');location.href=")
                    editor = EDITOR.replace('id="ai" type="checkbox"','id="ai" style="display:none" type="checkbox"')
                    editor = editor.replace('window.postClicks=(window.postClicks||0)+1',"window.testEvent('post')")
                    context.route('https://www.facebook.com/**',lambda route:route.fulfill(content_type='text/html',body=editor if urlparse(route.request.url).path=='/reels/create' else profile))
                    context.new_page()
                    return context
                return launch
            with patch.object(app.normal,'launcher_for_jobs',side_effect=factory),app.identity.scoped({('fb09',job['target'])}),app.editor.installed(), \
                 patch.object(app.sys,'platform','linux'), \
                 patch.object(app.upload,'wait_for_receipt',return_value='Your reel is published.'), \
                 patch('safe_video_comments.resolve_published_link',return_value=('https://www.facebook.com/reel/9001','fresh_success_view_reel_link')):
                app.one(job,entry,value,path,ledger_path,ledger)
            self.assertEqual(calls,['select','post'])
            state = app.upload.read_json(self.root/'logs/publish_state.json',{})
            self.assertEqual(state[job['key']]['status'],'published')
            self.assertEqual(state[job['key']]['previous_before_post_attempt'],self.state[job['key']])
            self.assertTrue(state[job['key']]['post_intent_at'])


if __name__ == '__main__':
    unittest.main()
