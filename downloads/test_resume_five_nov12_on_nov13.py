import contextlib
import copy
import io
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import resume_five_nov12_on_nov13 as app
import publish_today_20261112 as nov12
from test_publish_today_20261112 import Nov12NewVideosTests


class FiveContinuationTests(unittest.TestCase):
    def setUp(self):
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.base = Nov12NewVideosTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.root = self.base.root
        with nov12.old.locked():
            parent, original = nov12.old_sources()
            nov12.ready_personals(parent)
            for account, filename in app.EXPECTED.items():
                old = self.root/'videos'/account/'personal/inbox'/self.base.expected[(account, 'personal')][0]
                old.rename(old.with_name(filename))
                self.base.expected[(account, 'personal')] = (filename, nov12.old.batch.file_hash(old.with_name(filename)))
            control_path, control = nov12.today_controller(original)
            nov12.prepare_wave(control_path, control, set())
        self.protected = {path: path.read_bytes() for path in (self.root/'logs').glob('*.json')}
        self.state_before = app.upload.read_json(self.root/'logs/publish_state.json', {})
        self.now = datetime(2026, 11, 13, 4, tzinfo=timezone.utc)
        for module in (app, app.upload, app.batch, app.priority.retry, app.priority.comment_retry):
            clock = self.enterContext(patch.object(module, 'datetime', wraps=datetime))
            clock.now.return_value = self.now
        for path in self.root.rglob('*'):
            if path.is_file() and path.suffix in {'.mp4', '.txt'}:
                os.utime(path, (self.now.timestamp()-180,)*2)

    def run_core(self, unknown=False, fail_once=False):
        browser = MagicMock()
        browser.pages = [MagicMock()]
        button = MagicMock()
        posted = []
        active = {}
        failures = set()
        def prepare(page, entry, video, caption, **kwargs):
            self.assertIn(entry['account'], app.EXPECTED)
            self.assertEqual(entry['target'], 'personal')
            self.assertEqual(video.name, app.EXPECTED[entry['account']])
            active['account'] = entry['account']
            if fail_once and entry['account'] == 'fb17' and 'fb17' not in failures:
                failures.add('fb17')
                raise RuntimeError('net::ERR_CONNECTION_CLOSED')
            return button, {}
        button.click.side_effect = lambda **kwargs: posted.append(active['account'])
        def comments(value, *args, **kwargs):
            self.assertEqual(kwargs['only_keys'], {j['key'] for j in value['payload']['jobs']})
            self.assertEqual({j['account'] for j in value['payload']['jobs']}, set(app.EXPECTED))
            state = app.upload.read_json(self.root/'logs/publish_state.json', {})
            for job in value['payload']['jobs']:
                if state.get(job['key'], {}).get('status') == 'published':
                    state[job['key']]['comment_status'] = 'sent'
            app.upload.save_json(self.root/'logs/publish_state.json', state)
        with patch.object(app.normal, 'launcher_for_jobs', return_value=lambda *args: browser) as launcher, \
                patch('playwright.sync_api.sync_playwright'), patch.object(app.batch, 'close_selected_window'), \
                patch.object(app.upload, 'prepare_reel', side_effect=prepare), patch.object(app.upload, 'recheck_publish_identity'), \
                patch.object(app.upload, 'install_receipt_watch'), \
                patch.object(app.upload, 'wait_for_receipt', side_effect=app.upload.ReceiptNeedsReview('unknown') if unknown else None, return_value='Your reel is published.'), \
                patch('safe_video_comments.resolve_published_link', return_value=('https://www.facebook.com/reel/9001', 'fresh_success_view_reel_link')), \
                patch.object(app.priority.daily, 'backfill', side_effect=comments), patch.object(app.priority.comment_retry, 'run', return_value=[]), \
                patch('builtins.input', side_effect=AssertionError('No manual name or AI prompt')):
            result = app.execute()
        self.assertTrue(launcher.call_args_list)
        self.assertTrue(all(call.kwargs.get('date') == app.DAY for call in launcher.call_args_list))
        return result, posted

    def test_exact_five_publish_archive_comment_and_rerun_without_touching_parent_or_other_state(self):
        extra = self.root/'videos/fb17/personal/inbox/newer.mp4'
        extra.write_bytes(b'not authorized in this continuation')
        result, posted = self.run_core()
        self.assertEqual(result, 0)
        self.assertEqual(posted, list(app.EXPECTED))
        state = app.upload.read_json(self.root/'logs/publish_state.json', {})
        for key, record in self.state_before.items():
            self.assertEqual(state[key], record)
        for path, data in self.protected.items():
            if path.name != 'publish_state.json':
                self.assertEqual(path.read_bytes(), data)
        self.assertEqual(extra.read_bytes(), b'not authorized in this continuation')
        result, posted = self.run_core()
        self.assertEqual(result, 0)
        self.assertEqual(posted, [])

    def test_pending_receipts_not_reposted_on_resume(self):
        result, posted = self.run_core(unknown=True)
        self.assertEqual(result, 3)
        self.assertEqual(len(posted), 5)
        result, posted = self.run_core()
        self.assertEqual(result, 3)
        self.assertEqual(posted, [])

    def test_recoverable_prepost_failure_gets_one_retry_after_other_videos(self):
        result, posted = self.run_core(fail_once=True)
        self.assertEqual(result, 0)
        self.assertEqual(posted, ['fb16', 'fb18', 'fb21', 'fb24', 'fb17'])
        ledger = app.upload.read_json(self.root/'logs/automatic_before_post_retry_claims.json', {})
        self.assertEqual(len(ledger['jobs']), 1)
        _, posted = self.run_core()
        self.assertEqual(posted, [])

    def test_changed_asset_or_config_rejected_without_new_manifest(self):
        path = self.root/'videos/fb17/personal/inbox'/app.EXPECTED['fb17']
        path.write_bytes(b'replaced material')
        with self.assertRaisesRegex(ValueError, '原视频'):
            app.prepare()
        self.assertFalse((self.root/'logs'/app.POINTER).exists())

    def test_original_attempt_without_state_cannot_be_reissued(self):
        jobs, origin, _ = app.source_jobs()
        source = self.root/'logs'/origin['plans'][0]['manifest']
        app.upload.save_json(source.with_name(source.stem+'-results.json'), dict(manifest=source.name, attempts=[dict(key=jobs[0]['key'], action='interrupted')]))
        with self.assertRaisesRegex(ValueError, '已有尝试'):
            app.prepare()

    def test_committed_orphan_manifest_reused_after_pointer_loss(self):
        path, value = app.prepare()
        before = path.read_bytes()
        (self.root/'logs'/app.POINTER).unlink()
        self.assertEqual(app.prepare(), (path, value))
        self.assertEqual(path.read_bytes(), before)

    def test_does_not_reopen_existing_failed_or_pending_records(self):
        jobs, _, _ = app.source_jobs()
        state = copy.deepcopy(self.state_before)
        state[jobs[0]['key']] = dict(account='fb16', target='personal', url=jobs[0]['url'], status='failed_before_post', error='net::ERR_CONNECTION_CLOSED')
        state[jobs[1]['key']] = dict(account='fb17', target='personal', url=jobs[1]['url'], status='needs_review', post_intent_at='2026-11-12T10:00:00+00:00')
        app.upload.save_json(self.root/'logs/publish_state.json', state)
        result, posted = self.run_core()
        self.assertEqual(result, 3)
        self.assertEqual(posted, ['fb18', 'fb21', 'fb24'])
        current = app.upload.read_json(self.root/'logs/publish_state.json', {})
        for job in jobs[:2]:
            self.assertEqual(current[job['key']], state[job['key']])


if __name__ == '__main__':
    unittest.main()
