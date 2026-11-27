import contextlib,copy,io,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import connect_fb08_fb14_pages_20261127 as app
import scheduled_material_batch as batch
import publication_content_20261119 as content

class RegistrationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'FB-AutoUpload';self.root.mkdir();self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close);self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
  for module in [app.upload,app.accounts]:self.stack.enter_context(patch.object(module,'ROOT',self.root))
  self.stack.enter_context(patch.object(app.upload,'CONFIG',self.root/'upload_config.json'))
  self.owners=[dict(account=a,target='personal',type='personal',name='Owner '+a,url='https://www.facebook.com/owner'+a,enabled=True,prepared_at='keep-real-proof',workflow='personal_recording_v1',ai_label=False,excluded_files=['old.mp4']) for a in ['fb08','fb14']]
  self.other=dict(account='fb10',target='page01',type='page',name='Existing Page',url='https://www.facebook.com/profile.php?id=100010',enabled=True,prepared_at='keep-other-proof')
  self.config=dict(custom={'keep':True},targets=self.owners+[self.other]);app.upload.save_json(app.upload.CONFIG,self.config)
  base=dict(schema='publication-preferences-v1',effective_from='2026-11-06',caption_policy='exact-unified-new-videos',caption='base-caption',excluded_accounts=[])
  app.upload.save_json(self.root/'publication_preferences.json',dict(payload=base,sha256=app.digest(base),content_updates=[content.CONTENT]));(self.root/'common_caption_today.txt').write_text(content.CAPTION,encoding='utf-8')
  self.comments=dict(schema='per-video-post-comment-v1',enabled=True,future_only=True,automatic_send_enabled=False,custom='keep-comment-switches',targets=[dict(account='fb10',target='page01',url=self.other['url'])]);app.upload.save_json(self.root/'post_comment_config.json',self.comments)
  pauses=dict(schema='publication-account-exclusions-v1',excluded_accounts=['fb32','fb52']);app.upload.save_json(self.root/'publication_account_exclusions.json',dict(payload=pauses,sha256=app.digest(pauses)))
  for relative,blob in [('profiles/fb08/session',b'keep-08-session'),('profiles/fb14/session',b'keep-14-session'),('videos/fb08/personal/completed/old.mp4',b'keep-old-video'),('videos/fb14/personal/completed/old.mp4',b'keep-old-video-14'),('account_registry.json',b'{"keep":"registry"}'),('logs/publish_state.json',b'{"old":{"status":"needs_review"}}'),('logs/video_comments.json',b'{"old":{"status":"sent"}}'),('material-staging/eligible58-20261126-pending-import.json',b'{"keep":"frozen58"}'),('material-staging/2026-11-26/manifest.json',b'{"keep":"immutable58"}')]:
   p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(blob)
  self.untouched={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p not in [app.upload.CONFIG,self.root/'post_comment_config.json']}
 def apply(self,inspector=lambda root:[]):return app.connect(self.root,inspector=inspector)
 def preserved(self):
  for path,blob in self.untouched.items():self.assertEqual(path.read_bytes(),blob,str(path))
 def test_exact_ten_page_bindings_folders_backup_and_original_owners_preserved(self):
  before=app.upload.CONFIG.read_bytes();result=self.apply();self.assertEqual(result['targets'][:3],self.config['targets']);self.assertEqual(len(result['targets']),13);self.assertEqual(result['custom'],{'keep':True})
  ids=['61596581349898','61596636007799','61596732513142','61596813179840','61596875847318','61596692195025','61596417496995','61596777031514','61596810479819','61596934854640'];self.assertEqual([r[3] for r in app.PAGES],ids)
  for account,target,name,number in app.PAGES:
   row=next(r for r in result['targets'] if (r['account'],r['target'])==(account,target));self.assertEqual((row['name'],row['url']),(name,'https://www.facebook.com/profile.php?id='+number));self.assertFalse(row['enabled']);self.assertFalse(row['ai_label']);self.assertEqual(row['workflow'],'page_flow_configured');self.assertNotIn('prepared_at',row)
   for folder in ['inbox','completed','failed']:self.assertTrue((self.root/'videos'/account/target/folder).is_dir())
  backup=next((self.root/'backups').glob('*/upload_config.json'));self.assertEqual(backup.read_bytes(),before);report=app.read(self.root/app.REPORT);self.assertEqual(report['sha256'],app.digest(report['payload']));self.assertEqual(report['payload']['page_count'],10);self.preserved()
 def test_comment_targets_merge_preserves_switches_and_does_not_enable_sending(self):
  self.apply();settings=app.read(self.root/'post_comment_config.json');self.assertEqual(settings['targets'][0],self.comments['targets'][0]);self.assertEqual(len(settings['targets']),11)
  for key in ['enabled','automatic_send_enabled','future_only','custom']:self.assertEqual(settings[key],self.comments[key])
  self.assertEqual({(r['account'],r['target']) for r in settings['targets'][1:]},{(a,t) for a,t,_,_ in app.PAGES});self.preserved()
 def test_idempotent_repeat_keeps_enabled_pages_materials_and_exact_config_bytes(self):
  config=self.apply();config['targets'][-1].update(enabled=True,prepared_at='verified-page');app.upload.save_json(app.upload.CONFIG,config);video=self.root/'videos/fb14/page05/inbox/new.mp4';video.write_bytes(b'keep-new');before={p:p.read_bytes() for p in [app.upload.CONFIG,self.root/'post_comment_config.json',self.root/app.REPORT]};backups=list((self.root/'backups').iterdir());self.apply()
  for p,blob in before.items():self.assertEqual(p.read_bytes(),blob)
  self.assertEqual(list((self.root/'backups').iterdir()),backups);self.assertEqual(video.read_bytes(),b'keep-new');self.preserved()
 def test_last_slot_collision_prevents_all_new_registration(self):
  config=copy.deepcopy(self.config);config['targets'].append(dict(self.other,account='fb14',target='page05'));app.upload.save_json(app.upload.CONFIG,config);before=app.upload.CONFIG.read_bytes()
  with self.assertRaisesRegex(ValueError,'未覆盖'):self.apply()
  self.assertEqual(app.upload.CONFIG.read_bytes(),before);self.assertFalse((self.root/'videos/fb08/page01').exists());self.preserved()
 def test_cross_account_id_collision_is_rejected_before_new_folders(self):
  config=copy.deepcopy(self.config);config['targets'][-1]['url']='https://www.facebook.com/profile.php?id='+app.PAGES[-1][-1];app.upload.save_json(app.upload.CONFIG,config);before=app.upload.CONFIG.read_bytes()
  with self.assertRaisesRegex(ValueError,'重复添加'):self.apply()
  self.assertEqual(app.upload.CONFIG.read_bytes(),before);self.assertFalse((self.root/'videos/fb08/page01').exists());self.preserved()
 def test_conflicting_legacy_comment_binding_blocks_the_entire_merge(self):
  comments=copy.deepcopy(self.comments);comments['targets'].append(dict(account='fb14',target='page05',url=self.other['url']));app.upload.save_json(self.root/'post_comment_config.json',comments);before=app.upload.CONFIG.read_bytes()
  with self.assertRaisesRegex(ValueError,'评论目标已绑定其他主页'):self.apply()
  self.assertEqual(app.upload.CONFIG.read_bytes(),before);self.assertEqual(app.read(self.root/'post_comment_config.json'),comments);self.assertFalse((self.root/'videos/fb08/page01').exists())
 def test_active_fb_process_and_existing_lock_are_preserved(self):
  before=app.upload.CONFIG.read_bytes()
  with self.assertRaisesRegex(RuntimeError,'仍有FB'):self.apply(lambda root:[dict(pid=777,name='python.exe')])
  self.assertFalse((self.root/'videos/fb08/page01').exists());lock=self.root/'logs/upload.lock';lock.write_bytes(b'active-worker')
  with self.assertRaises(RuntimeError):self.apply()
  self.assertEqual(lock.read_bytes(),b'active-worker');self.assertEqual(app.upload.CONFIG.read_bytes(),before);self.assertFalse((self.root/'logs/batch.lock').exists())
 def test_report_write_failure_rolls_back_both_config_and_comment_bytes(self):
  before={p:p.read_bytes() for p in [app.upload.CONFIG,self.root/'post_comment_config.json']};original=app.atomic_json
  def fail(path,value):
   if Path(path)==self.root/app.REPORT:Path(path).write_bytes(b'partial');raise OSError('fixture write failure')
   original(path,value)
  with patch.object(app,'atomic_json',side_effect=fail):
   with self.assertRaises(OSError):self.apply()
  for p,blob in before.items():self.assertEqual(p.read_bytes(),blob)
  self.assertFalse((self.root/app.REPORT).exists());self.assertFalse((self.root/'logs/upload.lock').exists());self.preserved()
 def test_concurrent_config_edit_is_not_replaced_by_stale_snapshot(self):
  calls=[];external=dict(self.config,external='keep-concurrent-change')
  def inspector(root):
   calls.append(True)
   if len(calls)==3:app.upload.save_json(app.upload.CONFIG,external)
   return []
  with self.assertRaisesRegex(RuntimeError,'配置正在变化'):self.apply(inspector)
  self.assertEqual(app.read(app.upload.CONFIG),external);self.preserved()
 def test_bad_content_or_new_pause_refuses_before_config_change(self):
  before=app.upload.CONFIG.read_bytes();(self.root/'common_caption_today.txt').write_text('wrong caption')
  with self.assertRaisesRegex(ValueError,'统一正文文件'):self.apply()
  self.assertEqual(app.upload.CONFIG.read_bytes(),before);self.assertFalse((self.root/'videos/fb08/page01').exists());(self.root/'common_caption_today.txt').write_text(content.CAPTION)
  p=dict(schema='publication-account-exclusions-v1',excluded_accounts=['fb14']);app.upload.save_json(self.root/'publication_account_exclusions.json',dict(payload=p,sha256=app.digest(p)))
  with self.assertRaisesRegex(ValueError,'停用名单'):self.apply()
  self.assertEqual(app.upload.CONFIG.read_bytes(),before)
 def test_linked_page_folder_is_not_followed(self):
  outside=Path(self.tmp.name)/'outside';outside.mkdir();marker=outside/'keep';marker.write_bytes(b'outside');(self.root/'videos/fb14/page05').symlink_to(outside,target_is_directory=True);before=app.upload.CONFIG.read_bytes()
  with self.assertRaises(ValueError):self.apply()
  self.assertEqual(marker.read_bytes(),b'outside');self.assertEqual(app.upload.CONFIG.read_bytes(),before);self.assertFalse((self.root/'videos/fb08/page01').exists())
 def test_modern_batch_freezes_exact_caption_comment_and_all_ten_new_targets_without_publishing(self):
  self.apply()
  for a,t,_,_ in app.PAGES:
   video=self.root/'videos'/a/t/'inbox/new.mp4';video.write_bytes(('distinct '+a+t).encode())
  _,frozen=batch.freeze('2026-11-27','17:00',True,'ignored-old-comment',datetime(2026,11,27,8,tzinfo=timezone.utc),report_format='text');p=frozen['payload'];self.assertEqual(len(p['jobs']),10);self.assertEqual(p['comment_text'],content.COMMENT);self.assertEqual(p['publication_content_sha256'],content.CONTENT['sha256']);self.assertEqual({(j['account'],j['target']) for j in p['jobs']},{(a,t) for a,t,_,_ in app.PAGES})
  for j in p['jobs']:self.assertEqual(j['caption_text'],content.CAPTION);self.assertEqual(batch.validate_job(j,date='2026-11-27')['target'],j['target'])
  self.preserved()
 def test_no_legacy_comment_config_does_not_create_or_enable_obsolete_sender(self):
  (self.root/'post_comment_config.json').unlink();self.apply();self.assertFalse((self.root/'post_comment_config.json').exists());self.assertFalse(app.read(self.root/app.REPORT)['payload']['existing_per_video_comment_targets_merged']);self.preserved()

