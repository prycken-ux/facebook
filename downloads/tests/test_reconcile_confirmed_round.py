import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import add_fb_accounts
import fb_upload as upload
import reconcile_confirmed_round as tool


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload, 'ROOT', self.root))
        self.stack.enter_context(patch.object(upload, 'CONFIG', self.root / 'upload_config.json'))
        self.stack.enter_context(patch.object(add_fb_accounts, 'ROOT', self.root))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.launch = self.stack.enter_context(patch.object(upload, 'launch_context', side_effect=AssertionError('browser forbidden')))
        self.entries, self.state, self.rows = [], {}, []
        pending = {'fb03', 'fb04', 'fb07', 'fb08', 'fb10', 'fb11'}
        for index, (account, target) in enumerate((*tool.ORIGINAL, tool.EXTRA), 1):
            entry = dict(account=account, target=target, name=account + target,
                         type='personal' if target == 'personal' else 'page',
                         workflow='personal_recording_v1' if target == 'personal' else 'page_flow_configured',
                         url='https://www.facebook.com/profile.php?id=' + ('61595024556188' if (account, target) == tool.EXTRA else str(10000 + index)))
            self.entries.append(entry)
            needs = account in pending or (account, target) == tool.EXTRA
            folder = upload.inbox_for(entry) if needs else upload.inbox_for(entry).parent / 'completed'
            folder.mkdir(parents=True)
            upload.inbox_for(entry).mkdir(exist_ok=True)
            name = 'k1.mp4' if (account, target) == tool.EXTRA else f'实拍{index}.mp4'
            video = folder / name
            video.write_bytes(f'original-content-{index}'.encode())
            video.with_suffix('.txt').write_text('yesterday caption', encoding='utf-8')
            key = upload.job_key(entry, video)
            record = dict(account=account, target=target, url=entry['url'], video=str(upload.inbox_for(entry) / name),
                          created='2026-10-22T10:00:00+08:00' if needs else '2026-10-21T18:00:00+08:00',
                          status='needs_review' if needs else 'published')
            if needs:
                record.update(error='receipt timeout', review_reason='publication_receipt_timeout')
            else:
                record.update(success_message='fresh success', confirmation_method='fresh_success_ui_and_composer_closed')
            self.state[key] = record
            if (account, target) != tool.EXTRA:
                self.rows.append(dict(account=account, target=target, key=key if needs else None,
                                      filename=name if needs else '', status='needs_review' if needs else 'inbox_empty'))
        self.old_key = 'a' * 64
        self.state[self.old_key] = dict(account='fb03', target='personal', url=self.entries[2]['url'],
                                        status='needs_review', video=r'E:\FB-AutoUpload\videos\fb03\personal\inbox\old.mp4',
                                        created='2026-10-20T10:00:00+08:00', error='old uncertainty')
        self.report = dict(created='2026-10-22T10:30:00+08:00', final_rows=self.rows)
        self.audit_path = self.root / 'logs/current-audit-test.json'
        self.state_path = self.root / 'logs/publish_state.json'
        upload.save_json(upload.CONFIG, {'targets': self.entries})
        self.save()

    def save(self):
        upload.save_json(self.state_path, self.state)
        upload.save_json(self.audit_path, self.report)

    def tearDown(self):
        self.launch.assert_not_called()
        self.stack.close()
        self.temp.cleanup()

    def test_all_fourteen_archive_exact_current_content_and_preserve_old_unknowns_and_proofs(self):
        before = self.state_path.read_bytes()
        self.assertEqual(tool.reconcile(True), 0)
        after = upload.read_json(self.state_path, {})
        self.assertEqual(after[self.old_key], self.state[self.old_key])
        self.assertEqual(sum(r['status'] == 'published' for r in after.values()), 14)
        for key, previous in self.state.items():
            if previous['status'] == 'published':
                self.assertEqual(after[key], previous)
            elif key != self.old_key:
                self.assertEqual(after[key]['error'], previous['error'])
                self.assertEqual(after[key]['confirmation_method'], 'user_confirmed_existing_post_no_link')
        backups = list((self.root / 'backups').glob('confirmed-fourteen-*/publish_state.json'))
        self.assertEqual(backups[0].read_bytes(), before)
        report = upload.read_json(next((self.root / 'logs').glob('confirmed-fourteen-*.json')), {})
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(len(report['rows']), 14)
        self.assertEqual(report['preserved_older_reviews'], [self.old_key])
        for row in report['rows']:
            self.assertTrue(Path(row['archived_video']).is_file())
            self.assertTrue(Path(row['archived_caption']).is_file())
        self.assertEqual(len(list((self.root / 'logs').glob('confirmed-fourteen-*.csv'))), 1)

    def test_repeated_run_preserves_ledger_and_archive(self):
        tool.reconcile(True)
        before = self.state_path.read_bytes()
        self.assertEqual(tool.reconcile(True), 0)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(len(list((self.root / 'videos').glob('*/*/completed/*.mp4'))), 14)

    def test_changed_current_content_causes_zero_mutation(self):
        entry = self.entries[2]
        path = next(upload.inbox_for(entry).glob('*.mp4'))
        path.write_bytes(b'replacement')
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '已变化'):
            tool.reconcile(True)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertFalse((self.root / 'backups').exists())

    def test_new_page_requires_correct_id(self):
        config = dict(targets=copy.deepcopy(self.entries))
        config['targets'][-1]['url'] = 'https://www.facebook.com/profile.php?id=999999'
        upload.save_json(upload.CONFIG, config)
        with self.assertRaisesRegex(ValueError, '新增公共主页'):
            tool.reconcile(True)

    def test_newest_incomplete_audit_cannot_fall_back_to_old_report(self):
        upload.save_json(self.root / 'logs/current-audit-new.json', {'created': self.report['created'], 'rows': self.rows})
        with self.assertRaisesRegex(ValueError, '完整'):
            tool.reconcile(True)
        self.assertFalse((self.root / 'backups').exists())

    def test_missing_pending_source_does_not_mark_old_record(self):
        entry = self.entries[2]
        next(upload.inbox_for(entry).glob('*.mp4')).unlink()
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '不在 inbox'):
            tool.reconcile(True)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_unattempted_current_file_is_not_included_in_confirmation(self):
        key = self.rows[2]['key']
        self.state[key]['status'] = 'failed_before_post'
        self.save()
        with self.assertRaisesRegex(ValueError, '尚未处于'):
            tool.reconcile(True)

    def test_no_confirmation_flag_no_changes(self):
        with self.assertRaisesRegex(ValueError, '用户已确认'):
            tool.reconcile(False)
        self.assertFalse((self.root / 'backups').exists())

    def test_upload_lock_is_respected(self):
        lock = self.root / 'logs/upload.lock'
        lock.write_text('already-running')
        with self.assertRaisesRegex(RuntimeError, '锁'):
            tool.reconcile(True)
        self.assertEqual(lock.read_text(), 'already-running')
        self.assertFalse((self.root / 'logs/batch.lock').exists())

    def test_archive_collision_keeps_both_pairs_and_repeat_works(self):
        entry = self.entries[2]
        video = next(upload.inbox_for(entry).glob('*.mp4'))
        folder = video.parent.parent / 'completed'
        folder.mkdir()
        existing = folder / video.name
        existing.write_bytes(b'historical media')
        existing.with_suffix('.txt').write_text('historical caption')
        self.assertEqual(tool.reconcile(True), 0)
        self.assertEqual(existing.read_bytes(), b'historical media')
        self.assertEqual(len(list(folder.glob('*/' + video.name))), 1)
        self.assertEqual(tool.reconcile(True), 0)

    def test_archive_error_keeps_success_and_reports_incomplete(self):
        with patch.object(upload, 'archive', side_effect=OSError('disk unavailable')):
            self.assertEqual(tool.reconcile(True), 1)
        report = upload.read_json(next((self.root / 'logs').glob('confirmed-fourteen-*.json')), {})
        self.assertEqual(report['status'], 'archive_incomplete')
        self.assertEqual(sum(r['status'] == 'published_archive_incomplete' for r in report['rows']), 7)
        self.assertEqual(sum(r['status'] == 'published' for r in upload.read_json(self.state_path, {}).values()), 14)
        self.assertEqual(tool.reconcile(True), 0)


if __name__ == '__main__':
    unittest.main()
