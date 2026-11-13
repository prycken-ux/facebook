import contextlib,copy,os,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import MagicMock,patch
import publish_distributed_nov13_first24 as app
import publish_today_20261112 as nov12
from test_publish_today_20261112 import Nov12NewVideosTests


class DistributedFirst24Tests(unittest.TestCase):
    def setUp(self):
        self.fx=Nov12NewVideosTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root
        with nov12.old.locked():
            parent,original=nov12.old_sources();nov12.ready_personals(parent)
            pointer,control=nov12.today_controller(original);nov12.prepare_wave(pointer,control,set())
        self.enterContext(patch.object(app.materials,'ROOT',self.root))
        for n in range(1,75):(self.root/'profiles'/f'fb{n:02d}').mkdir(parents=True,exist_ok=True)
        self.pool=self.root/'Nov13-total';self.pool.mkdir()
        for n in range(1,95):(self.pool/f'{n}.mp4').write_bytes(('Nov13 fresh footage '+str(n)).encode())
        self.material=app.materials.distribute(self.root,self.pool,day=app.DAY,scope='all')
        self.futures={p:p.read_bytes() for n in range(25,75) for p in (self.root/f'videos/fb{n:02d}').rglob('*') if p.is_file()}
        self.before=app.upload.read_json(self.root/'logs/publish_state.json',{})
        app.upload.save_json(self.root/'logs/frozen-material-2026-11-13-aaaaaaaaaaaaaaaa-results.json',dict(manifest='earlier-completed-retry',attempts=[]))
        self.config=app.upload.CONFIG.read_bytes()
        self.now=datetime(2026,11,13,8,tzinfo=timezone.utc);self.clocks=[]
        for module in (app,app.upload,app.batch,app.priority.retry,app.priority.comment_retry):
            clock=self.enterContext(patch.object(module,'datetime',wraps=datetime));clock.now.return_value=self.now;self.clocks.append(clock)
        self.enterContext(patch.object(app.priority.daily,'keep_awake',side_effect=contextlib.nullcontext))

    def tick(self,*args):
        self.now+=timedelta(seconds=80)
        for clock in self.clocks:clock.now.return_value=self.now
        for file in (self.root/'videos').rglob('*'):
            if file.is_file() and file.suffix in {'.mp4','.txt'}:os.utime(file,(self.now.timestamp()-180,)*2)

    def core(self,unknown=False,fail_once=False,comment_retry=False,include_new=False):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock();active={};events=[];failed=set();comment_calls=[]
        expected={(r['account'],r['target']):r['files'][-1] for r in self.material['payload']['assignments'] if r['account'] in app.ALLOWED or include_new}
        def prepare(page,entry,video,caption,**kwargs):
            pair=entry['account'],entry['target'];self.assertIn(pair,expected);self.assertEqual(video.name,expected[pair]['destination_name'])
            self.assertEqual(app.archive.info(video)['sha256'],expected[pair]['sha256']);active['pair']=pair
            if fail_once and entry['account']=='fb02' and pair not in failed:failed.add(pair);raise RuntimeError('net::ERR_CONNECTION_CLOSED')
            return button,{}
        button.click.side_effect=lambda **kwargs:events.append(('post',active['pair']))
        def backfill(value,*args,**kwargs):
            selected=kwargs['only_keys'];comment_calls.append(selected);events.append(('comment-pass',len(selected)))
            self.assertTrue(selected<={j['key'] for j in value['payload']['jobs']})
            state=app.upload.read_json(self.root/'logs/publish_state.json',{})
            for j in value['payload']['jobs']:
                if j['key'] in selected and state.get(j['key'],{}).get('status')=='published':
                    state[j['key']]['comment_status']='manual_required' if comment_retry and len(comment_calls)==1 and j['account']=='fb02' else 'sent'
            app.upload.save_json(self.root/'logs/publish_state.json',state)
        with patch.object(app.time,'sleep',side_effect=self.tick),patch.object(app.normal,'launcher_for_jobs',return_value=lambda *a:browser), \
             patch.object(app.personals,'scoped',side_effect=lambda *a:contextlib.nullcontext()),patch.object(app.numeric,'scoped',side_effect=lambda *a:contextlib.nullcontext()), \
             patch.object(app.upload,'ensure_identity',return_value={}),patch('playwright.sync_api.sync_playwright'), \
             patch.object(app,'close_selected_window'),patch.object(app.batch,'close_selected_window'),patch.object(app.upload,'prepare_reel',side_effect=prepare), \
             patch.object(app.upload,'recheck_publish_identity'),patch.object(app.upload,'install_receipt_watch'), \
             patch.object(app.upload,'wait_for_receipt',return_value='Your reel is published.',side_effect=app.upload.ReceiptNeedsReview('unknown') if unknown else None), \
             patch('safe_video_comments.resolve_published_link',return_value=('https://www.facebook.com/reel/9001','fresh_success_view_reel_link')), \
             patch.object(app.priority.daily,'backfill',side_effect=backfill), \
             patch.object(app.priority.actual,'make_finder',return_value=MagicMock(side_effect=ValueError('No unique video'))), \
             patch('builtins.input',side_effect=AssertionError('No repeated names/AI prompt')):
            result=app.execute(True)
        return result,events,comment_calls

    def test_exact_today_first44_and_old_extras_archived_fifty_deferred_and_resume_no_second_post(self):
        result,events,_=self.core();self.assertEqual(result,0)
        self.assertEqual(len([e for e in events if e[0]=='post']),44)
        self.assertTrue(all(e[0]=='post' for e in events[:44]));self.assertEqual(events[44][0],'comment-pass')
        self.assertEqual(app.upload.CONFIG.read_bytes(),self.config)
        for path,data in self.futures.items():self.assertEqual(path.read_bytes(),data)
        for pair,(filename,_) in self.fx.expected.items():
            self.assertFalse((self.root/'videos'/pair[0]/pair[1]/'inbox'/filename).exists())
        state=app.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,old in self.before.items():
            for field,value in old.items():self.assertEqual(state[key][field],value)
        result,events,_=self.core();self.assertEqual(result,0);self.assertFalse(any(e[0]=='post' for e in events))

    def test_network_failure_gets_one_retry_after_video_pass_and_failed_comment_gets_one_extra_pass(self):
        result,events,comments=self.core(fail_once=True,comment_retry=True);self.assertEqual(result,0)
        posts=[e[1] for e in events if e[0]=='post'];self.assertEqual(len(posts),44);self.assertEqual(posts[-1],('fb02','page01'))
        self.assertEqual(len(comments),2)
        claim=app.upload.read_json(self.root/'logs/automatic_before_post_retry_claims.json',{})
        self.assertEqual(len(claim['jobs']),1)

    def test_submitted_unknowns_never_reupload_and_old_history_comments_never_selected(self):
        result,events,_=self.core(unknown=True);self.assertEqual(result,3)
        self.assertEqual(sum(e[0]=='post' for e in events),44)
        result,events,_=self.core();self.assertEqual(result,3);self.assertFalse(any(e[0]=='post' for e in events))

    def test_distribution_required_and_ai_confirmation_required_before_freeze(self):
        with self.assertRaisesRegex(ValueError,'全部实拍'):app.execute(False)
        self.assertFalse((self.root/'logs'/app.POINTER).exists())
        path,_,_,_=app.distribution();progress=path.with_name(path.stem+'-progress.json')
        value=app.upload.read_json(progress,{});value['done']=[];app.upload.save_json(progress,value)
        with self.assertRaisesRegex(ValueError,'尚未全部分配'):app.execute(True)

    def test_archived_old_preparing_is_paused_without_changing_posted_old_result(self):
        path,value=app.freeze();app.archive_old(path,value)
        state=app.upload.read_json(self.root/'logs/publish_state.json',{})
        old=next((k,r) for k,r in state.items() if r.get('material_archive_video'))
        key,row=old;row.update(status='preparing',uploader_version='2.47',material_archive_date='2026-11-12');row.pop('post_intent_at',None)
        app.upload.save_json(self.root/'logs/publish_state.json',state)
        app.pause_archived_history(path,value)
        self.assertEqual(app.upload.read_json(self.root/'logs/publish_state.json',{})[key]['status'],'paused')

    def test_verified_fresh_published_metadata_recovers_receipt_timeout_without_browser_or_comment_reset(self):
        path,value=app.freeze();job=value['payload']['jobs'][0]
        state=app.upload.read_json(self.root/'logs/publish_state.json',{})
        state[job['key']]=dict(account=job['account'],target=job['target'],url=job['url'],
                              video=str(self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']),
                              created=self.now.isoformat(),post_intent_at=self.now.isoformat(),status='needs_review',
                              source_frozen_manifest=path.name,source_frozen_sha256=value['sha256'],fresh_publication_candidate='https://www.facebook.com/reel/9001',
                              fresh_publication_job_key=job['key'],fresh_publication_candidate_count=1,
                              fresh_publication_explicit_published=True,comment_status='sent')
        app.upload.save_json(self.root/'logs/publish_state.json',state)
        with patch.object(app.upload,'launch_context',side_effect=AssertionError('Passive proof needs no browser')):
            app.reconcile(path,value)
        row=app.upload.read_json(self.root/'logs/publish_state.json',{})[job['key']]
        self.assertEqual(row['status'],'published');self.assertEqual(row['confirmation_method'],'fresh_owned_published_metadata')
        self.assertEqual(row['comment_status'],'sent')

    def test_killed_before_post_uses_only_bounded_recovery_and_killed_after_post_is_not_resubmitted(self):
        path,value=app.freeze();first,second=value['payload']['jobs'][:2]
        state=app.upload.read_json(self.root/'logs/publish_state.json',{})
        for job,status in ((first,'preparing'),(second,'posting')):
            row=dict(account=job['account'],target=job['target'],url=job['url'],
                     video=str(self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']),
                     created=self.now.isoformat(),status=status,uploader_version='2.47',ai_label_requested=False,
                     source_frozen_manifest=path.name,source_frozen_sha256=value['sha256'])
            if status=='posting':row['post_intent_at']=self.now.isoformat()
            state[job['key']]=row
        app.upload.save_json(self.root/'logs/publish_state.json',state)
        result,events,_=self.core()
        self.assertEqual(result,3)
        posts=[e[1] for e in events if e[0]=='post']
        self.assertEqual(len(posts),43)
        self.assertIn((first['account'],first['target']),posts)
        self.assertNotIn((second['account'],second['target']),posts)


if __name__=='__main__':unittest.main()
