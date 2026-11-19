import contextlib
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import archive_delete_project_videos_20261119 as app


class CleanupAllVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'uploader';self.root.mkdir()
        self.outside=Path(self.temp.name)/'originals';self.outside.mkdir()
        self.clock=self.enterContext(patch.object(app,'datetime',wraps=datetime))
        self.clock.now.return_value=datetime(2026,11,19,6,tzinfo=timezone.utc)
        self.enterContext(patch.object(app.upload,'ROOT',self.root))
        self.enterContext(patch.object(app,'locked',side_effect=contextlib.nullcontext))
        self.workers=self.enterContext(patch.object(app.workers,'active_workers',return_value=[]))
        self.enterContext(patch.object(app.recovery,'recover_locks'))
        self.enterContext(contextlib.redirect_stdout(__import__('io').StringIO()))
        self.media=[]
        self.state={}
        self.write('upload_config.json','{"targets":[]}')
        self.write('fb_upload.py','# original program')
        self.write('account_registry.json','{"accounts":[]}')
        self.write('publication_account_exclusions.json','original pause policy')
        self.write('profiles/fb32/Default/Login Data','credentials')
        self.write('profiles/fb32/asset.mp4','profile media asset')
        self.write('.venv/lib/asset.mp4','library asset')
        self.write('browsers/resources/asset.mp4','browser asset')
        self.write('material-staging/tools/installer/fixture.mp4','tool asset')
        self.write('backups/browser-copy/Default/Preferences','browser prefs')
        self.write('backups/browser-copy/Default/asset.mp4','browser profile asset')
        self.write('backups/install/program.zip','program package')
        for n,(folder,status) in enumerate([('videos/fb01/page01/completed','published'),
                                          ('videos/fb32/personal/inbox','failed_before_post'),
                                          ('videos/fb09/page01/inbox','needs_review'),
                                          ('videos/fb17/personal/inbox','failed_before_post')],1):
            path=self.write(folder+'/video.mp4','video'+str(n));self.media.append(path)
            self.write(folder+'/video.txt','caption');self.write(folder+'/video.comment.txt','comment')
            key=str(n)*64
            self.state[key]=dict(account='fb'+str(n).zfill(2),target='personal',status=status,
                                 comment_status='sent' if status=='published' else 'not_started',
                                 video=str(path),confirmation_method='receipt' if status=='published' else None)
        for name in ['material-staging/2026-11-18/source/videos/clip.mp4','backups/old-media/clip.mp4',
                     'logs/diagnostic/recording.webm','standalone.mp4']:
            self.media.append(self.write(name,'managed video'))
        (self.outside/'fresh.mp4').write_bytes(b'external source video')
        self.write('material_distribution_settings.json',json.dumps(dict(source=str(self.outside))))
        self.write('logs/publish_state.json',json.dumps(self.state))
        job=dict(key='5'*64,account='fb70',target='personal',filename='missing.mp4')
        payload=dict(date='2026-11-18',material_source_date='2026-11-18',jobs=[job])
        value=dict(payload=payload,sha256=app.media.digest(payload))
        self.write('logs/frozen-material-2026-11-18-'+value['sha256'][:16]+'.json',json.dumps(value))
        self.protected={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p not in self.media and p!=self.root/'logs/publish_state.json'}

    def write(self,name,content):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content);return path

    def assert_protected(self):
        for p,data in self.protected.items():self.assertEqual(p.read_bytes(),data,str(p))
        self.assertEqual((self.outside/'fresh.mp4').read_bytes(),b'external source video')

    def test_deletes_all_managed_outcomes_archives_without_faking_success_and_preserves_programs(self):
        result=app.execute(self.root,apply=True)
        self.assertTrue(result['complete']);self.assertEqual(len(result['deleted']),len(self.media))
        self.assertTrue(all(not p.exists() for p in self.media));self.assert_protected()
        state=app.read(self.root/'logs/publish_state.json')
        for key,before in self.state.items():
            self.assertEqual(state[key]['status'],'archived')
            self.assertEqual(state[key]['publication_status_before_user_archive'],before['status'])
            self.assertEqual(state[key]['comment_status'],before['comment_status'])
            self.assertEqual(state[key]['confirmation_method'],before['confirmation_method'])
        ledger=app.read(self.root/app.ARCHIVES)
        self.assertEqual(ledger['rows']['5'*64]['publication_status_before_archive'],'not_started')
        backup=self.root/'backups'/('user-video-cleanup-'+result['plan']['sha256'][:16])/'publish-state-before.json'
        self.assertEqual(app.read(backup),self.state)
        events=[json.loads(l) for l in (self.root/app.AUDIT).read_text().splitlines()]
        self.assertEqual(sum(e['event']=='delete_intent' for e in events),len(self.media))
        self.assertTrue(all('sha256' in e for e in events if e['event']=='delete_intent'))

    def test_replay_never_deletes_new_files_or_resurrects_old_media(self):
        app.execute(self.root,apply=True)
        new=self.write('videos/fb32/personal/inbox/new-today.mp4','new after cleanup')
        same_path=self.media[0];same_path.write_bytes(b'replacement after completed cleanup')
        self.clock.now.return_value=datetime(2026,11,20,6,tzinfo=timezone.utc)
        result=app.execute(self.root,apply=True)
        self.assertEqual(result['deleted'],[]);self.assertTrue(new.exists());self.assertTrue(same_path.exists())
        self.assert_protected()

    def test_preview_then_changed_file_preserved_and_only_frozen_files_deleted(self):
        result=app.execute(self.root,apply=False)
        self.assertEqual(app.read(self.root/'logs/publish_state.json'),self.state)
        changed=self.media[0];changed.write_bytes(b'new material replacing same path')
        new=self.write('videos/fb32/personal/inbox/new-today.mp4','fresh')
        result=app.execute(self.root,apply=True)
        self.assertTrue(changed.exists());self.assertTrue(new.exists());self.assertFalse(result['complete'])
        self.assertEqual(len(result['deleted']),len(self.media)-1);self.assert_protected()

    def test_active_worker_or_corrupt_state_prevents_all_deletion(self):
        self.workers.return_value=[dict(pid=123)]
        with self.assertRaisesRegex(ValueError,'仍有发布'):app.execute(self.root,apply=True)
        self.workers.return_value=[]
        for value in ('{bad json','[]','{"x":{},"x":{}}'):
            (self.root/'logs/publish_state.json').write_text(value)
            with self.assertRaises((ValueError,json.JSONDecodeError)):app.execute(self.root,apply=True)
            self.assertTrue(all(p.exists() for p in self.media))

    def test_linked_files_and_external_junction_subtree_preserved(self):
        link=self.root/'videos/external';link.symlink_to(self.outside,target_is_directory=True)
        path=self.root/'videos/hardlink.mp4';os.link(self.outside/'fresh.mp4',path)
        app.execute(self.root,apply=True)
        self.assertTrue(link.is_symlink());self.assertTrue(path.exists());self.assert_protected()

    def test_durable_audit_failure_stops_before_deleting(self):
        append=app.media.append_event
        def fail(stream,value):
            if value['event']=='delete_intent':raise OSError('disk full')
            return append(stream,value)
        with patch.object(app.media,'append_event',side_effect=fail):
            with self.assertRaises(app.AuditFailure):app.execute(self.root,apply=True)
        self.assertTrue(all(p.exists() for p in self.media));self.assert_protected()

    def test_corrupt_or_changed_plan_never_rescans_and_deletes_new_scope(self):
        app.execute(self.root,apply=False)
        value=app.read(self.root/app.PLAN);value['payload']['files'].append(dict(path='outside.mp4'))
        app.atomic(self.root/app.PLAN,value)
        with self.assertRaisesRegex(ValueError,'指纹'):app.execute(self.root,apply=True)
        self.assertTrue(all(p.exists() for p in self.media))

    def test_old_distribution_pointers_retired_with_exact_backup_new_pointer_not_touched_on_replay(self):
        pointer=self.write('material-staging/eligible62-pending-import.json','{"manifest":"2026-11-18/source/manifest.json","complete":true}')
        original=pointer.read_bytes()
        result=app.execute(self.root,apply=True)
        self.assertFalse(pointer.exists())
        backup=self.root/'backups'/('user-video-cleanup-'+result['plan']['sha256'][:16])/'retired-pointers'/pointer.name
        self.assertEqual(backup.read_bytes(),original)
        pointer.write_text('{"manifest":"2026-11-19/new-source/manifest.json"}')
        newer=pointer.read_bytes();app.execute(self.root,apply=True)
        self.assertEqual(pointer.read_bytes(),newer);self.assertEqual(backup.read_bytes(),original)


class CleanupChainTests(unittest.TestCase):
    def test_exact_cleanup_chain_exempts_self_only(self):
        from test_nov16_venv_process_chain import VenvProcessChainTests
        f=VenvProcessChainTests();f.setUp();rows=copy.deepcopy(f.rows)
        runner=r'E:\FB-AutoUpload\material-staging\tools\cleanup\archive_delete_project_videos_20261119.py'
        body=f.body.replace('start_finish_first24_nov16','start_archive_delete_project_videos_20261119').replace('verified-nov16-first24-and-nov14-stage','verified-user-archive-delete-project-videos')
        for row in rows[:2]:row['command']=subprocess.list2cmdline([f.exe,'-u',runner,f.root])
        for row in rows[2:]:row['command']=subprocess.list2cmdline([f.exe,'-u','-c',body,f.root])
        rows.append(f.row(96,1,['-u',f.root+r'\publish_eligible62_materials_20261118.py',f.root]))
        with patch.object(app.workers,'BOOTSTRAP',app.BOOTSTRAP):workers,allowed=app.workers.classify_workers(rows,f.root,100,runner)
        self.assertEqual(allowed,[97,98,99,100]);self.assertEqual([r['pid'] for r in workers],[96])


if __name__=='__main__':unittest.main()
