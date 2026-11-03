import contextlib,copy,hashlib,io,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import add_fb_accounts
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import confirm_verify_nov02_20261103 as verify


class ConfirmVerifyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'logs').mkdir();self.stack=contextlib.ExitStack()
        for module,name,value in [(upload,'ROOT',self.root),(upload,'CONFIG',self.root/'upload_config.json'),(add_fb_accounts,'ROOT',self.root)]:self.stack.enter_context(patch.object(module,name,value))
        self.output=self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()));self.entries=[];self.jobs=[];self.state={};user={};online={}
        for i,pair in enumerate(sorted(daily.EXPECTED_PAIRS)):
            key=hashlib.sha256(('/'.join(pair)+'-nov02').encode()).hexdigest()
            entry=dict(account=pair[0],target=pair[1],type='personal' if pair[1]=='personal' else 'page',name='Example '+str(i),url='https://www.facebook.com/profile.php?id='+str(1000+i),enabled=False)
            if entry['type']=='personal':entry['workflow']='personal_recording_v1'
            job=dict(account=pair[0],target=pair[1],key=key,filename=pair[0]+'_'+pair[1]+'.mp4',url=entry['url'],caption_text='Exact caption '+str(i))
            self.jobs.append(job);self.entries.append(entry)
            if pair==('fb02','page01'):continue
            status='published';method='fresh_success_ui_and_composer_closed'
            if pair in verify.USER_CONFIRMED:user[pair]=key[:12];status='needs_review';method=''
            elif pair in verify.VERIFY:online[pair]=key[:12];status='needs_review';method=''
            elif pair==('fb04','personal'):status='failed_before_post';method=''
            self.state[key]=dict(account=pair[0],target=pair[1],url=entry['url'],video='E:\\original\\'+job['filename'],status=status,
                created='2026-11-02T18:40:00+08:00',post_intent_at='2026-11-02T18:47:00+08:00',error='original timeout' if status=='needs_review' else '',
                confirmation_method=method,comment_status='not_started')
        self.stack.enter_context(patch.object(verify,'USER_CONFIRMED',user));self.stack.enter_context(patch.object(verify,'VERIFY',online))
        payload=dict(schema=batch.SCHEMA,date='2026-11-02',jobs=self.jobs);value=dict(payload=payload,sha256=batch.digest(payload),report_format='text')
        self.stack.enter_context(patch.object(verify,'PREFIX',value['sha256'][:8]));self.source=self.root/'logs'/('frozen-material-2026-11-02-'+value['sha256'][:16]+'.json');upload.save_json(self.source,value)
        upload.save_json(self.source.with_name(self.source.stem+'-results.json'),dict(manifest=self.source.name,attempts=[]))
        upload.save_json(upload.CONFIG,dict(targets=self.entries));self.state_path=self.root/'logs/publish_state.json';upload.save_json(self.state_path,self.state)
        upload.save_json(self.root/'logs/video_comments.json',dict(protected='unchanged'));upload.save_json(self.root/'logs/automatic_before_post_retry_claims.json',dict(protected='unchanged'))
        self.original=copy.deepcopy(self.state);self.config_before=upload.CONFIG.read_bytes();self.comment_before=(self.root/'logs/video_comments.json').read_bytes();self.retry_before=(self.root/'logs/automatic_before_post_retry_claims.json').read_bytes()
        self.stack.enter_context(patch.object(upload,'run_entry',side_effect=AssertionError('no uploads')));self.stack.enter_context(patch.object(upload,'archive',side_effect=AssertionError('no media moves')));self.stack.enter_context(patch.object(daily,'backfill',side_effect=AssertionError('no comments')))
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def job(self,pair):return next(j for j in self.jobs if (j['account'],j['target'])==pair)
    def browser_run(self,effects):
        context=MagicMock()
        with patch('playwright.sync_api.sync_playwright'),patch.object(verify,'close_selected_window') as close,patch.object(upload,'launch_context',return_value=context),patch.object(verify,'online_verify',side_effect=effects):
            results=verify.execute()
        self.assertTrue(all(c.args==('fb10',) for c in close.call_args_list));return results
    def test_user_confirmations_plus_verified_two_mark_28_with_distinct_sources_and_no_other_changes(self):
        self.assertEqual(len(verify.USER_CONFIRMED),13);self.assertEqual(len(verify.VERIFY),2)
        self.browser_run([('https://www.facebook.com/reel/9007','exact-proof'),('https://www.facebook.com/reel/9008','exact-proof')])
        state=upload.read_json(self.state_path,{})
        self.assertEqual(sum(r['status']=='published' for r in state.values()),28)
        for pair in verify.USER_CONFIRMED:
            row=state[self.job(pair)['key']];self.assertEqual(row['confirmation_method'],verify.USER_METHOD);self.assertNotIn('permalink',row);self.assertNotIn('published_at',row)
        for pair in verify.VERIFY:
            key=self.job(pair)['key'];row=state[key];self.assertEqual(row['confirmation_method'],verify.ONLINE_METHOD);self.assertEqual(row['comment_link_job_key'],key);self.assertTrue(row['permalink'])
        selected={self.job(p)['key'] for p in list(verify.USER_CONFIRMED)+list(verify.VERIFY)}
        for key,row in self.original.items():
            if key not in selected:self.assertEqual(state[key],row)
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before);self.assertEqual((self.root/'logs/video_comments.json').read_bytes(),self.comment_before);self.assertEqual((self.root/'logs/automatic_before_post_retry_claims.json').read_bytes(),self.retry_before)
        self.assertTrue(list((self.root/'backups').glob('*/publish_state.json')))
        report=upload.read_json(self.source.with_name(self.source.stem+'-results.json'),{});self.assertEqual(sum(r['video_status']=='published' for r in report['rows']),28)
        self.assertFalse(list(self.root.rglob('*.csv')))
        with patch.object(upload,'launch_context',side_effect=AssertionError('already confirmed must not reopen')):verify.execute()
        self.assertEqual(upload.read_json(self.state_path,{}),state)
    def test_loading_or_wrong_link_keeps_target_pending_but_records_user_confirmations(self):
        self.browser_run([RuntimeError('Loading remained'),('https://outside.example/reel/9','bad-proof')])
        state=upload.read_json(self.state_path,{})
        for pair in verify.VERIFY:
            key=self.job(pair)['key'];self.assertEqual(state[key],self.original[key])
        self.assertEqual(sum(r['status']=='published' for r in state.values()),26)
    def test_source_tampering_aborts_before_status_changes(self):
        value=upload.read_json(self.source,{});value['payload']['jobs'][0]['caption_text']='tampered';upload.save_json(self.source,value)
        with self.assertRaises(ValueError):verify.execute()
        self.assertEqual(upload.read_json(self.state_path,{}),self.original)
    def test_wrong_record_or_missing_timezone_cannot_be_confirmed(self):
        job=self.job(next(iter(verify.USER_CONFIRMED)));state=copy.deepcopy(self.state);state[job['key']]['video']='E:\\other.mp4'
        with self.assertRaises(ValueError):verify.mark(state,job,self.source,verify.USER_METHOD,[])
        state=copy.deepcopy(self.state);state[job['key']]['post_intent_at']='2026-11-02T18:47:00'
        with self.assertRaises(ValueError):verify.mark(state,job,self.source,verify.USER_METHOD,[])
        self.assertEqual(state[job['key']]['status'],'needs_review')
    def test_online_proof_requires_same_video_after_navigation_and_exact_author(self):
        job=self.job(('fb10','page07'));entry=next(e for e in self.entries if e['target']=='page07');row=self.state[job['key']];page=MagicMock();page.url='https://www.facebook.com/reel/9007?locale=en_US'
        with patch.object(verify.lookup,'find_published',return_value=('https://www.facebook.com/reel/9007','exact')) as search,patch.object(verify.comments,'require_video_author') as author,patch.object(upload,'checkpoint'),patch.object(upload,'require_no_advanced_protection'):
            self.assertEqual(verify.online_verify(page,MagicMock(),entry,job,row)[0],'https://www.facebook.com/reel/9007');author.assert_called_once();self.assertEqual(search.call_args.args[3],job['caption_text'])
            page.url='https://www.facebook.com/reel/9999'
            with self.assertRaises(ValueError):verify.online_verify(page,MagicMock(),entry,job,row)
