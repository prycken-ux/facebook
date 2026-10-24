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

class FourteenManifestTests(ReconcileTests):
    def complete_manifest(self):
        self.report['final_rows'] = []
        for key, record in self.state.items():
            if key == self.old_key:
                continue
            self.report['final_rows'].append(dict(account=record['account'], target=record['target'],
                key=key, filename=tool.basename(record['video']), status=record['status']))
        self.save()

    def test_new_round_page_uses_exact_manifest_filename_instead_of_old_k1(self):
        self.complete_manifest()
        extra = self.entries[-1]
        old = upload.inbox_for(extra) / 'k1.mp4'
        new = old.with_name('新产品14.mp4')
        old.rename(new)
        old.with_suffix('.txt').rename(new.with_suffix('.txt'))
        key = upload.job_key(extra, new)
        self.state[key]['video'] = str(new)
        self.report['final_rows'][-1]['filename'] = new.name
        self.save()
        self.assertEqual(tool.reconcile(True), 0)
        self.assertTrue((new.parent.parent / 'completed' / new.name).exists())

    def test_new_round_manifest_empty_directory_cannot_use_historical_success(self):
        self.complete_manifest()
        self.report['final_rows'][0].update(key=None, filename='', status='inbox_empty')
        self.save()
        with self.assertRaisesRegex(ValueError, '空目录'):
            tool.reconcile(True)

class ConfirmedBeforePostTests(unittest.TestCase):
    def setUp(self):
        ReconcileTests.setUp(self)
        self.report['schema'] = 'fourteen-current-publication-v1'
        self.report['phase'] = 'attempts_finished'
        self.report['final_rows'] = [dict(account=row['account'], target=row['target'], key=key,
            filename=tool.basename(row['video']), status=row['status']) for key, row in self.state.items() if key != self.old_key]
        self.key = self.report['final_rows'][-1]['key']
        self.state[self.key].update(status='failed_before_post', error='original Next click timeout')
        self.report['final_rows'][-1]['status'] = 'failed_before_post'
        self.report['rows'] = copy.deepcopy(self.report['final_rows'])
        self.path = self.root / 'logs/current-audit-20261022-103000.json'
        self.audit_path.unlink()
        self.audit_path = self.path
        self.save()

    save = ReconcileTests.save

    def tearDown(self):
        ReconcileTests.tearDown(self)

    def test_bound_full_confirmation_includes_before_post_record_preserves_error_and_old_proofs(self):
        before = copy.deepcopy(self.state)
        self.assertEqual(tool.reconcile(True, '2026-10-22T10:30:00', True), 0)
        state = upload.read_json(self.state_path, {})
        self.assertEqual(state[self.key]['status'], 'published')
        self.assertEqual(state[self.key]['error'], 'original Next click timeout')
        self.assertTrue(state[self.key]['user_verified_post_despite_before_post_error'])
        self.assertEqual(state[self.old_key], before[self.old_key])
        for key, old in before.items():
            if old['status'] == 'published':
                self.assertEqual(state[key], old)
        report = upload.read_json(self.path, {})
        self.assertTrue(all(row['status'] == 'published' for row in report['final_rows']))
        self.assertEqual(report['rows'], self.report['rows'])
        self.assertTrue(self.path.with_suffix('.csv').exists())
        self.assertEqual(tool.reconcile(True, '2026-10-22T10:30:00', True), 0)

    def test_before_post_record_requires_explicit_existing_video_confirmation(self):
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '尚未处于'):
            tool.reconcile(True, '2026-10-22T10:30:00')
        self.assertEqual(before, self.state_path.read_bytes())

    def test_bound_confirmation_does_not_apply_to_a_newer_actual_round(self):
        newer = self.root / 'logs/current-audit-20261024-103000.json'
        upload.save_json(newer, dict(self.report, created='2026-10-24T10:30:00+08:00'))
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '批次不同'):
            tool.reconcile(True, '2026-10-22T10:30:00', True)
        self.assertEqual(before, self.state_path.read_bytes())
        self.assertFalse((self.root / 'backups').exists())

    def test_newer_read_only_plan_does_not_replace_actual_confirmed_round(self):
        newer = self.root / 'logs/current-audit-20261024-103000.json'
        upload.save_json(newer, dict(self.report, phase='plan_only', created='2026-10-24T10:30:00+08:00'))
        self.assertEqual(tool.reconcile(True, '2026-10-22T10:30:00', True), 0)

    def test_missing_file_stops_before_marking_a_failed_record_successful(self):
        entry = self.entries[-1]
        (upload.inbox_for(entry) / 'k1.mp4').unlink()
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '不在 inbox'):
            tool.reconcile(True, '2026-10-22T10:30:00', True)
        self.assertEqual(before, self.state_path.read_bytes())
        self.assertFalse((self.root / 'backups').exists())
