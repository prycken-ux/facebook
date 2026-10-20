import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright

import fb_upload as upload
import batch_upload as batch
from test_personal import fast_expect


class ClassicLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch('playwright.sync_api.expect', side_effect=fast_expect))

    def test_classic_page_checked_and_pressed_states_are_set_and_verified(self):
        for attribute in ('aria-checked', 'aria-pressed'):
            for initial in ('true', 'false'):
                for desired in (True, False):
                    with self.subTest(attribute=attribute, initial=initial, desired=desired):
                        self.page.set_content('''<button id="label" aria-label="Add AI label We require you to label content"
                        %s="%s" onclick="window.changes=(window.changes||0)+1;
                        this.setAttribute('%s',this.getAttribute('%s')==='true'?'false':'true')">AI</button>
                        <button onclick="window.postClicks=1">Post</button>''' % (attribute, initial, attribute, attribute))
                        self.page.evaluate('window.changes=0;window.postClicks=0')
                        upload.set_ai_label(self.page, {'type':'page', 'ai_label':desired})
                        self.assertEqual(self.page.locator('#label').get_attribute(attribute), str(desired).lower())
                        self.assertEqual(self.page.evaluate('window.changes'), int((initial=='true') != desired))
                        self.assertEqual(self.page.evaluate('window.postClicks'), 0)

    def test_nested_switch_is_verified_after_turning_off(self):
        self.page.set_content('''<button aria-label="Add AI label We require you to label content"
        onclick="document.querySelector('[role=switch]').setAttribute('aria-checked','false')">
        <span role="switch" aria-checked="true">AI</span></button>''')
        upload.set_ai_label(self.page, {'type':'page', 'ai_label':False})
        self.assertEqual(self.page.get_by_role('switch').get_attribute('aria-checked'), 'false')

    def test_unknown_state_is_not_clicked(self):
        self.page.set_content('''<button aria-label="Add AI label We require you"
        onclick="window.changes=1">AI</button>''')
        with self.assertRaisesRegex(RuntimeError, '无法确认'):
            upload.set_ai_label(self.page, {'type':'page', 'ai_label':False})
        self.assertIsNone(self.page.evaluate('window.changes'))

    def test_unsaved_off_state_is_rejected(self):
        self.page.set_content('''<button aria-label="Add AI label We require you"
        aria-pressed="true" onclick="window.clicks=1">AI</button>''')
        with self.assertRaises(AssertionError):
            upload.set_ai_label(self.page, {'type':'page', 'ai_label':False})


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root/'upload_config.json'))
        self.stack.enter_context(patch.object(batch, 'ROOT', self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry = dict(account='fb01', target='page01', type='page', name='Example Page',
                          url='https://www.facebook.com/profile.php?id=1001', enabled=True,
                          prepared_at='old-review', ai_label=True)
        upload.save_json(upload.CONFIG, {'targets':[self.entry]})
        (self.root/'profiles/fb01').mkdir(parents=True)
        self.folder = upload.inbox_for(self.entry)
        self.folder.mkdir(parents=True)
        self.video = self.folder/'1.mp4'
        self.video.write_bytes(b'fixture media')
        self.video.with_suffix('.txt').write_text('Common caption with link https://example.com/')
        for path in self.folder.iterdir():
            os.utime(path, (time.time()-120,time.time()-120))
        self.state_path = self.root/'logs/publish_state.json'
        upload.save_json(self.state_path, {})

    def test_publish_cli_passes_off_without_rewriting_config(self):
        before = upload.CONFIG.read_bytes()
        with patch('sys.argv', ['fb_upload.py','publish','--account','fb01','--target','page01','--ai-label','off']), \
                patch.object(upload, 'run_entry', return_value=True) as run:
            self.assertEqual(upload.main(), 0)
        self.assertIs(run.call_args.kwargs['ai_label_override'], False)
        self.assertEqual(upload.CONFIG.read_bytes(), before)

    def test_prepare_off_saves_review_but_retains_default_and_enabled(self):
        with patch('sys.argv', ['fb_upload.py','prepare','--account','fb01','--target','page01','--ai-label','off']), \
                patch.object(upload, 'run_entry', return_value=True) as run:
            self.assertEqual(upload.main(), 0)
        row = upload.read_json(upload.CONFIG,{})['targets'][0]
        self.assertTrue(row['ai_label'])
        self.assertTrue(row['enabled'])
        self.assertNotEqual(row['prepared_at'], 'old-review')
        self.assertIs(run.call_args.kwargs['ai_label_override'], False)

    def test_run_uses_off_copy_and_records_request_without_changing_default(self):
        context = MagicMock()
        context.pages = [MagicMock()]
        button = MagicMock()
        before = upload.CONFIG.read_bytes()
        with patch('playwright.sync_api.sync_playwright'), \
                patch.object(upload, 'launch_context', return_value=context), \
                patch.object(upload, 'prepare_reel', return_value=(button,{'method':'page_actor_id_match'})) as prepare, \
                patch.object(upload, 'recheck_publish_identity'), \
                patch.object(upload, 'install_receipt_watch'), \
                patch.object(upload, 'wait_for_receipt', side_effect=upload.ReceiptNeedsReview('receipt timeout')):
            with self.assertRaises(upload.ReceiptNeedsReview):
                upload.run_entry(self.entry, {}, self.state_path, True, ai_label_override=False)
        self.assertIs(prepare.call_args.args[1]['ai_label'], False)
        self.assertTrue(self.entry['ai_label'])
        self.assertEqual(upload.CONFIG.read_bytes(), before)
        row = next(iter(upload.read_json(self.state_path,{}).values()))
        self.assertIs(row['ai_label_requested'], False)
        self.assertEqual(row['status'], 'needs_review')
        button.click.assert_called_once()

    def test_batch_forwards_off_to_every_child(self):
        entries = [dict(self.entry,account='fb%02d'%i) for i in range(1,14)]
        with patch.object(batch.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            results = batch.execute(entries,'publish', ai_label='off')
        self.assertEqual(len(results),13)
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(args[args.index('--ai-label')+1], 'off')

    def test_batch_cli_off_does_not_change_stored_defaults(self):
        before = upload.CONFIG.read_bytes()
        with patch('sys.argv',['batch_upload.py','publish','--accounts=fb01','--ai-label=off']), \
                patch.object(batch.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(batch.main(),0)
        self.assertIn('--ai-label', run.call_args.args[0])
        self.assertEqual(upload.CONFIG.read_bytes(),before)

    def test_invalid_actions_reject_override_before_locks(self):
        for module, argv in ((upload,['fb_upload.py','status','--ai-label=off']),
                             (batch,['batch_upload.py','enable','--accounts=fb01','--ai-label=off'])):
            with self.subTest(argv=argv), patch('sys.argv',argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    module.main()
                self.assertEqual(error.exception.code,2)
                self.assertFalse((self.root/'logs/upload.lock').exists())
                self.assertFalse((self.root/'logs/batch.lock').exists())


if __name__ == '__main__':
    unittest.main()
