import copy
import unittest
from unittest.mock import patch

import confirm_selected_round as confirm
import fb_upload as upload
import test_retry_failed_with_switch as fixture


class SelectedConfirmationTests(unittest.TestCase):
    setUp=fixture.RetryTests.setUp
    tearDown=fixture.RetryTests.tearDown
    age_captions=fixture.RetryTests.age_captions

    def run_confirmation(self):
        return confirm.confirm(fixture.ROUND,fixture.TARGETS,True)

    def test_confirms_only_six_exact_source_keys_and_preserves_other_records(self):
        original=copy.deepcopy(self.state)
        with patch.object(upload,'run_entry') as publish:
            self.assertEqual(self.run_confirmation(),0)
        publish.assert_not_called()
        state=upload.read_json(self.state_path,{})
        for key,record in original.items():
            if (record['account'],record['target']) in fixture.TARGETS:
                self.assertEqual(state[key]['status'],'published')
                self.assertEqual(state[key]['error'],record['error'])
                self.assertEqual(state[key]['status_before_user_confirmation'],'failed_before_post')
                video=self.videos[self.keys.index(key)]
                self.assertFalse(video.exists())
                self.assertTrue((video.parent.parent/'completed'/video.name).exists())
            else:
                self.assertEqual(state[key],record)
        report=upload.read_json(self.path,{})
        self.assertEqual(report['rows'],self.payload['rows'])
        self.assertEqual(report['results'],self.payload['results'])
        self.assertEqual(len(report['selected_user_confirmations']),1)

    def test_repeating_does_not_replace_success_evidence_or_republish(self):
        self.run_confirmation()
        before=self.state_path.read_bytes()
        with patch.object(upload,'run_entry') as publish:
            self.assertEqual(self.run_confirmation(),0)
        publish.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(),before)
        self.assertEqual(len(upload.read_json(self.path,{})['selected_user_confirmations']),1)

    def test_replaced_same_name_video_is_not_archived_or_confirmed_as_old_content(self):
        video=self.videos[1]
        key=self.keys[1]
        video.write_bytes(b'different newly copied content with reused name')
        replacement=upload.job_key(self.entries[1],video)
        self.run_confirmation()
        state=upload.read_json(self.state_path,{})
        self.assertEqual(state[key]['status'],'published')
        self.assertNotIn(replacement,state)
        self.assertTrue(video.exists())
        self.assertEqual(video.read_bytes(),b'different newly copied content with reused name')

    def test_missing_record_stops_entire_preflight_before_any_confirmation(self):
        state=copy.deepcopy(self.state)
        del state[self.keys[1]]
        upload.save_json(self.state_path,state)
        before=self.state_path.read_bytes()
        with self.assertRaises(ValueError):
            self.run_confirmation()
        self.assertEqual(self.state_path.read_bytes(),before)
        self.assertTrue(self.videos[1].exists())

    def test_wrong_round_or_empty_source_slot_is_never_replaced_with_latest_success(self):
        before=self.state_path.read_bytes()
        with self.assertRaises(ValueError):
            confirm.confirm('2026-10-25T17:53:46',fixture.TARGETS,True)
        with self.assertRaisesRegex(ValueError,'确切素材指纹'):
            confirm.confirm(fixture.ROUND,[('fb10','page01')],True)
        self.assertEqual(self.state_path.read_bytes(),before)

    def test_identity_conflict_or_unconfirmed_operation_does_not_write_state(self):
        before=self.state_path.read_bytes()
        with self.assertRaises(ValueError):
            confirm.confirm(fixture.ROUND,fixture.TARGETS,False)
        config=copy.deepcopy(self.config)
        config['targets'][1]['url']='https://www.facebook.com/profile.php?id=99999'
        upload.save_json(upload.CONFIG,config)
        with self.assertRaises(ValueError):
            self.run_confirmation()
        self.assertEqual(self.state_path.read_bytes(),before)

    def test_published_record_with_link_keeps_its_existing_confirmation(self):
        state=copy.deepcopy(self.state)
        record=state[self.keys[1]]
        record.update(status='published',permalink='https://www.facebook.com/reel/12345',
            success_message='Your reel is published.',confirmation_method='fresh_success_ui_and_composer_closed')
        upload.save_json(self.state_path,state)
        self.run_confirmation()
        self.assertEqual(upload.read_json(self.state_path,{})[self.keys[1]],record)

    def test_existing_lock_is_preserved(self):
        lock=self.root/'logs/batch.lock'
        lock.write_bytes(b'other task')
        before=self.state_path.read_bytes()
        with self.assertRaises(RuntimeError):
            self.run_confirmation()
        self.assertEqual(lock.read_bytes(),b'other task')
        self.assertEqual(self.state_path.read_bytes(),before)

    def test_archival_error_cannot_erase_confirmed_success_guard(self):
        with patch.object(upload,'archive',side_effect=OSError('archive disk full')):
            self.assertEqual(self.run_confirmation(),0)
        state=upload.read_json(self.state_path,{})
        self.assertTrue(all(state[row['key']]['status']=='published' for row in self.rows
                            if (row['account'],row['target']) in fixture.TARGETS))
        self.assertTrue(self.videos[1].exists())


if __name__=='__main__':
    unittest.main()
