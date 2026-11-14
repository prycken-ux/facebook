import contextlib,copy,shutil,unittest
from datetime import datetime
from unittest.mock import MagicMock,patch
import retry_nov13_prepost_fifteen_on_nov14 as app
from test_resume_nov13_two_waves_on_nov14 import CrossDayResumeTests


class ExplicitFifteenTests(unittest.TestCase):
    def setUp(self):
        self.fx=CrossDayResumeTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root;self.first=app.first;self.fx.advance_day();self.fx.run_resume()
        self.distributed=self.fx.fx.fx
        self.clock=self.enterContext(patch.object(app,'datetime',wraps=datetime));self.clock.now.return_value=self.distributed.now
        pointer=self.first.upload.read_json(self.root/'logs'/app.resume.FIRST_POINTER,{})
        control=self.first.upload.read_json(self.root/'logs'/app.resume.CONTROL,{})
        self.parents=[self.root/'logs'/pointer['manifest']]+[self.root/'logs'/r['manifest'] for r in control['waves']]
        self.alljobs={};self.origins={}
        for path in self.parents:
            value=self.first.archive.checked_json(path)
            for j in value['payload']['jobs']:
                self.alljobs[j['account'],j['target']]=j;self.origins[j['key']]=dict(source_frozen_manifest=path.name,source_frozen_sha256=value['sha256'])
        self.jobs=[self.alljobs[pair] for pair in app.SPEC]
        self.enterContext(patch.object(app,'SPEC',{(j['account'],j['target']):(j['filename'],j['key'][:12]) for j in self.jobs}))
        state=self.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for j in self.jobs:
            old=state[j['key']];video=self.root/'videos'/j['account']/j['target']/'inbox'/j['filename'];video.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(old['archived_video'],video);shutil.copy2(old['archived_caption'],video.with_suffix('.txt'))
            state[j['key']]=dict(account=j['account'],target=j['target'],url=j['url'],video=str(video),created=self.distributed.now.isoformat(),
                                 status='failed_before_post',uploader_version='2.47',ai_label_requested=False,error='缺少唯一的登录者身份',**self.origins[j['key']])
        self.first.upload.save_json(self.root/'logs/publish_state.json',state);self.before=copy.deepcopy(state)
        self.original_parents={p:p.read_bytes() for p in self.parents}
        self.protected=self.root/'videos/fb74/personal/inbox/new-nov14.mp4';self.protected.parent.mkdir(parents=True,exist_ok=True);self.protected.write_bytes(b'never publish new material')
        self.first.upload.save_json(self.root/'logs/video_comments.json',{'historical':{'status':'sent'}})
        self.comment_bytes=(self.root/'logs/video_comments.json').read_bytes()

    def core(self,unknown=False,interrupt=False,session_failure=False,fail_prepost=False):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock();active={};posts=[];comment_keys=[]
        def prepare(page,entry,video,caption,**kwargs):
            pair=entry['account'],entry['target'];self.assertIn(pair,app.SPEC);active['pair']=pair
            j=self.alljobs[pair];self.assertEqual(video.name,j['filename']);self.assertEqual(self.first.archive.info(video)['sha256'],j['video_sha256'])
            if fail_prepost:raise RuntimeError('identity unavailable before Post')
            return button,{}
        def click(**kwargs):
            posts.append(active['pair'])
            if interrupt:raise KeyboardInterrupt
        button.click.side_effect=click
        def backfill(value,*args,**kwargs):
            keys=kwargs['only_keys'];comment_keys.append(keys)
            self.assertTrue(keys<={j['key'] for j in self.jobs})
            state=self.first.upload.read_json(self.root/'logs/publish_state.json',{})
            for key in keys:
                if state.get(key,{}).get('status')=='published':state[key]['comment_status']='sent'
            self.first.upload.save_json(self.root/'logs/publish_state.json',state)
        with patch.object(self.first.normal,'launcher_for_jobs',return_value=lambda *args:browser), \
             patch('playwright.sync_api.sync_playwright'),patch.object(self.first,'close_selected_window'), \
             patch.object(self.first.personals,'scoped',side_effect=lambda *args:contextlib.nullcontext()), \
             patch.object(self.first.numeric,'scoped',side_effect=lambda *args:contextlib.nullcontext()), \
             patch.object(self.first.upload,'ensure_identity',return_value={}), \
             patch.object(app,'ensure_background_identity',side_effect=lambda previous,page,entry:previous(page,entry)), \
             patch.object(app,'wait_session',side_effect=app.SessionNotReady('missing session') if session_failure else None), \
             patch.object(self.first.upload,'prepare_reel',side_effect=prepare),patch.object(self.first.upload,'recheck_publish_identity'), \
             patch.object(self.first.upload,'install_receipt_watch'), \
             patch.object(self.first.upload,'wait_for_receipt',return_value='Your reel is published.',side_effect=self.first.upload.ReceiptNeedsReview('unknown') if unknown else None), \
             patch('safe_video_comments.resolve_published_link',return_value=('https://www.facebook.com/reel/9001','fresh_success_view_reel_link')), \
             patch.object(self.first.priority.daily,'backfill',side_effect=backfill), \
             patch.object(self.first.priority.actual,'make_finder',return_value=MagicMock(side_effect=ValueError('No unique match'))), \
             patch('builtins.input',side_effect=AssertionError('No repeated names/AI/manual prompt')):
            if interrupt:
                with self.assertRaises(KeyboardInterrupt):app.execute()
                result=130
            else:result=app.execute()
        return result,posts,comment_keys

    def test_exact_fifteen_once_with_original_comments_and_preserve_every_other_task(self):
        result,posts,comments=self.core();self.assertEqual(result,0);self.assertEqual(set(posts),set(app.SPEC));self.assertEqual(len(posts),15)
        self.assertTrue(all(int(a[2:])<=24 for a,t in posts[:12]));self.assertEqual(posts[0],('fb09','personal'))
        state=self.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in self.before.items():
            if key not in {j['key'] for j in self.jobs}:self.assertEqual(state[key],row)
        for j in self.jobs:
            row=state[j['key']];self.assertEqual(row['status'],'published');self.assertEqual(row['comment_status'],'sent')
            self.assertEqual(row['previous_before_post_attempt']['repair_previous_attempt'],self.before[j['key']])
        for path,data in self.original_parents.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(self.protected.read_bytes(),b'never publish new material')
        self.assertEqual((self.root/'logs/video_comments.json').read_bytes(),self.comment_bytes)
        _,posts,_=self.core();self.assertEqual(posts,[])

    def test_unknown_results_never_reposted_or_commented_and_partial_interrupt_resumes_remaining_only(self):
        result,posts,_=self.core(interrupt=True);self.assertEqual(len(posts),1)
        result,posts,comments=self.core(unknown=True);self.assertEqual(result,3);self.assertEqual(len(posts),14)
        result,posts,_=self.core(unknown=True);self.assertEqual(posts,[])
        state=self.first.upload.read_json(self.root/'logs/publish_state.json',{})
        self.assertTrue(all(state[j['key']]['status']=='needs_review' for j in self.jobs))

    def test_nested_submission_and_new_success_never_granted_or_selected_for_comments(self):
        first,second=self.jobs[:2];state=copy.deepcopy(self.before)
        state[first['key']]['previous_before_post_attempt']={'post_intent_at':self.distributed.now.isoformat()}
        state[second['key']].update(status='published',post_intent_at=self.distributed.now.isoformat(),comment_status='needs_review')
        self.first.upload.save_json(self.root/'logs/publish_state.json',state)
        result,posts,comments=self.core();self.assertEqual(len(posts),13)
        self.assertNotIn((first['account'],first['target']),posts);self.assertNotIn((second['account'],second['target']),posts)
        self.assertTrue(all(first['key'] not in c and second['key'] not in c for c in comments))
        current=self.first.upload.read_json(self.root/'logs/publish_state.json',{})
        self.assertEqual(current[first['key']],state[first['key']]);self.assertEqual(current[second['key']],state[second['key']])

    def test_session_not_ready_restores_exact_original_record_and_changed_file_is_not_substituted(self):
        result,posts,_=self.core(session_failure=True);self.assertEqual(posts,[])
        self.assertEqual(self.first.upload.read_json(self.root/'logs/publish_state.json',{}),self.before)
        j=self.jobs[0];file=self.root/'videos'/j['account']/j['target']/'inbox'/j['filename'];file.write_bytes(b'changed')
        result,posts,_=self.core();self.assertEqual(len(posts),14);self.assertNotIn((j['account'],j['target']),posts)

    def test_original_frozen_or_log_fingerprint_mismatch_aborts_before_post(self):
        specs=copy.deepcopy(app.SPEC);pair=next(iter(specs));specs[pair]=(specs[pair][0],'f'*12)
        with patch.object(app,'SPEC',specs):
            with self.assertRaisesRegex(ValueError,'任务指纹'):self.core()
        self.assertEqual(self.first.upload.read_json(self.root/'logs/publish_state.json',{}),self.before)


