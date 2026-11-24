import hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import start_publish_eligible60_real_20261123 as starter
import publish_eligible60_real_20261123 as driver

class StartNov23Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'logs').mkdir();(self.root/'upload_config.json').write_text('{}')
        (self.root/'logs/upload.lock').write_bytes(b'old20-task-active')
        (self.root/'.venv/Scripts').mkdir(parents=True);(self.root/'.venv/Scripts/python.exe').write_bytes(b'fixture')
        (self.root/'material-staging').mkdir();self.pointer=self.root/driver.POINTER;self.pointer.write_text('{"complete":true}')
        self.updates={n:b'# fixture verified runtime\n' for n in starter.NAMES}
    def run_start(self,launch):
        with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download',return_value=self.updates), \
             patch.object(starter.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(starter.subprocess,'Popen',side_effect=launch):
            return starter.start(self.root)
    def acknowledge(self,environment,phase='running',message='started',pid=999,launch_id=None):
        token=environment['FB_PUBLISH_LAUNCH_ID']
        path=self.root/'logs'/('eligible60-2026-11-23-worker-'+token+'.json')
        path.write_text(json.dumps(dict(pid=pid,phase=phase,message=message,material_date='2026-11-23',launch_id=launch_id or token)))
    def test_direct_launch_uses_null_input_new_group_and_actual_venv_worker_ack(self):
        def launch(args,**kwargs):
            self.assertEqual(args[0],str(self.root/'.venv/Scripts/python.exe'));self.assertIn('-u',args)
            self.assertEqual(kwargs['creationflags'],0x08000200);self.assertEqual(kwargs['stdin'],subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'],subprocess.STDOUT);self.assertTrue(hasattr(kwargs['stdout'],'write'))
            environment=kwargs['env'];self.assertEqual(environment['FB_PUBLISH_ISOLATED_BACKGROUND'],'1');self.assertEqual(environment['FB_PUBLISH_FILE_LOG_ONLY'],'1')
            self.acknowledge(environment,pid=999)
            p=MagicMock(pid=777);p.poll.return_value=None;return p
        self.assertEqual(self.run_start(launch),0)
        self.assertEqual((self.root/'logs/upload.lock').read_bytes(),b'old20-task-active')
        self.assertFalse((self.root/starter.DRIVER_NAME).exists())
    def test_worker_busy_error_does_not_replace_existing_publisher_status(self):
        queue=self.root/'logs/eligible60-2026-11-23-queue.json';queue.write_text('{"pid":111,"phase":"running","launch_id":"older"}');before=queue.read_bytes()
        def launch(args,**kwargs):
            self.acknowledge(kwargs['env'],'failed','原发布任务仍在运行')
            p=MagicMock(pid=777);p.poll.return_value=1;return p
        with self.assertRaisesRegex(RuntimeError,'原发布任务仍在运行'):self.run_start(launch)
        self.assertEqual(queue.read_bytes(),before)
    def test_native_startup_failure_includes_exit_code_and_captured_error(self):
        def launch(args,**kwargs):
            kwargs['stdout'].write(b'fixture native startup error\n')
            p=MagicMock(pid=777);p.poll.return_value=17;return p
        with self.assertRaisesRegex(RuntimeError,'(?s)退出码：17.*启动诊断：.*fixture native startup error'):self.run_start(launch)
    def test_pid_match_without_launch_nonce_is_not_confirmation(self):
        def launch(args,**kwargs):
            self.acknowledge(kwargs['env'],pid=777,launch_id='f'*32)
            p=MagicMock(pid=777);p.poll.return_value=1;return p
        with self.assertRaisesRegex(RuntimeError,'未收到后台发布核验回执'):self.run_start(launch)
    def test_incomplete_distribution_does_not_start_a_python_waiter(self):
        self.pointer.write_text('{"complete":false}')
        with patch.object(starter.sys,'platform','win32'),patch.object(starter.subprocess,'Popen',side_effect=AssertionError('No waiter')):
            with self.assertRaisesRegex(ValueError,'正式分配尚未完成'):starter.start(self.root)
    def test_changed_immutable_cache_blocks_process_start(self):
        folder=self.root/'material-staging/tools'/starter.RUNTIME_SHA[:16];folder.mkdir(parents=True)
        (folder/starter.NAMES[0]).write_bytes(b'changed')
        with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download',return_value=self.updates),patch.object(starter.subprocess,'Popen',side_effect=AssertionError('No process')):
            with self.assertRaisesRegex(ValueError,'同指纹'):starter.start(self.root)
    def test_embedded_programs_match_reviewed_source(self):
        self.assertEqual(starter.DRIVER,Path(driver.__file__).read_bytes());self.assertEqual(starter.DRIVER_SHA,hashlib.sha256(starter.DRIVER).hexdigest())
        self.assertEqual(starter.RUNTIME_SHA,hashlib.sha256(starter.PACKAGE_SHA.encode()+starter.DRIVER+starter.QUEUE).hexdigest())
    def test_direct_launch_parent_chain_is_exempt_but_sibling_is_blocked(self):
        from test_nov16_venv_process_chain import VenvProcessChainTests
        f=VenvProcessChainTests();f.setUp()
        entry=f.root+r'\material-staging\tools\abc123\publish_eligible60_real_20261123.py'
        body=f.body.replace('start_finish_first24_nov16','start_publish_eligible60_real_20261123').replace('verified-nov16-first24-and-nov14-stage','verified-real-eligible60-nov23-publication')
        run=['-u',entry,f.root];boot=['-u','-c',body,f.root]
        rows=[f.row(100,99,run,runtime=True),f.row(99,98,run),f.row(98,97,boot,runtime=True),f.row(97,96,boot)]
        with patch.object(driver.app.workers,'BOOTSTRAP',driver.BOOTSTRAP):
            workers,allowed=driver.app.workers.classify_workers(rows,f.root,100,entry)
            self.assertEqual(workers,[]);self.assertEqual(allowed,[97,98,99,100])
            workers,allowed=driver.app.workers.classify_workers(rows+[f.row(101,1,run)],f.root,100,entry)
            self.assertEqual([w['pid'] for w in workers],[101])

if __name__=='__main__':unittest.main()
