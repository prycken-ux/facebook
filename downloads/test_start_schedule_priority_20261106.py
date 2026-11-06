import contextlib,io,shutil,subprocess,sys,tempfile,unittest,zipfile
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import start_schedule_priority_20261106 as start
import fb_upload as upload
import test_scheduled_material_batch as fixtures


class Nov06ScheduleStartTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ScheduledMaterialTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.code=Path(__file__).resolve().parent
        self.updates={name:(self.code/name).read_bytes() for name in start.NAMES}
    def package(self,updates=None):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            for name,value in (updates or self.updates).items():archive.writestr(name,value)
        return data.getvalue()
    def test_unpack_requires_exact_file_scope_and_python_syntax(self):
        self.assertEqual(start.unpack(self.package()),self.updates)
        with self.assertRaises(ValueError):start.unpack(self.package(dict(self.updates,**{'../config.json':b'{}'})))
        changed=dict(self.updates);changed[start.NAMES[0]]=b'invalid!python'
        with self.assertRaises(SyntaxError):start.unpack(self.package(changed))
    def test_installer_verifies_fresh_process_and_preserves_state_config_and_captions(self):
        state=self.fx.state_path.read_bytes();config=upload.CONFIG.read_bytes()
        with patch.object(start.subprocess,'run') as run:start.install(self.fx.root,self.updates)
        self.assertTrue(run.call_args.kwargs['check'])
        self.assertEqual(self.fx.state_path.read_bytes(),state);self.assertEqual(upload.CONFIG.read_bytes(),config)
        for name,value in self.updates.items():self.assertEqual((self.fx.root/name).read_bytes(),value)
    def test_failed_verification_restores_original_files_and_removes_new_files(self):
        original=b'# Original scheduler\n';(self.fx.root/start.NAMES[0]).write_bytes(original)
        with patch.object(start.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['verify'])):
            with self.assertRaises(subprocess.CalledProcessError):start.install(self.fx.root,self.updates)
        self.assertEqual((self.fx.root/start.NAMES[0]).read_bytes(),original)
        self.assertTrue(all(not (self.fx.root/name).exists() for name in start.NAMES[1:]))
    def test_start_recovers_then_installs_then_runs_child_with_inherited_console_input(self):
        helper=b'def recover_locks(root):\n print("test helper")\n';events=[]
        with patch.object(start.sys,'platform','win32'),patch.object(start,'datetime',wraps=datetime) as clock,patch.object(start,'download',side_effect=[self.package(),helper]),patch.object(start,'install',side_effect=lambda *a:events.append('install')),patch.object(start.subprocess,'run',return_value=subprocess.CompletedProcess([],3)) as run:
            clock.now.return_value=datetime(2026,11,6,4,tzinfo=timezone.utc)
            self.assertEqual(start.start(self.fx.root,True),3)
        self.assertEqual(events,['install']);self.assertNotIn('input',run.call_args.kwargs);self.assertNotIn('stdin',run.call_args.kwargs)
        self.assertIn('--real-footage',run.call_args.args[0]);self.assertIn('setup',run.call_args.args[0]);self.assertEqual(run.call_args.args[0][1],str(self.fx.root/'scheduled_priority_workflow.py'))
    def test_wrong_date_refuses_before_downloading(self):
        with patch.object(start.sys,'platform','win32'),patch.object(start,'datetime',wraps=datetime) as clock,patch.object(start,'download') as download:
            clock.now.return_value=datetime(2026,11,2,4,tzinfo=timezone.utc)
            with self.assertRaises(ValueError):start.start(self.fx.root,True)
        download.assert_not_called()
    def test_unconfirmed_todays_footage_stops_before_download(self):
        with patch.object(start.sys,'platform','win32'),patch.object(start,'datetime',wraps=datetime) as clock,patch.object(start,'download') as download:
            clock.now.return_value=datetime(2026,11,6,4,tzinfo=timezone.utc)
            with self.assertRaises(ValueError):start.start(self.fx.root,False)
        download.assert_not_called()
    def test_real_fresh_process_feature_probe_can_import_the_installed_package(self):
        for source in self.code.glob('*.py'):shutil.copy2(source,self.fx.root/source.name)
        completed=subprocess.run([sys.executable,'-c',start.VERIFY,str(self.fx.root)],capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
