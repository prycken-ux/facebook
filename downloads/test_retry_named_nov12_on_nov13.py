import contextlib
import copy
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import retry_named_nov12_on_nov13 as app
import publish_today_20261112 as nov12
from test_publish_today_20261112 import Nov12NewVideosTests


class NamedRetryTests(unittest.TestCase):
    def setUp(self):
        self.base = Nov12NewVideosTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.root = self.base.root
        pairs = [('fb11', 'personal'), ('fb12', 'page01'), ('fb13', 'page01'), ('fb14', 'personal'),
                 ('fb15', 'personal'), ('fb19', 'personal'), ('fb20', 'personal'), ('fb22', 'personal'),
                 ('fb23', 'personal'), ('fb02', 'page01'), ('fb10', 'page02'), ('fb10', 'page01'),
                 ('fb10', 'page07'), ('fb10', 'page08'), ('fb10', 'page09')]
        self.mapping = dict(zip(app.NAMES, pairs))
        with nov12.old.locked():
            parent, original = nov12.old_sources()
            nov12.ready_personals(parent)
            config = app.upload.read_json(app.upload.CONFIG, {})
            for name, pair in self.mapping.items():
                next(e for e in config['targets'] if (e['account'], e['target']) == pair)['name'] = name
            app.upload.save_json(app.upload.CONFIG, config)
            control_path, control = nov12.today_controller(original)
            nov12.prepare_wave(control_path, control, set())
        self.parent_before = {p: p.read_bytes() for p in (self.root/'logs').glob('*.json')}
        self.old_state = app.upload.read_json(self.root/'logs/publish_state.json', {})
        self.config_before = app.upload.CONFIG.read_bytes()
        self.now = datetime(2026, 11, 13, 5, tzinfo=timezone.utc)
        for module in (app, app.upload, app.batch):
            clock = self.enterContext(patch.object(module, 'datetime', wraps=datetime))
            clock.now.return_value = self.now
        for file in self.root.rglob('*'):
            if file.is_file() and file.suffix in {'.mp4', '.txt'}:
                os.utime(file, (self.now.timestamp()-180,)*2)
        self.jobs = app.source()[0]
        self.assertEqual(len(self.jobs), 15)
        state = copy.deepcopy(self.old_state)
        for index, job in enumerate(self.jobs[:2]):
            state[job['key']] = dict(account=job['account'], target=job['target'], url=job['url'],
                                    video=str(self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']),
                                    status='failed_before_post' if index == 0 else 'needs_review',
                                    created='2026-11-12T04:00:00+00:00', uploader_version='2.47', ai_label_requested=False)
            if index:
                state[job['key']]['post_intent_at'] = '2026-11-12T04:01:00+00:00'
        self.before = copy.deepcopy(state)
        app.upload.save_json(self.root/'logs/publish_state.json', state)
        self.comments_path = self.root/'logs/video_comments.json'
        app.upload.save_json(self.comments_path, {'previous-user-comments': {'status': 'sent'}})
        self.comment_bytes = self.comments_path.read_bytes()
        self.parent_before[self.comments_path] = self.comment_bytes

    def core(self, unknown=False, lookup=False, interrupt=False):
        browser = MagicMock()
        browser.pages = [MagicMock()]
        browser.pages[0].context = browser
        button = MagicMock()
        active = {}
        posted = []
        def prepare(page, entry, video, caption, **kwargs):
            active['pair'] = entry['account'], entry['target']
            self.assertIn(active['pair'], set(self.mapping.values()))
            original = next(j for j in self.jobs if (j['account'], j['target']) == active['pair'])
            self.assertEqual(video.name, original['filename'])
            self.assertEqual(app.batch.file_hash(video), original['video_sha256'])
            return button, {}
        def click(**kwargs):
            posted.append(active['pair'])
            if interrupt:
                raise KeyboardInterrupt
        button.click.side_effect = click
        finder = MagicMock(return_value=('https://www.facebook.com/reel/9001', 'verified_owner_caption_time'),
                           side_effect=None if lookup else ValueError('no unique match'))
        with patch.object(app.normal, 'launcher_for_jobs', return_value=lambda *args: browser) as launcher, \
                patch('playwright.sync_api.sync_playwright'), patch.object(app, 'close_selected_window'), \
                patch.object(app.upload, 'prepare_reel', side_effect=prepare), patch.object(app.upload, 'recheck_publish_identity'), \
                patch.object(app.upload, 'install_receipt_watch'), \
                patch.object(app.upload, 'wait_for_receipt', return_value='Your reel is published.', side_effect=app.upload.ReceiptNeedsReview('unknown') if unknown else None), \
                patch('safe_video_comments.resolve_published_link', return_value=('https://www.facebook.com/reel/9001', 'fresh_success_view_reel_link')), \
                patch('safe_video_comments.after_publication', side_effect=AssertionError('No comments authorized')), \
                patch('safe_video_comments.immediate_verified_comment', side_effect=AssertionError('No comments authorized')), \
                patch('daily_publish_and_comments.backfill', side_effect=AssertionError('No comment backfill')), \
                patch('automatic_comment_retry.run', side_effect=AssertionError('No comment retry')), \
                patch.object(app.actual, 'make_finder', return_value=finder), \
                patch.object(app.personal, 'scoped', side_effect=lambda *a: contextlib.nullcontext()), \
                patch.object(app.numeric, 'scoped', side_effect=lambda *a: contextlib.nullcontext()), \
                patch.object(app.upload, 'ensure_identity', return_value={}), \
                patch('builtins.input', side_effect=AssertionError('No name re-entry')):
            if interrupt:
                with self.assertRaises(KeyboardInterrupt):
                    app.execute()
                result = 130
            else:
                result = app.execute()
        self.assertTrue(all(c.kwargs['date'] == app.DAY for c in launcher.call_args_list))
        return result, posted, finder

    def test_exact_fifteen_once_no_comments_and_preserve_other_state_source_and_future_files(self):
        later = self.root/'videos/fb11/personal/inbox/newer.mp4'
        later.write_bytes(b'do not publish this newer file')
        result, posted, finder = self.core()
        self.assertEqual(result, 0)
        self.assertEqual(set(posted), set(self.mapping.values()))
        self.assertEqual(len(posted), 15)
        finder.assert_not_called()
        state = app.upload.read_json(self.root/'logs/publish_state.json', {})
        for key, row in self.old_state.items():
            self.assertEqual(state[key], row)
        for job in self.jobs:
            self.assertEqual(state[job['key']]['status'], 'published')
            self.assertEqual(state[job['key']]['comment_status'], 'not_requested')
            self.assertEqual(state[job['key']]['previous_before_post_attempt']['repair_previous_attempt'], self.before.get(job['key']))
        self.assertEqual(app.upload.CONFIG.read_bytes(), self.config_before)
        self.assertEqual(self.comments_path.read_bytes(), self.comment_bytes)
        for path, data in self.parent_before.items():
            if path.name != 'publish_state.json':
                self.assertEqual(path.read_bytes(), data)
        self.assertEqual(later.read_bytes(), b'do not publish this newer file')
        result, posted, _ = self.core()
        self.assertEqual(result, 0)
        self.assertEqual(posted, [])

    def test_receipt_timeouts_are_readonly_rechecked_but_never_reposted(self):
        result, posted, finder = self.core(unknown=True)
        self.assertEqual(result, 3)
        self.assertEqual(len(posted), 15)
        self.assertEqual(finder.call_count, 15)
        result, posted, _ = self.core()
        self.assertEqual(result, 3)
        self.assertEqual(posted, [])

    def test_readonly_unique_proof_confirms_timeout_without_comment_or_second_post(self):
        result, posted, finder = self.core(unknown=True, lookup=True)
        self.assertEqual(result, 0)
        self.assertEqual(len(posted), 15)
        self.assertEqual(finder.call_count, 15)
        state = app.upload.read_json(self.root/'logs/publish_state.json', {})
        for job in self.jobs:
            self.assertEqual(state[job['key']]['confirmation_method'], 'readonly_unique_author_caption_post_time')
        self.assertEqual(self.comments_path.read_bytes(), self.comment_bytes)

    def test_changed_file_fails_only_its_target_and_never_picks_newer_file(self):
        job = self.jobs[0]
        file = self.root/'videos'/job['account']/job['target']/'inbox'/job['filename']
        file.write_bytes(b'changed original')
        result, posted, _ = self.core()
        self.assertEqual(result, 3)
        self.assertEqual(len(posted), 14)
        self.assertNotIn((job['account'], job['target']), posted)

    def test_ambiguous_name_is_reported_without_publishing_either_same_named_target(self):
        config = app.upload.read_json(app.upload.CONFIG, {})
        duplicate = next(e for e in config['targets'] if (e['account'], e['target']) == ('fb09', 'page01'))
        duplicate['name'] = app.NAMES[0]
        app.upload.save_json(app.upload.CONFIG, config)
        result, posted, _ = self.core()
        self.assertEqual(result, 3)
        self.assertEqual(len(posted), 14)
        self.assertNotIn(self.mapping[app.NAMES[0]], posted)
        self.assertTrue(all(pair[0] != 'fb09' for pair in posted))

    def test_known_success_and_active_task_are_never_reset_or_closed(self):
        state = app.upload.read_json(self.root/'logs/publish_state.json', {})
        for job, status in zip(self.jobs[:2], ('published', 'posting')):
            state[job['key']].update(status=status, post_intent_at='2026-11-13T04:00:00+00:00')
        app.upload.save_json(self.root/'logs/publish_state.json', state)
        _, posted, _ = self.core()
        self.assertNotIn((self.jobs[0]['account'], self.jobs[0]['target']), posted)
        self.assertNotIn((self.jobs[1]['account'], self.jobs[1]['target']), posted)
        current = app.upload.read_json(self.root/'logs/publish_state.json', {})
        for job in self.jobs[:2]:
            self.assertEqual(current[job['key']], state[job['key']])

    def test_interrupt_after_post_is_durable_and_resume_only_uploads_other_fourteen(self):
        _, posted, _ = self.core(interrupt=True)
        self.assertEqual(len(posted), 1)
        _, resumed, _ = self.core()
        self.assertEqual(len(resumed), 14)
        self.assertNotIn(posted[0], resumed)

    def test_missing_claims_after_attempt_cannot_grant_another_retry(self):
        self.core(unknown=True)
        (self.root/'logs'/(app.GRANT+'-claims.json')).unlink()
        with self.assertRaisesRegex(ValueError, '账本缺失'):
            self.core()

    def test_record_changed_after_frozen_authorization_is_not_replaced(self):
        _, value = app.prepare()
        _, claims = app.ledger(value)
        state = app.upload.read_json(self.root/'logs/publish_state.json', {})
        state[self.jobs[0]['key']]['created'] = '2026-11-13T06:00:00+00:00'
        with self.assertRaisesRegex(ValueError, '快照后变化'):
            app.checked(self.jobs[0], state, claims)


if __name__ == '__main__':
    unittest.main()
