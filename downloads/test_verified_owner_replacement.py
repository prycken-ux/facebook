import copy,hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import fb_upload as upload


class VerifiedOwnerReplacementTests(unittest.TestCase):
    def setUp(self):
        self.entry=dict(account='fb17',target='personal',type='personal',workflow='personal_recording_v1',name='Verified new owner',url='https://www.facebook.com/profile.php?id=2002',enabled=True,verified_owner_replacement=dict(version=upload.VERIFIED_OWNER_REPLACEMENT_VERSION,previous_target_key='id:1001',current_target_key='id:2002',session_marker=hashlib.sha256(b'personal:2002').hexdigest(),verified_at='2026-11-12T04:00:00+00:00'))
        self.state={'old-key':dict(account='fb17',target='personal',url='https://www.facebook.com/profile.php?id=1001',status='needs_review')}
    def test_exact_frozen_new_owner_job_does_not_remove_or_rewrite_old_person_review(self):
        before=copy.deepcopy(self.state)
        with tempfile.TemporaryDirectory() as folder,patch.object(upload,'named_job',return_value=None),patch.object(upload,'save_json',side_effect=AssertionError('history must stay untouched')):
            self.assertFalse(upload.run_entry(self.entry,self.state,Path(folder)/'state.json',True,filename='failed-yesterday.mp4',expected_job_key='a'*64,preserve_old_review_for_exact_job=True))
        self.assertEqual(self.state,before)
    def test_unknown_proof_current_owner_and_active_old_submission_remain_blocked(self):
        for change in [('swap',None),('swap',dict(self.entry['verified_owner_replacement'],session_marker='wrong')),('status','posting'),('status','preparing'),('url',self.entry['url'])]:
            entry=copy.deepcopy(self.entry);state=copy.deepcopy(self.state)
            if change[0]=='swap':entry['verified_owner_replacement']=change[1]
            else:state['old-key'][change[0]]=change[1]
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises((RuntimeError,ValueError)):upload.run_entry(entry,state,Path(folder)/'state.json',True,filename='failed-yesterday.mp4',expected_job_key='a'*64,preserve_old_review_for_exact_job=True)
    def test_legacy_unbound_publish_cannot_use_the_replacement_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):upload.run_entry(self.entry,self.state,Path(folder)/'state.json',True,filename='failed-yesterday.mp4')


if __name__=='__main__':unittest.main()
