import contextlib,copy,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
import publish_staged_first24_nov14 as app
from test_publish_distributed_nov13_first24 import DistributedFirst24Tests


class NewStagedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fx=DistributedFirst24Tests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.root=self.fx.root
        self.fx.now=datetime(2026,11,14,6,tzinfo=timezone.utc)
        for clock in self.fx.clocks:clock.now.return_value=self.fx.now
        for module in (app,app.stage):
            clock=self.enterContext(patch.object(module,'datetime',wraps=datetime));clock.now.return_value=self.fx.now
        pool=self.root/'Nov14-original44';pool.mkdir()
        for n in range(1,45):(pool/f'today-{n}.mp4').write_bytes(('Original November14 clip '+str(n)).encode())
        path,value=app.stage.prepare(self.root,pool,scope='existing24');self.stage_path=path
        self.fx.material=value['payload']['distribution']
        self.enterContext(patch.object(app,'SOURCE_ID',value['payload']['source_id']))
        self.enterContext(patch.object(app,'STAGE',path.relative_to(self.root)))
        self.before_state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        self.before_material={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
    def core(self,unknown=False,fail_once=False):
        with patch.object(app.stage,'active_workers',return_value=[]) as workers,patch.object(app.lock_recovery,'recover_locks') as recovery, \
             patch.object(app.first,'execute',side_effect=app.execute):
            result,events,comments=self.fx.core(unknown=unknown,fail_once=fail_once)
        return result,events,comments
    def test_import_and_exact43_publish_with_comments_preserving_paused17_old_jobs_and_new50(self):
        result,events,comments=self.core();self.assertEqual(result,0)
        posts=[pair for event,pair in events if event=='post'];self.assertEqual(len(posts),43)
        self.assertNotIn(('fb17','personal'),posts);self.assertTrue(all(int(a[2:])<=24 for a,t in posts));self.assertEqual(len(comments[0]),43)
        self.assertEqual(sum(a=='fb09' and t.startswith('page') for a,t in posts),10)
        state=app.first.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in self.before_state.items():self.assertEqual(state[key],row)
        for path,data in self.before_material.items():self.assertEqual(path.read_bytes(),data)
        row=next(r for r in self.fx.material['payload']['assignments'] if r['account']=='fb17')
        paused=self.root/'videos/fb17/personal/inbox'/row['files'][-1]['destination_name'];self.assertTrue(paused.is_file())
        _,events,_=self.core();self.assertFalse(any(e[0]=='post' for e in events))
    def test_new_submitted_unknowns_not_reuploaded_and_old_material_still_present(self):
        result,events,_=self.core(unknown=True);self.assertEqual(result,3);self.assertEqual(sum(e[0]=='post' for e in events),43)
        _,events,_=self.core(unknown=True);self.assertFalse(any(e[0]=='post' for e in events))
        for path,data in self.before_material.items():self.assertEqual(path.read_bytes(),data)
    def test_safe_prepost_network_retry_is_scoped_to_new_original(self):
        result,events,_=self.core(fail_once=True);self.assertEqual(result,0)
        posts=[e[1] for e in events if e[0]=='post'];self.assertEqual(len(posts),43);self.assertEqual(posts[-1],('fb02','page01'))
    def test_live_previous_task_is_waited_for_without_any_import_or_lock_mutation(self):
        with patch.object(app.stage,'active_workers',side_effect=[[dict(pid=1234,name='python.exe')],[]]) as probe,patch.object(app.time,'sleep') as sleep:
            app.wait_previous()
        self.assertEqual(probe.call_count,2);sleep.assert_called_once_with(15)
        self.assertEqual(app.first.upload.read_json(self.root/'logs/publish_state.json',{}),self.before_state)
        with self.assertRaisesRegex(ValueError,'全部实拍'):app.execute(False)


class PageHomeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(__import__('io').StringIO()))
        self.entry=dict(account='fb09',target='page01',type='page',name='Exact Page',url='https://www.facebook.com/profile.php?id=61595986545178')
        self.page=MagicMock();self.page.url='https://www.facebook.com/'
        self.enterContext(patch.object(app.first.upload,'checkpoint'));self.enterContext(patch.object(app.first.upload,'require_no_advanced_protection'))
    def test_home_redirect_uses_exact_picker_then_requires_actor_and_original_numeric_profile(self):
        def navigate(page,url):page.url=url
        with patch.object(app.first.numeric.picker,'login_marker',return_value='same-owner'), \
             patch.object(app.first.upload,'page_actor_matches',side_effect=[False,True,True]), \
             patch.object(app.first.numeric.picker,'picker_dialog',return_value=None), \
             patch.object(app.first.numeric.picker,'select_configured_profile') as picker, \
             patch.object(app.first.upload,'navigate_profile',side_effect=navigate),patch.object(app,'NUMERIC',return_value={'verified':True}) as strict:
            self.assertEqual(app.page_identity(self.page,self.entry),{'verified':True})
        picker.assert_called_once();strict.assert_called_once();self.assertEqual(self.page.url,self.entry['url'])
    def test_login_settings_reel_and_other_host_never_enable_home_recovery(self):
        for url in ['https://www.facebook.com/login','https://www.facebook.com/settings','https://www.facebook.com/reel/123','https://outside.example/']:
            self.page.url=url
            with patch.object(app.first.numeric.picker,'select_configured_profile') as picker,patch.object(app,'NUMERIC') as strict:
                with self.assertRaises(ValueError):app.page_identity(self.page,self.entry)
            picker.assert_not_called();strict.assert_not_called()
    def test_login_owner_change_after_picker_stops_before_final_identity_or_upload(self):
        with patch.object(app.first.numeric.picker,'login_marker',side_effect=['old-owner','new-owner']), \
             patch.object(app.first.upload,'page_actor_matches',return_value=False),patch.object(app.first.numeric.picker,'select_configured_profile'),patch.object(app,'NUMERIC') as strict:
            with self.assertRaisesRegex(RuntimeError,'登录者变化'):app.page_identity(self.page,self.entry)
        strict.assert_not_called()


if __name__=='__main__':unittest.main()
