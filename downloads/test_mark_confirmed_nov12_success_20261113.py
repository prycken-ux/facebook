import copy
import hashlib
import unittest
from unittest.mock import patch

import mark_confirmed_nov12_success_20261113 as app
from test_scheduled_material_batch import ScheduledMaterialTests


class MarkConfirmedTests(unittest.TestCase):
    def setUp(self):
        self.fx = ScheduledMaterialTests()
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)
        self.root = self.fx.root
        state, sources = {}, []
        for index, (pointer, _, spec, field, scope) in enumerate(app.SOURCES):
            jobs = []
            for (account, target), (filename, name) in spec.items():
                key = hashlib.sha256((account+target+filename).encode()).hexdigest()
                url = 'https://www.facebook.com/profile.php?id='+str(100000+len(state))
                job = dict(account=account, target=target, filename=filename, key=key, url=url)
                jobs.append(job)
                state[key] = dict(account=account, target=target, video=str(self.root/'videos'/account/target/'inbox'/filename),
                                  url=url, status='needs_review' if index == 0 else 'published',
                                  post_intent_at='2026-11-13T04:00:00+00:00',
                                  review_reason='publication_receipt_timeout' if index == 0 else '',
                                  error='timeout' if index == 0 else '', comment_status='sent' if account == 'fb16' else 'not_requested')
            payload = dict(schema=app.batch.SCHEMA, date='2026-11-13', jobs=jobs,
                           selected_names={j['key']: spec[(j['account'], j['target'])][1] for j in jobs}, **{field: scope})
            checksum = app.batch.digest(payload)
            path = self.root/'logs'/('frozen-material-2026-11-13-'+checksum[:16]+'.json')
            app.upload.save_json(path, dict(payload=payload, sha256=checksum))
            app.upload.save_json(self.root/'logs'/pointer, dict(manifest=path.name, sha256=checksum))
            sources.append((pointer, checksum[:8], spec, field, scope))
        state['other-failed'] = dict(account='fb02', target='page01', status='failed_before_post')
        state['other-pending'] = dict(account='fb24', target='personal', status='needs_review')
        state['interrupted'] = dict(account='fb15', target='personal', status='preparing')
        self.before = copy.deepcopy(state)
        app.upload.save_json(self.fx.state_path, state)
        self.comments = self.root/'logs/video_comments.json'
        app.upload.save_json(self.comments, {'already-sent': {'status': 'sent'}})
        self.comment_bytes = self.comments.read_bytes()
        self.sources_before = {p: p.read_bytes() for p in (self.root/'logs').glob('frozen-*.json')}
        self.enterContext(patch.object(app, 'SOURCES', tuple(sources)))

    def test_only_four_confirmed_records_change_and_no_upload_or_comment(self):
        with patch.object(app.upload, 'run_entry', side_effect=AssertionError('No upload')), \
                patch('safe_video_comments.after_publication', side_effect=AssertionError('No comments')):
            self.assertEqual(app.execute(), 0)
        state = app.upload.read_json(self.fx.state_path, {})
        for key, old in self.before.items():
            row = state[key]
            if (old.get('account'), old.get('target')) in app.PERSONALS:
                self.assertEqual(row['status'], 'published')
                self.assertEqual(row['confirmation_method'], app.METHOD)
                self.assertEqual(row['comment_status'], old['comment_status'])
                self.assertEqual(row['post_intent_at'], old['post_intent_at'])
            else:
                self.assertEqual(row, old)
        self.assertEqual(self.comments.read_bytes(), self.comment_bytes)
        for path, data in self.sources_before.items():
            self.assertEqual(path.read_bytes(), data)
        before = self.fx.state_path.read_bytes()
        self.assertEqual(app.execute(), 0)
        self.assertEqual(self.fx.state_path.read_bytes(), before)

    def test_changed_previously_successful_state_aborts_all_marks(self):
        state = copy.deepcopy(self.before)
        row = next(r for r in state.values() if (r.get('account'), r.get('target')) in app.PAGES)
        row['status'] = 'needs_review'
        app.upload.save_json(self.fx.state_path, state)
        before = self.fx.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '最新状态'):
            app.execute()
        self.assertEqual(self.fx.state_path.read_bytes(), before)

    def test_tampered_manifest_or_missing_record_never_guesses_success(self):
        path = next(iter(self.sources_before))
        value = app.upload.read_json(path, {})
        value['payload']['jobs'][0]['filename'] = 'different.mp4'
        app.upload.save_json(path, value)
        before = self.fx.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '清单校验'):
            app.execute()
        self.assertEqual(self.fx.state_path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
