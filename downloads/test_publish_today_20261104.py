import contextlib,copy,io,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch,MagicMock
import publish_today_20261104 as today
import fb_upload as upload
import add_fb_accounts as legacy


class TodayNormalBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(upload,'ROOT',self.root));self.stack.enter_context(patch.object(legacy,'ROOT',self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        clock=self.stack.enter_context(patch.object(today,'datetime',wraps=datetime));clock.now.return_value=datetime(2026,11,4,4,tzinfo=timezone.utc)
        self.path=self.root/'logs/today.json';self.value=dict(payload=dict(jobs=[dict(account='fb01',target='page01',url='https://www.facebook.com/profile.php?id=1001')]))
        upload.save_json(self.path,self.value)
    def test_native_scope_is_bound_only_after_original_freeze_and_restored_on_exit(self):
        original=upload.launch_context
        def execute(date,real):
            self.assertEqual(date,'2026-11-04');self.assertTrue(real)
            path,value=today.priority.prepare(date)
            self.assertEqual(value['browser_launch_mode'],today.MODE)
            wrapper=MagicMock()
            with patch.object(today.normal,'launch_normal',return_value=wrapper),patch.object(today.normal.local_files,'authorize'):
                self.assertIs(upload.launch_context(None,dict(account='fb01',target='page01',url='https://www.facebook.com/profile.php?id=1001')),wrapper)
                with self.assertRaises(ValueError):upload.launch_context(None,dict(account='fb03',target='personal',url='https://www.facebook.com/profile.php?id=1003'))
            return 3
        with patch.object(today.priority,'prepare',return_value=(self.path,copy.deepcopy(self.value))) as freeze,patch.object(today.priority,'execute',side_effect=execute):
            self.assertEqual(today.execute(True),3)
            self.assertIs(today.priority.prepare,freeze)
        self.assertIs(upload.launch_context,original)
    def test_failure_restores_original_functions_and_never_resets_a_manifest(self):
        original=upload.launch_context
        def execute(*args):today.priority.prepare('2026-11-04');raise RuntimeError('test stop')
        with patch.object(today.priority,'prepare',return_value=(self.path,copy.deepcopy(self.value))) as prepare,patch.object(today.priority,'execute',side_effect=execute):
            with self.assertRaises(RuntimeError):today.execute(True)
            self.assertIs(today.priority.prepare,prepare)
        self.assertIs(upload.launch_context,original)
        self.assertEqual(upload.read_json(self.path,{})['payload'],self.value['payload'])
    def test_conflicting_browser_mode_and_unconfirmed_footage_do_not_launch(self):
        changed=copy.deepcopy(self.value);changed['browser_launch_mode']='different';upload.save_json(self.path,changed)
        def execute(*args):today.priority.prepare('2026-11-04')
        with patch.object(today.priority,'prepare',return_value=(self.path,changed)),patch.object(today.priority,'execute',side_effect=execute),patch.object(today.normal,'launcher_for_jobs') as launch:
            with self.assertRaises(ValueError):today.execute(True)
            launch.assert_not_called()
        with self.assertRaises(ValueError):today.execute(False)
