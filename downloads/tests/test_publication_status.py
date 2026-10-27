import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fb_upload as upload
import publication_status as status


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(upload,'ROOT',self.root))
        self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.entry=dict(account='fb14',target='personal',type='personal',workflow='personal_recording_v1',
            url='https://www.facebook.com/profile.php?id=1014',name='Andrew',enabled=True)
        self.key='a'*64
        self.row=dict(account='fb14',target='personal',url=self.entry['url'],filename='today.mp4',key=self.key,
            status='ready',eligible=True)
        self.report=dict(schema='fourteen-current-publication-v1',created='2026-10-26T17:53:46+08:00',
            phase='attempts_finished',rows=[self.row],results=[])
        self.path=self.root/'logs/current-audit-one.json'
        self.state_path=self.root/'logs/publish_state.json'
        self.record=dict(account='fb14',target='personal',url=self.entry['url'],video='today.mp4',
            status='needs_review',error='no receipt')
        upload.save_json(upload.CONFIG,dict(targets=[self.entry]))
        upload.save_json(self.state_path,{self.key:self.record})
        upload.save_json(self.path,self.report)
        (self.root/'profiles/fb14').mkdir(parents=True)

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def collect(self):
        return status.collect('2026-10-26')

    def test_same_video_across_two_report_schemas_is_counted_once_with_current_ledger(self):
        later=copy.deepcopy(self.report)
        later.update(schema='available-current-publication-v1',created='2026-10-26T18:22:38+08:00')
        upload.save_json(self.root/'logs/available-today-two.json',later)
        result=self.collect()
        self.assertEqual(len(result['sources']),2)
        self.assertEqual(result['counts'],dict(needs_review=1))

    def test_previous_video_success_does_not_override_different_current_video_failure(self):
        old_key='b'*64
        self.report['rows'].append(dict(self.row,key=old_key,filename='previous.mp4'))
        upload.save_json(self.path,self.report)
        upload.save_json(self.state_path,{self.key:dict(self.record,status='failed_before_post'),
            old_key:dict(self.record,status='published',video='previous.mp4')})
        result=self.collect()
        self.assertEqual(result['counts'],dict(failed_before_post=1,published=1))
        self.assertEqual(len(result['rows']),2)

    def test_no_new_or_empty_slots_are_never_counted_as_published(self):
        self.report['rows']=[dict(self.row,key=None,filename='',status='no_new_video')]
        upload.save_json(self.path,self.report)
        result=self.collect()
        self.assertEqual(result['rows'],[])
        self.assertEqual(len(result['no_material_rows']),1)
        self.assertEqual(result['counts'],{})

    def test_report_success_without_ledger_does_not_prove_success(self):
        upload.save_json(self.state_path,{})
        self.report['final_rows']=[dict(self.row,status='published')]
        self.report['results']=[dict(self.row,status='attempt_finished')]
        upload.save_json(self.path,self.report)
        self.assertEqual(self.collect()['rows'][0]['status'],'needs_check')

    def test_unknown_cached_report_without_ledger_is_still_a_do_not_repost_case(self):
        upload.save_json(self.state_path,{})
        self.report['final_rows']=[dict(self.row,status='needs_review')]
        upload.save_json(self.path,self.report)
        self.assertEqual(self.collect()['rows'][0]['status'],'needs_review')

    def test_latest_ledger_success_overrides_old_report_failure_and_never_opens_it(self):
        upload.save_json(self.state_path,{self.key:dict(self.record,status='published')})
        self.assertEqual(self.collect()['counts'],dict(published=1))
        with patch.object(status.sys,'platform','win32'),patch.object(status,'find_chrome',return_value='chrome.exe'), \
             patch.object(status.subprocess,'Popen') as open_browser:
            self.assertEqual(status.open_reviews(self.collect()),set())
        open_browser.assert_not_called()

    def test_mismatched_state_identity_and_changed_config_do_not_become_success(self):
        for record in (dict(self.record,account='fb15',status='published'),
                       dict(self.record,url='https://www.facebook.com/profile.php?id=999',status='published')):
            upload.save_json(self.state_path,{self.key:record})
            self.assertEqual(self.collect()['rows'][0]['status'],'needs_check')

    def test_conflicting_success_evidence_on_failure_needs_manual_review(self):
        upload.save_json(self.state_path,{self.key:dict(self.record,status='failed_before_post',success_message='published')})
        self.assertEqual(self.collect()['rows'][0]['status'],'needs_review')

    def test_latest_resume_error_is_used_for_restored_before_post_failure(self):
        upload.save_json(self.state_path,{self.key:dict(self.record,status='failed_before_post')})
        self.report['resume_results']=[dict(key=self.key,error='new busy error')]
        upload.save_json(self.path,self.report)
        self.assertEqual(self.collect()['rows'][0]['reason'],'new busy error')

    def test_open_review_uses_existing_exact_profile_without_publishing_or_marking(self):
        before=self.state_path.read_bytes()
        config=upload.CONFIG.read_bytes()
        with patch.object(status.sys,'platform','win32'),patch.object(status,'find_chrome',return_value='chrome.exe'), \
             patch.object(status.subprocess,'Popen') as open_browser:
            self.assertEqual(status.open_reviews(self.collect()),{('fb14','personal')})
        args=open_browser.call_args.args[0]
        self.assertIn('--user-data-dir='+str(self.root/'profiles/fb14'),args)
        self.assertEqual(args[-1],self.entry['url'])
        self.assertEqual(self.state_path.read_bytes(),before)
        self.assertEqual(upload.CONFIG.read_bytes(),config)

    def test_missing_profile_does_not_create_blank_or_open_browser(self):
        (self.root/'profiles/fb14').rmdir()
        with patch.object(status.sys,'platform','win32'),patch.object(status,'find_chrome',return_value='chrome.exe'), \
             patch.object(status.subprocess,'Popen') as open_browser:
            self.assertEqual(status.open_reviews(self.collect()),set())
        open_browser.assert_not_called()
        self.assertFalse((self.root/'profiles/fb14').exists())

    def test_other_dates_plans_and_corrupt_reports_do_not_override_valid_round(self):
        for number,report in enumerate((dict(self.report,created='2026-10-25T17:53:46+08:00'),
                                       dict(self.report,phase='plan_only'),[])):
            upload.save_json(self.root/f'logs/available-today-{number}.json',report)
        result=self.collect()
        self.assertEqual(len(result['sources']),1)
        self.assertEqual(result['counts'],dict(needs_review=1))
        self.assertEqual(len(result['issues']),1)

    def test_save_emits_full_keys_and_checklist_without_mutating_ledger(self):
        before=self.state_path.read_bytes()
        path=status.save(self.collect())
        self.assertIn(self.key,path.with_suffix('.csv').read_text(encoding='utf-8-sig'))
        self.assertIn('勿重发',path.with_suffix('.txt').read_text(encoding='utf-8-sig'))
        self.assertEqual(self.state_path.read_bytes(),before)

    def test_oct26_two_round_snapshot_totals_separate_twenty_exact_videos(self):
        personal={3,4,7,8,9,10,11,14,15,17,19,20,22,23}
        published={1,12}
        review={3,4,7,8,11,14,15,19,20}
        unfinished={17,22,23}
        config=[]
        state={}
        rounds=[[],[]]
        results=[]
        for n in (*range(1,14),14,15,17,19,20,22,23):
            entry=dict(self.entry,account=f'fb{n:02d}',target='personal' if n in personal else 'page01',
                type='personal' if n in personal else 'page',name=f'Name {n}',
                url=f'https://www.facebook.com/profile.php?id={1000+n}')
            config.append(entry)
            key=f'{n:064x}'
            row=dict(account=entry['account'],target=entry['target'],filename=f'{n}.mp4',key=key,status='ready')
            rounds[n>=14].append(row)
            if n in unfinished:
                results.append(dict(row,status='needs_check',error='prepare failed'))
            else:
                state[key]=dict(account=entry['account'],target=entry['target'],url=entry['url'],video=row['filename'],
                    status='published' if n in published else 'needs_review' if n in review else 'failed_before_post')
        rounds[0].append(dict(account='fb10',target='page01',filename='',key=None,status='inbox_empty'))
        upload.save_json(upload.CONFIG,dict(targets=config))
        upload.save_json(self.state_path,state)
        upload.save_json(self.path,dict(self.report,rows=rounds[0]))
        upload.save_json(self.root/'logs/available-today-two.json',dict(self.report,
            schema='available-current-publication-v1',created='2026-10-26T18:22:38+08:00',rows=rounds[1],results=results))
        report=self.collect()
        self.assertEqual(len(report['rows']),20)
        self.assertEqual(report['counts'],dict(published=2,needs_review=9,failed_before_post=6,needs_check=3))
        self.assertEqual(len(report['no_material_rows']),1)


if __name__=='__main__':
    unittest.main()
