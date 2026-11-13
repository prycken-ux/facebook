import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import start_material_distribution as start
import add_fb_accounts as legacy
from test_distribute_video_materials import DistributionTests


class DistributorInstallerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=DistributionTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.data=(Path(__file__).parent/start.MODULE).read_bytes()

    def test_install_creates_reusable_python_shortcut_preserves_data_and_verifies_fresh_process(self):
        def shortcuts(items):
            self.assertEqual(len(items),1)
            self.assertEqual(items[0]['chrome'],sys.executable)
            self.assertIn('--pause',items[0]['arguments'])
            self.assertNotIn('--choose',items[0]['arguments'])
            Path(items[0]['path']).write_bytes(b'test shortcut')
        with patch.object(start.subprocess,'run') as probe,patch.object(legacy,'write_shortcuts',side_effect=shortcuts):
            start.install(self.root,self.data)
        self.assertTrue(probe.call_args.kwargs['check'])
        self.assertEqual((self.root/start.MODULE).read_bytes(),self.data)
        for path,data in self.fixture.preserved.items():self.assertEqual(path.read_bytes(),data)

    def test_failed_feature_probe_restores_original_tool_and_does_not_create_shortcut(self):
        tool=self.root/start.MODULE;tool.write_bytes(b'# original tool\n')
        with patch.object(start.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['verify'])),patch.object(legacy,'write_shortcuts') as shortcuts:
            with self.assertRaises(subprocess.CalledProcessError):start.install(self.root,self.data)
        self.assertEqual(tool.read_bytes(),b'# original tool\n')
        shortcuts.assert_not_called()

    def test_first_run_opens_folder_picker_and_inherits_console(self):
        (self.root/'add_fb_accounts.py').write_text('# installed module')
        with patch.object(start.sys,'platform','win32'),patch.object(start,'download',side_effect=[self.data,b'def recover_locks(root):pass\n']), \
             patch.object(start,'install'),patch.object(start.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as launch:
            self.assertEqual(start.start(self.root),0)
        self.assertEqual(launch.call_args.args[0],[sys.executable,str(self.root/start.MODULE),'--root',str(self.root),'--choose'])
        self.assertNotIn('input',launch.call_args.kwargs)
        self.assertNotIn('stdin',launch.call_args.kwargs)

    def test_active_upload_lock_prevents_installation_without_changing_original_files(self):
        lock=self.root/'logs/upload.lock';lock.write_text('active')
        with self.assertRaises(RuntimeError):start.install(self.root,self.data)
        self.assertFalse((self.root/start.MODULE).exists())
        self.assertEqual(lock.read_text(),'active')

    def test_original_accounts_scope_is_passed_to_picker_child_without_publishing(self):
        (self.root/'add_fb_accounts.py').write_text('# installed module')
        with patch.object(start.sys,'platform','win32'),patch.object(start,'download',side_effect=[self.data,b'def recover_locks(root):pass\n']), \
             patch.object(start,'install'),patch.object(start.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as launch:
            self.assertEqual(start.start(self.root,'existing24'),0)
        self.assertEqual(launch.call_args.args[0],
                         [sys.executable,str(self.root/start.MODULE),'--root',str(self.root),'--choose','--scope','existing24'])

    def test_all_accounts_scope_matches_latest_request_and_is_passed_to_child(self):
        (self.root/'add_fb_accounts.py').write_text('# installed module')
        with patch.object(start.sys,'platform','win32'),patch.object(start,'download',side_effect=[self.data,b'def recover_locks(root):pass\n']), \
             patch.object(start,'install'),patch.object(start.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as launch:
            self.assertEqual(start.start(self.root,'all'),0)
        self.assertEqual(launch.call_args.args[0][-2:],['--scope','all'])

    def test_fresh_process_probe_imports_reusable_distributor_without_opening_gui(self):
        result=subprocess.run([sys.executable,'-c',start.VERIFY,str(Path(__file__).parent)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
