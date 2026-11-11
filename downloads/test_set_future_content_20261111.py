import hashlib
import io
import shutil
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock,patch

import set_future_content_20261111 as app
import publication_preferences as prefs
import fb_upload as upload
import test_scheduled_material_batch as fixtures


class FutureContentInstallerTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ScheduledMaterialTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        prefs.save_authorized(resume_from='2026-11-11')
        self.source=Path(__file__).resolve().parent
        self.updates={name:(self.source/name).read_bytes() for name in app.NAMES}

    def package(self,updates):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            for name,content in updates.items():archive.writestr(name,content)
        return data.getvalue()

    def test_real_fresh_probe_saves_both_defaults_and_preserves_original_jobs_and_rules(self):
        before=upload.read_json(self.f.root/'publication_preferences.json',{})
        protected={p:p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()}
        for source in self.source.glob('*.py'):shutil.copy2(source,self.f.root/source.name)
        self.assertEqual(app.install(self.f.root,self.updates),0)
        after=upload.read_json(self.f.root/'publication_preferences.json',{})
        self.assertEqual({k:v for k,v in after.items() if k!='content_updates'},before)
        self.assertEqual(prefs.content_policy('2026-11-11')['payload']['comment'],prefs.EVERYDAY_COMMENT)
        for path,data in protected.items():
            if path.name not in {'publication_preferences.json','common_caption_today.txt'}:self.assertEqual(path.read_bytes(),data)

    def test_probe_failure_restores_modules_and_both_setting_files(self):
        module=self.f.root/app.NAMES[0];module.write_bytes(b'# Previous installed module\n')
        originals={p:p.read_bytes() if p.is_file() else None for p in [self.f.root/n for n in app.NAMES]+[self.f.root/'publication_preferences.json',self.f.root/'common_caption_today.txt']}
        def fail(*args,**kwargs):
            (self.f.root/'publication_preferences.json').write_bytes(b'changed')
            (self.f.root/'common_caption_today.txt').write_bytes(b'changed')
            raise subprocess.CalledProcessError(1,['probe'])
        with patch.object(app.subprocess,'run',side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):app.install(self.f.root,self.updates)
        for path,data in originals.items():
            if data is None:self.assertFalse(path.exists())
            else:self.assertEqual(path.read_bytes(),data)

    def test_active_worker_prevents_install_and_keeps_its_lock(self):
        lock=self.f.root/'logs/upload.lock';lock.write_bytes(b'active')
        before=(self.f.root/'publication_preferences.json').read_bytes()
        with patch.object(app.subprocess,'run') as run:
            with self.assertRaises(RuntimeError):app.install(self.f.root,self.updates)
        run.assert_not_called();self.assertEqual(lock.read_bytes(),b'active');self.assertEqual((self.f.root/'publication_preferences.json').read_bytes(),before)

    def test_download_checks_digest_scope_and_syntax(self):
        for updates,exception in [(self.updates,None),(dict(self.updates,**{'../config.json':b'{}'}),ValueError),(dict(self.updates,**{app.NAMES[0]:b'invalid!python'}),SyntaxError)]:
            data=self.package(updates);response=MagicMock();response.__enter__.return_value.read.return_value=data
            with patch.object(app.urllib.request,'urlopen',return_value=response),patch.object(app,'PACKAGE_SHA',hashlib.sha256(data).hexdigest()):
                if exception:
                    with self.assertRaises(exception):app.download()
                else:self.assertEqual(app.download(),updates)
        with patch.object(app.urllib.request,'urlopen',return_value=response),patch.object(app,'PACKAGE_SHA','0'*64):
            with self.assertRaisesRegex(ValueError,'Checksum'):app.download()

    def test_entry_passes_explicit_upload_root_without_publishing(self):
        with patch.object(app.sys,'platform','win32'),patch.object(app.sys,'argv',['entry',str(self.f.root)]),patch.object(app,'download',return_value=self.updates),patch.object(app,'install',return_value=0) as install:
            self.assertEqual(app.main(),0)
        install.assert_called_once_with(self.f.root,self.updates)


if __name__=='__main__':unittest.main()
