import contextlib
import copy
import os
import time
import unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock,patch

import retry_three_personal_20261112 as app
from test_repair_nov11_identity_20261112 import IdentityRepairTests


class ThreePersonalRetryTests(unittest.TestCase):
    def setUp(self):
        self.base=IdentityRepairTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.root=self.base.root;self.stack=self.base.fx.stack
        (path,value),_=self.base.prepare()
        self.records={a:next(j for j in value['payload']['jobs'] if j['account']==a) for a in app.RECORDS}
        value=copy.deepcopy(value)
        value['payload']['jobs']=[j for j in value['payload']['jobs'] if j['account'] in {'fb09','fb16'}]
        value['issues']=[copy.deepcopy(j) for j in self.records.values()]
        value['sha256']=app.old.batch.digest(value['payload'])
        self.path=path.with_name('frozen-material-'+app.DAY+'-'+value['sha256'][:16]+'.json');self.value=value
        app.upload.save_json(self.path,value)
        app.upload.save_json(self.root/'logs/nov11-identity-repair-on-20261112.json',dict(manifest=self.path.name,sha256=value['sha256']))
        self.stack.enter_context(patch.object(app,'SOURCE_PREFIX',value['sha256'][:8]))
        self.stack.enter_context(patch.object(app,'RECORDS',{a:(j['filename'],j['video_sha256']) for a,j in self.records.items()}))
        self.stack.enter_context(patch.object(app.old,'require_day'))
        self.stack.enter_context(patch.object(app.old,'recover_locks'))
        self.stack.enter_context(patch.object(app.old.priority.daily,'keep_awake',side_effect=contextlib.nullcontext))
        self.clock=self.stack.enter_context(patch.object(app,'datetime',wraps=datetime));self.clock.now.return_value=datetime(2026,11,12,4,tzinfo=timezone.utc)
        for file in self.root.rglob('*'):
            if file.is_file() and file.suffix in {'.mp4','.txt'}:os.utime(file,(time.time()-180,time.time()-180))
        self.protected=app.upload.read_json(self.root/'logs/publish_state.json',{})
        self.source_before=self.path.read_bytes()

    def discover(self,account):
        entry,proof=self.base.fx.discovered(account)
        proof.update(route_method='numeric_owner_match',verified_aliases=[])
        return entry,proof

    def core(self,fail_account=None,unknown=False):
        browser=MagicMock();browser.pages=[MagicMock()];button=MagicMock();events=[]
        button.click.side_effect=lambda **k:events.append('post')
        def discover(account):
            if account==fail_account:raise ValueError('owner not ready')
            return self.discover(account)
        def comments(value,*a,**kwargs):
            events.append('comments')
            state=app.upload.read_json(self.root/'logs/publish_state.json',{})
            for job in value['payload']['jobs']:
                if state[job['key']]['status']=='published':state[job['key']]['comment_status']='sent'
            app.upload.save_json(self.root/'logs/publish_state.json',state)
        with patch.object(app,'discover',side_effect=discover) as owner,patch.object(app.old.normal,'launcher_for_jobs',return_value=lambda *a:browser), \
             patch('playwright.sync_api.sync_playwright'),patch.object(app.old.batch,'close_selected_window'),patch.object(app.upload,'prepare_reel',return_value=(button,{})), \
             patch.object(app.upload,'recheck_publish_identity'),patch.object(app.upload,'install_receipt_watch'), \
             patch.object(app.upload,'wait_for_receipt',side_effect=app.upload.ReceiptNeedsReview('unknown') if unknown else None,return_value='Your reel is published.'), \
             patch('safe_video_comments.resolve_published_link',return_value=('https://www.facebook.com/reel/9001','fresh_success_view_reel_link')), \
             patch.object(app.old.priority.daily,'backfill',side_effect=comments),patch.object(app.old.priority.comment_retry,'run',return_value=[]):
            result=app.execute()
        return result,button,events,owner

    def test_only_three_original_videos_publish_before_comments_without_touching_fb16_or_pages(self):
        result,button,events,owner=self.core()
        self.assertEqual(result,0);self.assertEqual(button.click.call_count,3)
        self.assertEqual(events,['post']*3+['comments']*3)
        self.assertEqual({c.args[0] for c in owner.call_args_list},set(app.RECORDS))
        state=app.upload.read_json(self.root/'logs/publish_state.json',{})
        for key,row in self.protected.items():self.assertEqual(state[key],row)
        self.assertEqual(self.path.read_bytes(),self.source_before)
        again,button,events,owner=self.core()
        self.assertEqual(again,0);button.click.assert_not_called();owner.assert_not_called()

    def test_one_unverified_account_can_be_connected_on_rerun_without_reposting_the_other_two(self):
        result,button,events,_=self.core(fail_account='fb18')
        self.assertEqual(result,3);self.assertEqual(button.click.call_count,2)
        result,button,events,owner=self.core()
        self.assertEqual(result,0);self.assertEqual(button.click.call_count,1)
        self.assertEqual([c.args[0] for c in owner.call_args_list],['fb18'])

    def test_posted_unknown_remains_blocked_after_rerun(self):
        result,button,events,_=self.core(unknown=True)
        self.assertEqual(result,3);self.assertEqual(button.click.call_count,3)
        result,button,events,owner=self.core()
        self.assertEqual(result,3);button.click.assert_not_called();owner.assert_not_called()

    def test_alias_conversion_requires_me_proof_and_cannot_replace_a_different_numeric_owner(self):
        config=app.upload.read_json(app.upload.CONFIG,{})
        registry=app.upload.read_json(self.root/'account_registry.json',{})
        manifest=app.upload.read_json(self.root/'additional_personal_accounts.json',{})
        entry,proof=self.discover('fb18');alias='https://www.facebook.com/current.fb18'
        for row in config['targets']+registry['accounts']:
            if row.get('account')=='fb18':row['url']=alias
        old=app.old.safe_failed_fb17(self.base.fx.parent,self.protected)
        with self.assertRaises(ValueError):app.register_alias(config,registry,manifest,'fb18',entry,proof,old)
        proof['verified_aliases']=['slug:current.fb18']
        result=app.register_alias(config,registry,manifest,'fb18',entry,proof,old)
        self.assertEqual(next(r for r in result[0]['targets'] if r['account']=='fb18')['url'],entry['url'])
        for row in config['targets']+registry['accounts']:
            if row.get('account')=='fb18':row['url']='https://www.facebook.com/profile.php?id=9999'
        with self.assertRaises(ValueError):app.register_alias(config,registry,manifest,'fb18',entry,proof,old)

    def test_changed_original_file_is_not_replaced_with_another_inbox_video(self):
        record=self.records['fb21'];video=self.root/'videos/fb21/personal/inbox'/record['filename'];video.write_bytes(b'changed original')
        result,button,events,owner=self.core()
        self.assertEqual(result,3);self.assertEqual(button.click.call_count,2)
        self.assertNotIn('fb21',[c.args[0] for c in owner.call_args_list])


if __name__=='__main__':unittest.main()