class ProcessClassificationTests(unittest.TestCase):
 def test_exact_contiguous_windows_venv_parent_is_allowed_but_sibling_installer_blocks(self):
  root=r'E:\FB-AutoUpload';exe=root+r'\.venv\Scripts\python.exe';code="https://raw.githubusercontent.com/prycken-ux/facebook/pinned/downloads/connect_fb08_fb14_pages_20261127.py";command='"'+exe+'" -u -c "'+code+'" "'+root+'"'
  parent=dict(pid=10,parent=1,created='2026-11-27T08:00:00Z',name='python.exe',exe=exe,command=command);child=dict(parent,pid=11,parent=10,created='2026-11-27T08:00:01Z',exe=r'E:\Python313\python.exe');sibling=dict(parent,pid=12)
  self.assertEqual(app.blockers([parent,child],root,11),[]);self.assertEqual([r['pid'] for r in app.blockers([parent,child,sibling],root,11)],[12])
 def test_recycled_parent_pid_is_not_exempted_from_fb_process_guard(self):
  root=r'E:\FB-AutoUpload';exe=root+r'\.venv\Scripts\python.exe';command='"'+exe+'" -c "connect_fb08_fb14_pages_20261127.py" "'+root+'"';parent=dict(pid=10,parent=1,created='2026-11-27T08:00:02Z',exe=exe,command=command);child=dict(parent,pid=11,parent=10,created='2026-11-27T08:00:01Z')
  self.assertEqual([r['pid'] for r in app.blockers([parent,child],root,11)],[10])
 def test_ig_with_shared_interpreter_is_preserved_but_fb_worker_and_unknown_venv_task_block(self):
  root=r'E:\FB-AutoUpload';exe=root+r'\.venv\Scripts\python.exe';ig=r'E:\IG-AutoUpload'
  def row(pid,args):return dict(pid=pid,name='python.exe',exe=exe,command='"'+exe+'" '+args)
  rows=[row(10,'-u -c "self" "'+root+'"'),row(20,'-u "'+ig+'\\tools\\ig10\\ig10_engine_20261127.py" "'+ig+'"'),row(30,'-u "'+root+'\\tools\\publisher.py" "'+root+'"'),row(40,'-c "print(123)"'),row(50,'-u -c "start_ig10_publish_20261127.py" "'+ig+'"')]
  self.assertEqual({r['pid'] for r in app.blockers(rows,root,10)},{30,40});self.assertEqual(app.win_args('"a b.exe" -u "E:\\目录\\file.py" "E:\\IG-AutoUpload"'),['a b.exe','-u','E:\\目录\\file.py','E:\\IG-AutoUpload'])
 def test_uninspectable_or_malformed_process_is_not_assumed_safe(self):
  with self.assertRaises(ValueError):app.blockers([dict(pid=3,exe='',command='')],r'E:\FB-AutoUpload',1)
  with self.assertRaises(ValueError):app.win_args('python "unterminated')

if __name__=='__main__':unittest.main()
