import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import add_fb_accounts as legacy
import add_personal_accounts as app
import chrome_profile_guard as guard
import fb_upload as upload


class PersonalAdditionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for module in (app, legacy, upload):
            self.stack.enter_context(patch.object(module, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.config = dict(custom='keep-config', targets=[])
        self.registry = dict(custom='keep-registry', accounts=[])
        for index in range(1, 14):
            account = f'fb{index:02d}'
            personal = index in {3, 4, 7, 8, 9, 10, 11}
            row = dict(account=account, target='personal' if personal else 'page01', type='personal' if personal else 'page',
                       name=account, url=f'https://www.facebook.com/profile.php?id={1000+index}', enabled=True, prepared_at='old-check')
            if personal:
                row['workflow'] = 'personal_recording_v1'
            self.config['targets'].append(row)
            self.registry['accounts'].append(copy.deepcopy(row))
            folder = self.root / 'profiles' / account
            folder.mkdir(parents=True)
            (folder / 'keep-login').write_bytes(b'old session stays local')
        self.config['targets'].append(dict(account='fb10', target='page01', type='page', name='New Page',
            url='https://www.facebook.com/profile.php?id=61595024556188', enabled=True, prepared_at='page-check'))
        upload.save_json(self.root / 'upload_config.json', self.config)
        upload.save_json(self.root / 'account_registry.json', self.registry)
        upload.save_json(self.root / legacy.MANIFEST, dict(schema=legacy.SCHEMA,
            slots={f'fb{i:02d}': dict(state='registered') for i in range(8, 14)}))
        upload.save_json(self.root / 'logs/publish_state.json', {'previous14': {'status': 'published'}})
        self.shortcut_dir = self.root / '新增账号登录'
        self.shortcut_dir.mkdir()
        for i in range(8, 14):
            (self.shortcut_dir / f'fb{i:02d} 登录.lnk').write_bytes(b'keep existing shortcut')

    def reserve(self):
        with legacy.locked():
            return app.reserve(10, 'personal-20261024-ten')

    def test_allocate_exact_ten_fb14_to_fb23_preserving_fourteen_targets_and_old_shortcuts(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.reserve(), [f'fb{i}' for i in range(14, 24)])
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        for account in (f'fb{i}' for i in range(14, 24)):
            self.assertTrue((self.root / 'profiles' / account).is_dir())
            for name in ('inbox', 'completed', 'failed'):
                self.assertTrue((self.root / 'videos' / account / 'personal' / name).is_dir())
        items = app.shortcut_items([f'fb{i}' for i in range(14, 24)], Path('C:/Chrome/chrome.exe'))
        self.assertTrue(all(Path(item['path']).parent == self.shortcut_dir for item in items))
        self.assertEqual(len({item['arguments'] for item in items}), 10)
        self.assertTrue(all('--no-first-run' in item['arguments'] for item in items))

    def test_repeating_same_reservation_reuses_numbers_and_existing_session_files(self):
        accounts = self.reserve()
        marker = self.root / 'profiles/fb14/new-local-login'
        marker.write_bytes(b'new local session')
        manifest = (self.root / app.MANIFEST).read_bytes()
        self.assertEqual(self.reserve(), accounts)
        self.assertEqual(marker.read_bytes(), b'new local session')
        self.assertEqual((self.root / app.MANIFEST).read_bytes(), manifest)
        self.assertFalse((self.root / 'profiles/fb24').exists())
        with self.assertRaises(ValueError):
            app.reserve(11, 'personal-20261024-ten')

    def test_preexisting_unclaimed_data_is_skipped_not_adopted(self):
        (self.root / 'profiles/fb20').mkdir()
        (self.root / 'profiles/fb20/local-session').write_bytes(b'unclaimed preserved')
        self.assertEqual(self.reserve(), [f'fb{i}' for i in range(21, 31)])
        self.assertEqual((self.root / 'profiles/fb20/local-session').read_bytes(), b'unclaimed preserved')
        self.assertFalse((self.root / 'profiles/fb14').exists())

    def test_existing_shortcut_or_legacy_pending_reservation_counts_as_occupied(self):
        (self.shortcut_dir / 'fb30 登录.lnk').write_bytes(b'preexisting')
        self.assertEqual(self.reserve()[0], 'fb31')

    def test_register_personal_is_disabled_and_keeps_all_old_targets_records_and_sessions(self):
        self.reserve()
        state = (self.root / 'logs/publish_state.json').read_bytes()
        old_config = (self.root / 'upload_config.json').read_bytes()
        self.assertTrue(app.register('fb14', 'Person Fourteen', 'https://www.facebook.com/New.Person?sk=reels_tab#x'))
        config = upload.read_json(self.root / 'upload_config.json', {})
        self.assertEqual(config['targets'][:14], self.config['targets'])
        row = config['targets'][-1]
        self.assertEqual(row['url'], 'https://www.facebook.com/new.person')
        self.assertEqual(row['target'], 'personal')
        self.assertEqual(row['workflow'], 'personal_recording_v1')
        self.assertFalse(row['enabled'])
        self.assertNotIn('prepared_at', row)
        self.assertEqual((self.root / 'logs/publish_state.json').read_bytes(), state)
        backup = next((self.root / 'backups').glob('new-personal-register-*'))
        self.assertEqual((backup / 'upload_config.json').read_bytes(), old_config)
        registry = upload.read_json(self.root / 'account_registry.json', {})
        self.assertEqual(registry['accounts'][:13], self.registry['accounts'])

    def test_idempotent_registration_preserves_enabled_and_extra_page_for_new_account(self):
        self.reserve()
        app.register('fb14', 'Person', 'https://www.facebook.com/newperson')
        config = upload.read_json(self.root / 'upload_config.json', {})
        config['targets'][-1].update(enabled=True, prepared_at='new-ready')
        config['targets'].append(dict(account='fb14', target='page01', type='page', name='Another Page',
                                      url='https://www.facebook.com/profile.php?id=8888'))
        upload.save_json(self.root / 'upload_config.json', config)
        before = (self.root / 'upload_config.json').read_bytes()
        self.assertFalse(app.register('fb14', 'Person', 'https://www.facebook.com/newperson'))
        self.assertEqual(before, (self.root / 'upload_config.json').read_bytes())
        with self.assertRaises(ValueError):
            app.register('fb14', 'Different Person', 'https://www.facebook.com/newperson')

    def test_duplicate_target_invalid_name_or_old_account_refuses_without_edits(self):
        self.reserve()
        before = (self.root / 'upload_config.json').read_bytes()
        for args in [('fb14', 'Person', self.config['targets'][0]['url']),
                     ('fb10', 'Person', 'https://www.facebook.com/newperson'),
                     ('fb14', 'Person\nOther', 'https://www.facebook.com/newperson'),
                     ('fb14', 'Person', 'https://example.com/person'),
                     ('fb24', 'Person', 'https://www.facebook.com/newperson')]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                app.register(*args)
            self.assertEqual(before, (self.root / 'upload_config.json').read_bytes())

    def test_registration_save_failure_restores_all_three_documents(self):
        self.reserve()
        paths = [self.root / name for name in ('upload_config.json', 'account_registry.json', app.MANIFEST)]
        before = {path: path.read_bytes() for path in paths}
        save = upload.save_json
        calls = []
        def fail_second(path, data):
            calls.append(path)
            if len(calls) == 2:
                raise OSError('simulated write failure')
            save(path, data)
        with patch.object(upload, 'save_json', side_effect=fail_second), self.assertRaises(OSError):
            app.register('fb14', 'Person', 'https://www.facebook.com/newperson')
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_open_one_to_seven_uses_existing_primary_targets_and_separate_chrome_profiles(self):
        accounts = [f'fb{i:02d}' for i in range(1, 8)]
        before = (self.root / 'upload_config.json').read_bytes()
        with patch.object(app.sys, 'platform', 'win32'), patch.object(legacy, 'find_chrome', return_value=Path('/chrome')), \
             patch.object(app.subprocess, 'Popen') as popen:
            selected = app.open_accounts(accounts)
        self.assertEqual(len(selected), 7)
        self.assertEqual(popen.call_count, 7)
        for index, call in enumerate(popen.call_args_list):
            argv = call.args[0]
            self.assertIn('--user-data-dir=' + str(self.root / 'profiles' / accounts[index]), argv)
            self.assertEqual(argv[-1], self.config['targets'][index]['url'])
        self.assertEqual((self.root / 'upload_config.json').read_bytes(), before)

    def test_open_existing_profiles_does_not_require_registry_target_on_old_single_target_accounts(self):
        registry = copy.deepcopy(self.registry)
        for row in registry['accounts']:
            row.pop('target', None)
        upload.save_json(self.root / 'account_registry.json', registry)
        with patch.object(app.sys, 'platform', 'win32'), patch.object(legacy, 'find_chrome', return_value=Path('/chrome')), \
             patch.object(app.subprocess, 'Popen') as popen:
            selected = app.open_accounts(['fb01', 'fb03', 'fb10'])
        self.assertEqual(len(selected), 3)
        self.assertEqual(selected[-1][2], self.config['targets'][9]['url'])
        self.assertEqual(popen.call_count, 3)

    def test_open_validation_is_complete_before_any_browser_launch(self):
        with patch.object(app.sys, 'platform', 'win32'), patch.object(legacy, 'find_chrome', return_value=Path('/chrome')), \
             patch.object(app.subprocess, 'Popen') as popen:
            with self.assertRaises(ValueError):
                app.open_accounts(['fb01', 'fb99'])
        popen.assert_not_called()

    def test_prepare_uses_same_folder_and_only_creates_own_new_shortcuts(self):
        def write_items(items):
            for item in items:
                Path(item['path']).write_bytes(b'new profile shortcut')
        with patch.object(app.sys, 'platform', 'win32'), patch.object(legacy, 'find_chrome', return_value=Path('/chrome')), \
             patch.object(legacy, 'write_shortcuts', side_effect=write_items), patch.object(app.os, 'startfile', create=True) as start:
            app.prepare(10, 'personal-20261024-ten')
        start.assert_called_once_with(str(self.shortcut_dir))
        self.assertEqual(len(list(self.shortcut_dir.glob('*.lnk'))), 16)
        for i in range(8, 14):
            self.assertEqual((self.shortcut_dir / f'fb{i:02d} 登录.lnk').read_bytes(), b'keep existing shortcut')
        self.assertFalse((self.root / '新增个人账号登录').exists())

    def test_non_windows_prepare_does_not_reserve_anything(self):
        with patch.object(app.sys, 'platform', 'linux'), self.assertRaises(ValueError):
            app.prepare(10, 'personal-20261024-ten')
        self.assertFalse((self.root / app.MANIFEST).exists())

    def test_active_lock_prevents_addition_and_opening(self):
        lock = self.root / 'logs/upload.lock'
        lock.write_text('another upload')
        with self.assertRaises(RuntimeError):
            self.reserve()
        self.assertEqual(lock.read_text(), 'another upload')
        self.assertFalse((self.root / 'profiles/fb14').exists())

    def test_registered_missing_profile_is_not_silently_recreated(self):
        self.reserve()
        app.register('fb14', 'Person', 'https://www.facebook.com/newperson')
        (self.root / 'profiles/fb14').rmdir()
        with self.assertRaises(ValueError):
            self.reserve()
        self.assertFalse((self.root / 'profiles/fb14').exists())

    def test_profile_guard_diagnostic_accepts_future_account_numbers(self):
        with patch('sys.argv', ['chrome_profile_guard.py', '--accounts', 'fb14,fb23,fb100']), \
             patch.object(guard, 'profile_owners', return_value=[]) as owners:
            self.assertEqual(guard.main(), 0)
        self.assertEqual(owners.call_count, 3)


if __name__ == '__main__':
    unittest.main()