class SessionGateTests(unittest.TestCase):
    def test_cookie_load_wait_has_no_identity_bypass_and_multiple_or_checkpoint_stop(self):
        page=MagicMock();page.context.cookies.side_effect=[[],[dict(name='c_user',value='1001')],[dict(name='c_user',value='1001')]]
        with patch.object(app.first.upload,'checkpoint'),patch.object(app.first.upload,'require_no_advanced_protection'):
            self.assertTrue(app.wait_session(page));page.wait_for_timeout.assert_called_once()
            page.context.cookies.side_effect=None;page.context.cookies.return_value=[dict(name='c_user',value='1001'),dict(name='c_user',value='2002')]
            with self.assertRaises(app.SessionNotReady):app.wait_session(page)
            page.context.cookies.return_value=[]
            with self.assertRaises(app.SessionNotReady):app.wait_session(page,timeout_ms=0)
        with patch.object(app.first.upload,'checkpoint',side_effect=RuntimeError('login checkpoint')):
            with self.assertRaisesRegex(RuntimeError,'login checkpoint'):app.wait_session(page)
    def test_auto_switch_personal_keeps_login_owner_and_never_asks_for_input(self):
        entry=dict(type='personal',auto_switch_personal=True);previous=MagicMock(return_value={'verified':True});page=MagicMock()
        with patch.object(app.first.upload,'personal_actor_fingerprint',side_effect=app.first.upload.PageActorActive), \
             patch.object(app.first.numeric.picker,'login_marker',side_effect=['same','same']), \
             patch.object(app.first.numeric.picker,'switch_personal_from_picker') as switch:
            self.assertEqual(app.ensure_background_identity(previous,page,entry),{'verified':True});switch.assert_called_once()
        with patch.object(app.first.upload,'personal_actor_fingerprint',side_effect=app.first.upload.PageActorActive), \
             patch.object(app.first.numeric.picker,'login_marker',side_effect=['one','different']),patch.object(app.first.numeric.picker,'switch_personal_from_picker'):
            with self.assertRaisesRegex(RuntimeError,'登录者变化'):app.ensure_background_identity(previous,page,entry)


if __name__=='__main__':unittest.main()
