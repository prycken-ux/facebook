import contextlib
import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as ET

import fb_upload as upload
import batch_upload as batch
import run_scheduled_batch as runner
import install_daily_schedule as installer


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.stack = contextlib.ExitStack()
        for module in (runner, installer, upload, batch):
            self.stack.enter_context(patch.object(module, 'ROOT', self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry = dict(account='fb01', target='page01', type='page', name='Example Page',
                          url='https://www.facebook.com/profile.php?id=1001', enabled=True, prepared_at='checked')
        (self.root / 'profiles/fb01').mkdir(parents=True)
        upload.save_json(self.root / 'upload_config.json', {'targets': [self.entry]})

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def test_beijing_boundary_is_independent_of_host_zone_and_always_future(self):
        now = datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc)
        self.assertEqual(installer.next_boundary('20:00', now), '2026-10-16T20:00:00+08:00')
        self.assertEqual(installer.next_boundary('19:00', now), '2026-10-17T19:00:00+08:00')
        self.assertEqual(installer.next_boundary('18:00', now), '2026-10-17T18:00:00+08:00')
        with self.assertRaises(ValueError):
            installer.next_boundary('24:00', now)

    def test_xml_uses_interactive_user_exact_python_and_single_daily_triggers(self):
        root = PureWindowsPath('E:/FB AutoUpload')
        xml = ET.fromstring(installer.make_xml(root, ['09:00', '20:00'], 'fb01,fb02', 1,
                                              datetime(2026, 10, 16, tzinfo=timezone.utc)))
        ns = {'t': installer.NS}
        self.assertEqual(xml.find('t:Principals/t:Principal/t:LogonType', ns).text, 'InteractiveToken')
        self.assertEqual(xml.find('t:Settings/t:MultipleInstancesPolicy', ns).text, 'IgnoreNew')
        self.assertEqual(xml.find('t:Settings/t:StartWhenAvailable', ns).text, 'false')
        self.assertEqual(len(xml.findall('t:Triggers/t:CalendarTrigger', ns)), 2)
        self.assertEqual(xml.find('t:Actions/t:Exec/t:Command', ns).text, r'E:\FB AutoUpload\.venv\Scripts\python.exe')
        args = xml.find('t:Actions/t:Exec/t:Arguments', ns).text
        self.assertEqual(args, r'"E:\FB AutoUpload\run_scheduled_batch.py" --accounts=fb01,fb02 --rounds=1')
        self.assertNotIn('2026-10-15', args)
        self.assertNotIn('review-before-post', args)

    def test_registration_command_never_starts_task_or_overwrites_existing_tasks(self):
        script = installer.powershell_script('<Task/>')
        self.assertIn('Register-ScheduledTask', script)
        self.assertIn('Existing FBUpload task(s)', script)
        self.assertNotIn('Start-ScheduledTask', script)
        self.assertNotIn('-Force', script)
        self.assertNotIn('ExecutionPolicy', script)

    def test_readiness_check_never_publishes_and_blocks_unresolved_records(self):
        with patch.object(runner.subprocess, 'run') as run:
            self.assertEqual(runner.check_ready(['fb01']), 0)
            upload.save_json(self.root / 'logs/publish_state.json', {'old': dict(account='fb01', target='page01', status='needs_review')})
            self.assertEqual(runner.check_ready(['fb01']), 1)
        run.assert_not_called()

    def test_readiness_detects_unprepared_or_disabled_target(self):
        self.entry.pop('prepared_at')
        self.entry['enabled'] = False
        upload.save_json(self.root / 'upload_config.json', {'targets': [self.entry]})
        self.assertEqual(runner.check_ready(['fb01']), 1)

    def test_real_child_output_goes_to_log_without_interactive_input(self):
        (self.root / 'batch_upload.py').write_text("import sys\nprint('fixture batch output')\nassert sys.stdin.read() == ''\n", encoding='utf-8')
        self.assertEqual(runner.run(['fb01'], 1), 0)
        logs = list((self.root / 'logs').glob('scheduled-*.log'))
        self.assertEqual(len(logs), 1)
        self.assertIn('fixture batch output', logs[0].read_text(encoding='utf-8'))
        self.assertFalse((self.root / 'logs/scheduled.lock').exists())

    def test_runner_retains_review_result_and_runs_next_round(self):
        with patch.object(runner.subprocess, 'run', side_effect=[SimpleNamespace(returncode=3), SimpleNamespace(returncode=0)]) as run:
            self.assertEqual(runner.run(['fb01'], 2), 3)
        self.assertEqual(run.call_count, 2)
        command = run.call_args.args[0]
        self.assertIn('--continue-on-review', command)
        self.assertFalse(any('--filename' in arg for arg in command))
        self.assertNotIn('--review-before-post', command)

    def test_runner_stops_on_real_error_and_keeps_other_lock(self):
        with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
            self.assertEqual(runner.run(['fb01'], 3), 1)
            self.assertEqual(run.call_count, 1)
        lock = self.root / 'logs/scheduled.lock'
        lock.write_text('another PID')
        with patch.object(runner.subprocess, 'run') as run:
            self.assertEqual(runner.run(['fb01'], 1), 2)
            run.assert_not_called()
        self.assertEqual(lock.read_text(), 'another PID')

    def test_installer_readiness_failure_does_not_register_or_publish(self):
        python = self.root / '.venv/Scripts/python.exe'
        python.parent.mkdir(parents=True)
        python.touch()
        (self.root / 'run_scheduled_batch.py').touch()
        with patch.object(installer.sys, 'platform', 'win32'), \
                patch('sys.argv', ['install_daily_schedule.py', '--time', '20:00']), \
                patch.object(installer.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
            self.assertEqual(installer.main(), 1)
        self.assertEqual(run.call_count, 1)
        self.assertIn('--check', run.call_args.args[0])

    def test_installer_registers_only_after_check_without_running_publication(self):
        python = self.root / '.venv/Scripts/python.exe'
        python.parent.mkdir(parents=True)
        python.touch()
        (self.root / 'run_scheduled_batch.py').touch()
        with patch.object(installer.sys, 'platform', 'win32'), \
                patch('sys.argv', ['install_daily_schedule.py', '--time', '20:00']), \
                patch.object(installer.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(installer.main(), 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn('--check', run.call_args_list[0].args[0])
        self.assertEqual(run.call_args_list[1].args[0][0], 'powershell.exe')
        self.assertNotIn('Start-ScheduledTask', run.call_args_list[1].args[0][-1])

    def test_interactive_installer_collects_time_and_rounds_before_registering(self):
        python = self.root / '.venv/Scripts/python.exe'
        python.parent.mkdir(parents=True)
        python.touch()
        (self.root / 'run_scheduled_batch.py').touch()
        with patch.object(installer.sys, 'platform', 'win32'), \
                patch('sys.argv', ['install_daily_schedule.py']), \
                patch('builtins.input', side_effect=['20:00', '2']) as answer, \
                patch.object(installer.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                patch.object(installer, 'make_xml', wraps=installer.make_xml) as make:
            self.assertEqual(installer.main(), 0)
        self.assertEqual(answer.call_count, 2)
        self.assertEqual(make.call_args.args[1], ['20:00'])
        self.assertEqual(make.call_args.args[3], 2)
        self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
