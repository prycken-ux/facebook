import contextlib
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fb_upload as upload
import add_fb_accounts
import install_reel_audience_recovery_20261119 as installer


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.core=self.root/'fb_upload.py';self.original=Path(upload.__file__).read_bytes();self.core.write_bytes(self.original)
        for name in ('upload_config.json','publication_account_exclusions.json','logs/publish_state.json','videos/fb32/personal/inbox/original.mp4'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'original task record or video')
        self.protected={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p!=self.core}
        self.enterContext(patch.object(upload,'ROOT',self.root))
        self.enterContext(patch.object(add_fb_accounts,'locked',side_effect=contextlib.nullcontext))
        self.workers=self.enterContext(patch.object(installer.workers,'active_workers',return_value=[]))
        self.probe=self.enterContext(patch.object(installer,'probe'))

    def check_protected(self):
        for p,data in self.protected.items():self.assertEqual(p.read_bytes(),data)

    def test_installs_only_narrow_function_and_helper_with_backup_no_task_run(self):
        self.assertEqual(installer.install(self.root),0)
        expected=installer.build_core(self.original)
        self.assertEqual(self.core.read_bytes(),expected)
        self.assertEqual(self.core.read_bytes().count(b'wait_for_public_controls'),2)
        self.assertEqual(len(list((self.root/'backups').glob('*/fb_upload.py'))),1)
        self.assertEqual(next((self.root/'backups').glob('*/fb_upload.py')).read_bytes(),self.original)
        self.probe.assert_called_once_with(self.root);self.check_protected()
        before=self.core.read_bytes();self.assertEqual(installer.install(self.root),0)
        self.assertEqual(self.core.read_bytes(),before)
        self.assertEqual(len(list((self.root/'backups').glob('*/fb_upload.py'))),1)

    def test_failed_probe_rolls_back_original_core_and_helper(self):
        helper=self.root/'reel_audience_dialog_recovery.py';helper.write_bytes(b'# original helper\n')
        self.probe.side_effect=RuntimeError('feature probe failed')
        with self.assertRaisesRegex(RuntimeError,'feature probe failed'):installer.install(self.root)
        self.assertEqual(self.core.read_bytes(),self.original)
        self.assertEqual(helper.read_bytes(),b'# original helper\n');self.check_protected()

    def test_active_task_or_unknown_core_refuses_without_changes(self):
        self.workers.return_value=[dict(pid=123)]
        with self.assertRaisesRegex(ValueError,'仍有发布'):installer.install(self.root)
        self.assertEqual(self.core.read_bytes(),self.original)
        self.workers.return_value=[]
        changed=self.original.replace(b'def ensure_personal_public_audience(page):',b'def ensure_personal_public_audience(page):\n    custom = True')
        self.core.write_bytes(changed)
        with self.assertRaisesRegex(ValueError,'不是已核对'):installer.install(self.root)
        self.assertEqual(self.core.read_bytes(),changed);self.check_protected()

    def test_crlf_and_utf8_bom_preserved(self):
        source=b'\xef\xbb\xbf'+self.original.decode('utf-8-sig').replace('\r\n','\n').replace('\n','\r\n').encode()
        changed=installer.build_core(source)
        self.assertTrue(changed.startswith(b'\xef\xbb\xbf'));self.assertIn(b'\r\n',changed)
        self.assertNotIn(b'\n',changed.replace(b'\r\n',b''))
        self.assertEqual(installer.build_core(changed),changed)


class InstallerChainTests(unittest.TestCase):
    def test_exact_installer_chain_exempts_only_self(self):
        from test_nov16_venv_process_chain import VenvProcessChainTests
        f=VenvProcessChainTests();f.setUp();rows=copy.deepcopy(f.rows)
        runner=r'E:\FB-AutoUpload\material-staging\tools\audience-fix\install_reel_audience_recovery_20261119.py'
        body=f.body.replace('start_finish_first24_nov16','start_install_reel_audience_recovery_nov19').replace('verified-nov16-first24-and-nov14-stage','verified-reel-audience-recovery-install')
        for row in rows[:2]:row['command']=subprocess.list2cmdline([f.exe,'-u',runner,f.root])
        for row in rows[2:]:row['command']=subprocess.list2cmdline([f.exe,'-u','-c',body,f.root])
        rows.append(f.row(96,1,['-u',f.root+r'\retry_nov18_twelve_prepost_on_nov19.py',f.root]))
        with patch.object(installer.workers,'BOOTSTRAP',installer.BOOTSTRAP):workers,allowed=installer.workers.classify_workers(rows,f.root,100,runner)
        self.assertEqual(allowed,[97,98,99,100]);self.assertEqual([r['pid'] for r in workers],[96])


if __name__=='__main__':unittest.main()
