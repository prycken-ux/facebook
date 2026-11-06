import base64,copy,json,os,re,subprocess,time,unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch
from xml.etree import ElementTree as ET
import fb_upload as upload
import scheduled_priority_workflow as runner
import test_scheduled_material_batch as fixtures


class ScheduledPriorityTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ScheduledMaterialTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.now=datetime(2026,11,6,8,tzinfo=timezone.utc)
        self.f.stack.enter_context(patch.object(runner,'datetime',wraps=datetime));runner.datetime.now.return_value=self.now
        self.previous=self.f.stack.enter_context(patch.object(runner.previous,'execute'))
        self.registration=self.f.stack.enter_context(patch.object(runner,'register',return_value='test exact task'))
    def setup_plan(self):return runner.setup(True)
    def test_setup_only_registers_at_17_no_browser_no_upload_and_resume_same_manifest(self):
        with patch.object(upload,'launch_context',side_effect=AssertionError('setup cannot open browser')),patch.object(upload,'run_entry',side_effect=AssertionError('no upload before task')):
            path,value=self.setup_plan();first=self.f.videos[('fb01','page01')];(first.parent/'later.mp4').write_bytes(b'added after freezing')
            self.assertEqual(self.setup_plan(),(path,value))
        self.assertEqual(value['payload']['start'],'2026-11-06T17:00:00+08:00');self.assertFalse(value['payload']['ai_label'])
        self.assertEqual(self.registration.call_count,2);self.previous.assert_called()
        self.assertTrue(all(j['filename']!='later.mp4' for j in value['payload']['jobs']))
        self.assertEqual(upload.CONFIG.read_bytes(),self.f.config_before)
    def test_one_time_task_action_runs_entire_priority_driver_without_daily_trigger(self):
        path,value=self.setup_plan();root=ET.fromstring(runner.task_xml(path,value));ns={'t':runner.batch.NS}
        self.assertEqual(root.find('t:Triggers/t:TimeTrigger/t:StartBoundary',ns).text,'2026-11-06T17:00:00+08:00')
        args=root.find('t:Actions/t:Exec/t:Arguments',ns).text
        self.assertIn('scheduled_priority_workflow.py',args);self.assertIn('run --manifest',args);self.assertIn(str(path),args)
        self.assertNotIn('scheduled_material_batch.py',args);self.assertEqual(root.findall('t:Triggers/t:CalendarTrigger',ns),[])
        self.assertEqual(root.find('t:Settings/t:AllowHardTerminate',ns).text,'false')
        self.assertEqual(root.find('t:Settings/t:ExecutionTimeLimit',ns).text,'PT0S')
    def test_registry_script_checks_conflicts_existing_exact_action_and_never_forces_running_tasks(self):
        path,value=self.setup_plan()
        name='FBUpload-Priority-Once-20261106-'+value['sha256'][:8]
        with patch.object(runner.sys,'platform','win32'),patch.object(runner.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(dict(TaskName=name,State='Ready')),'')) as call:
            original=ORIGINAL_REGISTER;name=original(path,value)
        script=call.call_args.args[0][-1];data=json.loads(base64.b64decode(re.search("FromBase64String\\('([^']+)'",script)[1]))
        self.assertIn('Priority-Once-20261106',name);self.assertEqual(data['start'],value['payload']['start'])
        self.assertIn('MSFT_TaskTimeTrigger',script);self.assertIn('Another upload task is running',script)
        self.assertIn('Unrecognized upload schedule action requires review',script);self.assertIn('Disable-ScheduledTask',script)
        self.assertIn('Export-ScheduledTask',script);self.assertIn("$xml.Task.Settings.Enabled='false'",script)
        self.assertNotIn('Stop-ScheduledTask',script);self.assertNotIn('Stop-Process',script);self.assertIn('Arguments -ne $d.arguments',script)
    def test_worker_uses_normal_local_file_adapter_then_real_upload_retry_comment_order(self):
        path,value=self.setup_plan();events=[];original=upload.launch_context;original_prepare=runner.priority.prepare
        runner.datetime.now.return_value=datetime(2026,11,6,9,1,tzinfo=timezone.utc)
        with patch.object(runner.priority,'datetime',wraps=datetime) as clock,patch.object(runner.batch,'run',side_effect=lambda *a,**k:events.append('uploads')),patch.object(runner.retry,'run',side_effect=lambda *a,**k:events.append('retry')),patch.object(runner.daily,'backfill',side_effect=lambda *a,**k:events.append('comments')) as comments,patch.object(runner.local,'self_check') as selfcheck,patch.object(runner,'close_selected_window'),patch('playwright.sync_api.sync_playwright'),patch.object(runner.normal,'launcher_for_jobs',return_value=MagicMock()) as launch:
            clock.now.return_value=datetime(2026,11,6,9,1,tzinfo=timezone.utc)
            self.assertEqual(runner.run(path),3)
        self.assertEqual(events,['uploads','retry','comments']);selfcheck.assert_called_once();launch.assert_called_once_with(value['payload']['jobs'])
        self.assertTrue(comments.call_args.kwargs['future_only']);self.assertIs(upload.launch_context,original);self.assertIs(runner.priority.prepare,original_prepare)
    def test_expired_worker_policy_changes_unconfirmed_and_active_setup_are_blocked(self):
        with self.assertRaises(ValueError):runner.setup(False)
        self.previous.assert_not_called();path,value=self.setup_plan();runner.datetime.now.return_value=datetime(2026,11,7,8,tzinfo=timezone.utc)
        with self.assertRaises(ValueError):runner.run(path)
        with self.assertRaises(ValueError):runner.setup(True)
        runner.datetime.now.return_value=self.now;policy=upload.read_json(self.f.root/'publication_preferences.json',{});policy['payload']['caption']='changed policy';policy['sha256']=runner.preferences.digest(policy['payload']);upload.save_json(self.f.root/'publication_preferences.json',policy)
        with self.assertRaises(ValueError):runner.run(path)

    def test_full_core_pass_then_single_retry_then_reload_verified_comments_with_new_policy(self):
        path,value=self.setup_plan();events=[];attempts={};active={};browser=MagicMock();page=MagicMock();browser.pages=[page];button=MagicMock()
        for file in self.f.root.rglob('*.txt'):os.utime(file,(time.time()-180,time.time()-180))
        def prepare(page,entry,video,caption,**kwargs):
            pair=entry['account'],entry['target'];active['pair']=pair;attempts[pair]=attempts.get(pair,0)+1;events.append(('prepare',pair))
            self.assertEqual(caption,runner.preferences.CAPTION)
            if pair==('fb01','page01') and attempts[pair]==1:
                page._fb_upload_stage='fill_caption';raise RuntimeError('Locator.fill: Timeout 30000ms exceeded.')
            return button,{}
        button.click.side_effect=lambda **kwargs:events.append(('post',active['pair']))
        def receipt(*args,**kwargs):
            if active['pair']==('fb10','personal'):raise upload.ReceiptNeedsReview('publication receipt not confirmed')
            return 'Your reel is published.'
        def comment(page,context,entry,proof,key,record,text,collector,**kwargs):
            self.assertEqual(sum(e[0]=='prepare' for e in events),5);self.assertEqual(record['status'],'published')
            self.assertTrue(kwargs['require_reload_verification']);self.assertEqual(kwargs['verified_link'][1],'previously_verified_exact_job_link')
            events.append(('comment',(entry['account'],entry['target'])));return dict(status='verifying',permalink=record['permalink'])
        with patch.object(runner,'datetime',wraps=datetime) as rc,patch.object(runner.priority,'datetime',wraps=datetime) as pc,patch.object(runner.batch,'datetime',wraps=datetime) as bc,patch.object(runner.retry,'datetime',wraps=datetime) as ac,patch('playwright.sync_api.sync_playwright'),patch.object(runner.normal,'launcher_for_jobs',return_value=lambda *a:browser),patch.object(runner.local,'self_check'),patch.object(runner,'close_selected_window'),patch.object(runner.batch,'close_selected_window'),patch.object(runner.daily,'close_selected_window'),patch.object(upload,'prepare_reel',side_effect=prepare),patch.object(upload,'recheck_publish_identity'),patch.object(upload,'ensure_identity'),patch.object(upload,'install_receipt_watch'),patch.object(upload,'wait_for_receipt',side_effect=receipt),patch('safe_video_comments.resolve_published_link',return_value=('https://www.facebook.com/reel/9001','fresh_success_view_reel_link')),patch('safe_video_comments.after_publication',side_effect=comment) as send,patch('safe_video_comments.verify_after_reload',side_effect=lambda *a:dict(a[-1],status='sent')):
            for clock in (rc,pc,bc,ac):clock.now.return_value=datetime(2026,11,6,9,1,tzinfo=timezone.utc)
            self.assertEqual(runner.run(path),3)
            self.assertEqual(button.click.call_count,4);self.assertEqual(send.call_count,3)
            self.assertEqual(attempts[('fb01','page01')],2);self.assertEqual(attempts[('fb10','personal')],1)
            state=upload.read_json(self.f.state_path,{})
            self.assertEqual(sum(r['status']=='published' for r in state.values()),3)
            self.assertEqual(sum(r.get('comment_status')=='sent' for r in state.values()),3)
            self.assertTrue(next(r for r in state.values() if r['account']=='fb01')['today_first_retry_used'])
            with patch.object(upload,'run_entry') as post:
                self.assertEqual(runner.run(path),3)
            post.assert_not_called();self.assertEqual(send.call_count,3)


ORIGINAL_REGISTER=runner.register
