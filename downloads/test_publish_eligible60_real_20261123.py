import copy,unittest
from datetime import datetime,timezone
from unittest.mock import patch
import publish_eligible60_real_20261123 as current
import distribute_eligible60_materials_20261123 as distribution
import test_publish_eligible60_materials_20261119 as fixture

class Nov23PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.Eligible60PublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root;self.app=current.app;self.runfx=self.fx.runfx
        self.app.content_today.save_authorized(self.root)
        self.now=datetime(2026,11,23,5,tzinfo=timezone.utc);self.runfx.now=self.now
        for clock in self.runfx.clocks:clock.now.return_value=self.now
        for module in (current,distribution.stage):
            clock=self.enterContext(patch.object(module,'datetime',wraps=datetime));clock.now.return_value=self.now;self.runfx.clocks.append(clock)
        self.old_pointer=current.first.upload.read_json(self.root/'material-staging/eligible60-pending-import.json',{})
        pool=self.root/'Nov23-fresh60';pool.mkdir()
        for n in range(1,61):(pool/f'{n}.mp4').write_bytes(('Nov23 fresh real material '+str(n)).encode())
        with patch.object(distribution,'inspect_workers',return_value=[]),patch.object(distribution.recovery,'recover_locks'):distribution.execute(self.root,pool)
        self.runfx.material=current.allocation(self.root)[3]
        (self.root/'normal_chrome_batch.py').write_text("STARTUP_WAIT_VERSION='1.0-wait-for-endpoint-after-launcher-exit'\n")
        self.sentinel=self.root/'videos/fb10/page09/scheduled/2026-11-20/inbox/old20.mp4';self.sentinel.parent.mkdir(parents=True);self.sentinel.write_bytes(b'old20 protected')
        self.state_before=copy.deepcopy(current.first.upload.read_json(self.root/'logs/publish_state.json',{}))
    def core(self,unknown=False,network=False,login=False,comment_retry=False):
        native=self.app.first.upload.run_entry;calls=[];failed=[]
        def run(entry,*args,**kwargs):
            self.assertIs(kwargs['ai_label_override'],False);self.assertNotIn(entry['account'],self.app.BLOCKED)
            self.assertTrue(kwargs['filename'].startswith('20261123-'));calls.append((entry['account'],entry['target']))
            if login and entry['account']=='fb52':
                with patch.object(self.app.first.upload,'prepare_reel',side_effect=RuntimeError('Login required for original account')):return native(entry,*args,**kwargs)
            if network and entry['account']=='fb02' and not failed:
                failed.append(True)
                with patch.object(self.app.first.upload,'prepare_reel',side_effect=RuntimeError('net::ERR_CONNECTION_RESET')):return native(entry,*args,**kwargs)
            return native(entry,*args,**kwargs)
        with patch.object(current,'inspect_workers',return_value=[]),patch.object(self.app.workers,'active_workers',return_value=[]), \
             patch.object(self.app.browser.staged.lock_recovery,'recover_locks'),patch.object(self.app.extra,'wait_session'), \
             patch.object(self.app.extra,'ensure_background_identity',side_effect=lambda prev,p,e:prev(p,e)), \
             patch.object(self.app.owners,'discover_background',side_effect=self.fx.fx.discover),patch.object(self.app.first.upload,'run_entry',side_effect=run), \
             patch.object(self.app,'manual_existing',side_effect=AssertionError('No manual window')),patch.object(self.app,'manual_new',side_effect=AssertionError('No manual window')), \
             patch.object(self.app.first,'execute',side_effect=lambda real:current.execute(self.root)):
            result,events,comments=self.runfx.core(unknown=unknown,include_new=True,comment_retry=comment_retry)
        return result,events,comments,calls
    def test_original60_real_off_exact_content_comments_and_no_repeat(self):
        result,events,_,_=self.core();self.assertEqual(result,0)
        self.assertEqual({p for e,p in events if e=='post'},self.app.EXPECTED);self.assertEqual(sum(e=='post' for e,p in events),60)
        request=current.first.upload.read_json(self.root/current.REQUEST,{})
        self.assertEqual(request['payload']['material_date'],'2026-11-23');self.assertEqual(request['payload']['authorization'],current.AUTH)
        self.assertEqual(request['payload']['content_sha256'],current.CONTENT_SHA);self.assertIs(request['payload']['ai_label'],False)
        state=current.first.upload.read_json(self.root/'logs/publish_state.json',{})
        new=[r for r in state.values() if '20261123-' in str(r.get('video',''))]
        self.assertEqual(len(new),60);self.assertTrue(all(r['status']=='published' and r['comment_status']=='sent' for r in new))
        self.assertEqual(self.sentinel.read_bytes(),b'old20 protected')
        for key,row in self.state_before.items():self.assertEqual(state[key],row)
        _,events,_,_=self.core();self.assertFalse(any(e=='post' for e,p in events))
    def test_pending_submissions_lookup_and_no_reupload(self):
        result,events,_,_=self.core(unknown=True);self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),60)
        _,events,_,_=self.core(unknown=True);self.assertFalse(any(e=='post' for e,p in events))
    def test_network_failure_retries_before_post_once(self):
        result,events,_,calls=self.core(network=True);self.assertEqual(result,0)
        self.assertEqual(sum(e=='post' for e,p in events),60);self.assertEqual(calls.count(('fb02','page01')),2)
    def test_login_failure_skips_to_other_accounts_without_manual_popup(self):
        result,events,_,_=self.core(login=True);self.assertEqual(result,3)
        self.assertEqual(sum(e=='post' for e,p in events),59);self.assertFalse(any(e=='post' and p[0]=='fb52' for e,p in events))
    def test_generic_old_pointer_is_not_selected_or_replaced(self):
        path=self.root/'material-staging/eligible60-pending-import.json';current.first.upload.save_json(path,self.old_pointer);before=path.read_bytes()
        self.assertEqual(current.allocation(self.root)[1]['payload']['date'],'2026-11-23')
        result,events,_,_=self.core();self.assertEqual(result,0);self.assertEqual(sum(e=='post' for e,p in events),60);self.assertEqual(path.read_bytes(),before)
    def test_incomplete_or_other_day_allocation_is_rejected(self):
        path=self.root/current.POINTER;saved=current.first.upload.read_json(path,{})
        current.first.upload.save_json(path,dict(saved,complete=False))
        with self.assertRaisesRegex(ValueError,'尚未正式导入'):current.allocation(self.root)
        current.first.upload.save_json(path,self.old_pointer)
        with self.assertRaisesRegex(ValueError,'不是11月23'):current.allocation(self.root)
    def test_live_pause_added_after_allocation_remains_skipped(self):
        p=dict(schema='publication-account-exclusions-v1',excluded_accounts=sorted(self.app.BLOCKED|{'fb04'}))
        current.first.upload.save_json(self.root/self.app.AVAILABILITY,dict(payload=p,sha256=current.first.batch.digest(p)))
        result,events,_,_=self.core();self.assertEqual(result,0)
        self.assertEqual(sum(e=='post' for e,p in events),59);self.assertFalse(any(e=='post' and p[0]=='fb04' for e,p in events))
    def test_comment_transient_failure_is_retried_without_reposting_video(self):
        result,events,_,_=self.core(comment_retry=True);self.assertEqual(result,0)
        self.assertEqual(sum(e=='post' for e,p in events),60)

if __name__=='__main__':unittest.main()
