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
        self.updates={n:b'# fixture verified runtime\n' for n in starter.NAMES}
    def test_background_queue_does_not_hold_python_wait_or_touch_old_lock(self):
        process=MagicMock(pid=777);process.poll.return_value=None
        def launch(args,**kwargs):
            self.assertEqual(args[0],'powershell.exe');self.assertIn('Hidden',args);self.assertIn('-File',args)
            self.assertEqual(kwargs['creationflags'],0x208)
            self.assertTrue(kwargs['creationflags'] & 0x8)
            self.assertTrue(kwargs['creationflags'] & 0x200)
            (self.root/'logs/eligible60-2026-11-23-queue.json').write_text(json.dumps(dict(pid=777,phase='waiting_workers',message='waiting old20')))
            return process
        with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download',return_value=self.updates), \
             patch.object(starter.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(starter.subprocess,'Popen',side_effect=launch) as spawn:
            self.assertEqual(starter.start(self.root),0);self.assertEqual(spawn.call_count,1)
        self.assertEqual((self.root/'logs/upload.lock').read_bytes(),b'old20-task-active')
        self.assertFalse((self.root/starter.DRIVER_NAME).exists())
    def test_duplicate_queue_retains_existing_task(self):
        (self.root/'logs/eligible60-2026-11-23-queue.json').write_text(json.dumps(dict(pid=111,phase='waiting_distribution')))
        process=MagicMock(pid=777);process.poll.return_value=0;process.returncode=0
        with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download',return_value=self.updates), \
             patch.object(starter.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(starter.subprocess,'Popen',return_value=process):
            self.assertEqual(starter.start(self.root),0)
    def test_changed_immutable_cache_blocks_queue_start(self):
        folder=self.root/'material-staging/tools'/starter.RUNTIME_SHA[:16];folder.mkdir(parents=True)
        (folder/starter.NAMES[0]).write_bytes(b'changed')
        with patch.object(starter.sys,'platform','win32'),patch.object(starter,'download',return_value=self.updates),patch.object(starter.subprocess,'Popen',side_effect=AssertionError('No queue')):
            with self.assertRaisesRegex(ValueError,'同指纹'):starter.start(self.root)
    def test_embedded_programs_are_reviewed_bytes_and_power_shell_51_utf8(self):
        self.assertEqual(starter.DRIVER,Path(driver.__file__).read_bytes());self.assertEqual(starter.DRIVER_SHA,hashlib.sha256(starter.DRIVER).hexdigest())
        self.assertEqual(starter.QUEUE,Path(driver.__file__).with_name(starter.QUEUE_NAME).read_bytes());self.assertTrue(starter.QUEUE.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(starter.RUNTIME_SHA,hashlib.sha256(starter.PACKAGE_SHA.encode()+starter.DRIVER+starter.QUEUE).hexdigest())

if __name__=='__main__':unittest.main()
