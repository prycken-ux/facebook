import contextlib
import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import add_fb_accounts
import audit_other_publication as audit
import fb_upload as upload


class FailureAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(upload,'ROOT',self.root))
        self.stack.enter_context(patch.object(add_fb_accounts,'ROOT',self.root))
        self.stack.enter_context(patch.object(upload,'CONFIG',self.root/'upload_config.json'))
        self.confirmed=[(f'fb{n:02d}','personal') for n in (14,17,19,20,22)]
        self.failed=[('fb01','page01'),('fb06','page01'),('fb09','personal'),('fb13','page01'),('fb23','personal')]
        self.rows=[];self.entries=[];self.state={};self.paths={}
        for index,pair in enumerate(self.confirmed+self.failed,1):
            entry=dict(account=pair[0],target=pair[1],name='Example '+pair[0],type='personal' if pair[1]=='personal' else 'page',
                url='https://www.facebook.com/profile.php?id='+str(1000+index),enabled=False)
            if entry['type']=='personal':entry['workflow']='personal_recording_v1'
            self.entries.append(entry)
            video=upload.inbox_for(entry)/'original.mp4';video.parent.mkdir(parents=True)
            video.write_bytes(pair[0].encode());video.with_suffix('.txt').write_text('caption')
            key=upload.job_key(entry,video);self.paths[pair]=(video,key)
            status='needs_review' if pair in self.confirmed else 'failed_before_post'
            self.state[key]=dict(account=pair[0],target=pair[1],url=entry['url'],video=str(video),status=status,
                error='old detailed error',created='2026-10-28T18:05:07+08:00')
            self.rows.append(dict(account=pair[0],target=pair[1],name=entry['name'],url=entry['url'],filename=video.name,
                key=key,status=status,reason='old reason'))
        self.source='other-accounts-publish-20261028-180507-117297.json'
        self.source_path=self.root/'logs'/self.source
        upload.save_json(self.source_path,dict(schema='other-accounts-direct-publication-v1',created='2026-10-28T18:05:07+08:00',
            phase='attempts_finished',ai_label='off',caption_text='common caption',rows=self.rows,
            final_rows=copy.deepcopy(self.rows),results=[dict(error='original attempts retained')],manual_checks=copy.deepcopy(self.rows)))
        upload.save_json(upload.CONFIG,dict(targets=self.entries))
        upload.save_json(self.root/'logs/publish_state.json',self.state)
        self.config_before=upload.CONFIG.read_bytes()
        for account,target in self.failed:
            video,key=self.paths[(account,target)]
            (self.root/'logs'/(self.source_path.stem+'-'+account+'-'+target+'-error.txt')).write_text('Full call log for '+account)
            (self.root/'logs'/('review-'+key[:12]+'.png')).write_bytes(b'PNG local evidence')
        self.desktop=self.root/'desktop';self.desktop.mkdir()

    def tearDown(self):
        self.stack.close();self.temp.cleanup()

    def test_confirms_exact_five_and_exports_only_five_failure_logs_without_any_browser_or_post(self):
        with patch.object(upload,'run_entry') as publish,patch.object(upload,'launch_context') as browser:
            output=audit.run(self.source,self.confirmed,True,self.desktop)
        publish.assert_not_called();browser.assert_not_called()
        self.assertEqual(upload.CONFIG.read_bytes(),self.config_before)
        state=upload.read_json(self.root/'logs/publish_state.json',{})
        for pair,(video,key) in self.paths.items():
            if pair in self.confirmed:
                self.assertEqual(state[key]['status'],'published')
                self.assertEqual(state[key]['confirmation_method'],'user_confirmed_existing_post_no_link')
                self.assertFalse(video.exists())
                self.assertTrue((video.parent.parent/'completed/original.mp4').exists())
            else:
                self.assertEqual(state[key],self.state[key])
                self.assertTrue(video.exists())
        report=upload.read_json(self.source_path,{})
        self.assertEqual(report['rows'],self.rows)
        self.assertEqual(len(report['manual_checks']),5)
        self.assertEqual(report['results'],[dict(error='original attempts retained')])
        with zipfile.ZipFile(output) as archive:
            names=archive.namelist();data=json.loads(archive.read('failure-evidence.json'))
            self.assertEqual(len(data['failures']),5)
            self.assertEqual({(row['account'],row['target']) for row in data['failures']},set(self.failed))
            self.assertTrue(all(not name.endswith('.mp4') for name in names))
            self.assertNotIn('publish_state.json',names)
            self.assertNotIn('upload_config.json',names)
            self.assertNotIn('fb14-personal-failure.png',names)
            self.assertIn('fb23-personal-full-error.txt',names)

    def test_repeat_confirmation_is_idempotent_and_never_posts(self):
        audit.run(self.source,self.confirmed,True,self.desktop)
        state=(self.root/'logs/publish_state.json').read_bytes()
        audit.run(self.source,self.confirmed,True,self.desktop)
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),state)

    def test_unverified_confirmation_and_wrong_source_are_refused_without_state_change(self):
        before=(self.root/'logs/publish_state.json').read_bytes()
        with self.assertRaises(ValueError):audit.run(self.source,self.confirmed,False,self.desktop)
        with self.assertRaises(ValueError):audit.run('../'+self.source,(),False,self.desktop)
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),before)

    def test_missing_error_artifact_is_reported_without_grabbing_other_files(self):
        (self.root/'logs'/(self.source_path.stem+'-fb09-personal-error.txt')).unlink()
        (self.root/'logs/unrelated-secrets.json').write_text('must not export')
        output=audit.run(self.source,(),False,self.desktop)
        with zipfile.ZipFile(output) as archive:
            data=json.loads(archive.read('failure-evidence.json'))
            self.assertIn('fb09-personal-full-error.txt',data['missing_artifacts'])
            self.assertNotIn('unrelated-secrets.json',archive.namelist())


if __name__=='__main__':unittest.main()
