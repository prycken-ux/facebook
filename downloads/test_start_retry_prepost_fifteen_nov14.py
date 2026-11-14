import io
import shutil
import subprocess
import sys
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import start_retry_prepost_fifteen_nov14 as app
import fb_upload as upload
from test_scheduled_material_batch import ScheduledMaterialTests


class FifteenRetryStartTests(unittest.TestCase):
    def setUp(self):
        self.fx = ScheduledMaterialTests()
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)
        self.code = Path(__file__).resolve().parent
        self.updates = {name: (self.code/name).read_bytes() for name in app.NAMES}

    def package(self, updates=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, data in (updates or self.updates).items():
                archive.writestr(name, data)
        return output.getvalue()

    def test_package_rejects_extra_files_and_installer_rolls_back_failed_probe(self):
        self.assertEqual(app.unpack(self.package()), self.updates)
        with self.assertRaises(ValueError):
            app.unpack(self.package(dict(self.updates, **{'../upload_config.json': b'{}'})))
        original = b'# original helper\n'
        (self.fx.root/app.NAMES[0]).write_bytes(original)
        protected = {p: p.read_bytes() for p in (upload.CONFIG, self.fx.state_path)}
        with patch.object(app.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['probe'])):
            with self.assertRaises(subprocess.CalledProcessError):
                app.install(self.fx.root, self.updates)
        self.assertEqual((self.fx.root/app.NAMES[0]).read_bytes(), original)
        self.assertTrue(all(not (self.fx.root/name).exists() for name in app.NAMES[1:]))
        for path, data in protected.items():
            self.assertEqual(path.read_bytes(), data)

    def test_actual_child_argv_preserves_console_without_name_or_ai_prompts(self):
        driver = self.fx.root/'retry_nov13_prepost_fifteen_on_nov14.py'
        driver.write_text("import sys\nfrom pathlib import Path\nassert len(sys.argv)==2\nassert Path(sys.argv[1]).resolve()==Path(__file__).resolve().parent\n", encoding='utf-8')
        with patch.object(app.sys, 'platform', 'win32'), patch.object(app, 'datetime', wraps=datetime) as clock, \
                patch.object(app, 'download', side_effect=[self.package(), b'def recover_locks(root):pass\n']), \
                patch.object(app, 'install'), patch('builtins.input', side_effect=AssertionError('Already confirmed')):
            clock.now.return_value = datetime(2026, 11, 14, 4, tzinfo=timezone.utc)
            self.assertEqual(app.start(self.fx.root), 0)

    def test_active_lock_recovery_rejection_never_installs_or_starts_second_publisher(self):
        helper = b'def recover_locks(root):raise RuntimeError("active publisher")\n'
        with patch.object(app.sys, 'platform', 'win32'), patch.object(app, 'datetime', wraps=datetime) as clock, \
                patch.object(app, 'download', side_effect=[self.package(), helper]), \
                patch.object(app, 'install') as install, patch.object(app.subprocess, 'run') as run:
            clock.now.return_value = datetime(2026, 11, 14, 4, tzinfo=timezone.utc)
            with self.assertRaisesRegex(RuntimeError, 'active publisher'):
                app.start(self.fx.root)
        install.assert_not_called()
        run.assert_not_called()

    def test_wrong_date_stops_before_network_or_installation(self):
        with patch.object(app.sys, 'platform', 'win32'), patch.object(app, 'datetime', wraps=datetime) as clock, patch.object(app, 'download') as download:
            clock.now.return_value = datetime(2026, 11, 15, 4, tzinfo=timezone.utc)
            with self.assertRaises(ValueError):
                app.start(self.fx.root)
        download.assert_not_called()

    def test_fresh_interpreter_can_import_exact_installed_package(self):
        for path in self.code.glob('*.py'):
            shutil.copy2(path, self.fx.root/path.name)
        completed = subprocess.run([sys.executable, '-c', app.VERIFY, str(self.fx.root)], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
