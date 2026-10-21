import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import add_fb_accounts
import add_page_target as app
import batch_upload as batch

ACCOUNT = 'fb10'
NAME = 'Thockspiwem Thimbrojospo'
URL = 'https://www.facebook.com/profile.php?id=61595024556188#'


class PageTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for module in (app, add_fb_accounts, batch):
            self.stack.enter_context(patch.object(module, 'ROOT', self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.personal = dict(account=ACCOUNT, target='personal', type='personal', name='Ava H-s',
            url='https://www.facebook.com/lale.hs.3', enabled=True, prepared_at='keep-prepare',
            workflow='personal_recording_v1', ai_label=False, excluded_files=['old.mp4'])
        self.other = dict(account='fb01', target='page01', type='page', name='Other',
            url='https://www.facebook.com/profile.php?id=1001', enabled=True)
        self.config = dict(custom={'keep': True}, targets=[self.other, self.personal])
        app.upload.save_json(self.root/'upload_config.json', self.config)
        app.upload.save_json(self.root/'account_registry.json', {'accounts': [self.personal]})
        app.upload.save_json(self.root/'logs/publish_state.json', {'old': {'status': 'published'}})
        (self.root/'profiles/fb10').mkdir(parents=True)
        (self.root/'profiles/fb10/fixture-login').write_bytes(b'keep-login')

    def apply(self):
        return app.apply(ACCOUNT, 'page01', NAME, URL)

    def test_addition_preserves_primary_and_all_other_data_with_backup(self):
        config_bytes = (self.root/'upload_config.json').read_bytes()
        untouched = {p: p.read_bytes() for p in (self.root/'account_registry.json',
            self.root/'logs/publish_state.json', self.root/'profiles/fb10/fixture-login')}
        result = self.apply()
        self.assertEqual(result['targets'][:2], self.config['targets'])
        self.assertEqual(result['custom'], self.config['custom'])
        page = result['targets'][-1]
        self.assertFalse(page['enabled'])
        self.assertFalse(page['ai_label'])
        self.assertNotIn('prepared_at', page)
        self.assertEqual(page['url'], URL.rstrip('#'))
        for folder in ('inbox', 'completed', 'failed'):
            self.assertTrue((self.root/'videos/fb10/page01'/folder).is_dir())
        backup = next((self.root/'backups').iterdir())
        self.assertEqual((backup/'upload_config.json').read_bytes(), config_bytes)
        for path, content in untouched.items():
            self.assertEqual(path.read_bytes(), content)

    def test_repeated_registration_preserves_enabled_state_and_existing_media(self):
        result = self.apply()
        result['targets'][-1].update(enabled=True, prepared_at='page-prepare')
        app.upload.save_json(self.root/'upload_config.json', result)
        media = self.root/'videos/fb10/page01/inbox/1.mp4'
        media.write_bytes(b'keep-video')
        before = (self.root/'upload_config.json').read_bytes()
        backups = list((self.root/'backups').iterdir())
        self.apply()
        self.assertEqual((self.root/'upload_config.json').read_bytes(), before)
        self.assertEqual(media.read_bytes(), b'keep-video')
        self.assertEqual(list((self.root/'backups').iterdir()), backups)

    def test_target_collision_is_refused_without_overwriting(self):
        self.apply()
        before = (self.root/'upload_config.json').read_bytes()
        with self.assertRaisesRegex(ValueError, '未覆盖'):
            app.apply(ACCOUNT, 'page01', NAME, 'https://www.facebook.com/profile.php?id=2002')
        self.assertEqual((self.root/'upload_config.json').read_bytes(), before)

    def test_duplicate_page_on_another_target_or_account_is_refused(self):
        for account in ('fb01', 'fb10'):
            config = copy.deepcopy(self.config)
            config['targets'].append(dict(account=account, target='page02', type='page', name=NAME, url=URL))
            with self.subTest(account=account), self.assertRaisesRegex(ValueError, '重复添加'):
                app.plan(config, ACCOUNT, 'page01', NAME, URL)

    def test_missing_personal_profile_invalid_ids_and_urls_are_refused(self):
        for account, target, url in [('fb99', 'page01', URL), ('fb10', 'personal', URL),
                                     ('../fb10', 'page01', URL), ('fb10', '../page01', URL),
                                     ('fb10', 'page01', 'https://www.facebook.com/page-slug'),
                                     ('fb10', 'page01', 'https://example.com/profile.php?id=12')]:
            with self.subTest(account=account, target=target, url=url), self.assertRaises(ValueError):
                app.plan(self.config, account, target, NAME, url)

    def test_active_lock_blocks_registration_and_is_preserved(self):
        lock = self.root/'logs/upload.lock'
        lock.write_bytes(b'other-job')
        before = (self.root/'upload_config.json').read_bytes()
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(lock.read_bytes(), b'other-job')
        self.assertEqual((self.root/'upload_config.json').read_bytes(), before)
        self.assertFalse((self.root/'logs/batch.lock').exists())

    def test_failed_configuration_save_restores_original_bytes(self):
        before = (self.root/'upload_config.json').read_bytes()
        with patch.object(app.upload, 'save_json', side_effect=OSError('fixture failure')), self.assertRaises(OSError):
            self.apply()
        self.assertEqual((self.root/'upload_config.json').read_bytes(), before)
        self.assertFalse((self.root/'logs/upload.lock').exists())

    def test_both_targets_are_selected_for_batch_and_page_needs_its_own_prepare(self):
        result = self.apply()
        selected, errors = batch.select_targets(result, [ACCOUNT], 'plan', {})
        self.assertEqual(errors, [])
        self.assertEqual([row['target'] for row in selected], ['personal', 'page01'])
        _, errors = batch.select_targets(result, [ACCOUNT], 'publish', {})
        self.assertTrue(any('fb10/page01' in error and 'prepare' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
