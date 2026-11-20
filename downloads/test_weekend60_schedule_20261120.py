import contextlib,copy,hashlib,io,json,os,subprocess,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
from xml.etree import ElementTree as ET
import weekend60_schedule_20261120 as schedule
import test_publish_eligible60_materials_20261119 as fixture

class Weekend60Tests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.Eligible60PublicationTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root;self.pub=schedule.app
        self.now=datetime(2026,11,20,8,40,tzinfo=timezone.utc)
        self.clock=self.enterContext(patch.object(schedule,'datetime',wraps=datetime));self.clock.now.return_value=self.now
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.sources={}
        for index,day in enumerate(schedule.DAYS):
            folder=self.root/('Desktop-'+day);folder.mkdir()
            for n in range(1,64):(folder/(str(n)+'.mp4')).write_bytes(('New unique '+day+' footage '+str(n)).encode())
            self.sources[day]=folder
        schedule.content.save_authorized(self.root)
        self.before_state=(self.root/'logs/publish_state.json').read_bytes();self.oldpointer=(self.root/'material-staging/eligible60-pending-import.json').read_bytes()
        self.protected={p:p.read_bytes() for p in (self.root/'videos').rglob('*') if p.is_file()}
        (self.root/'.venv/Scripts').mkdir(parents=True,exist_ok=True);(self.root/'.venv/Scripts/pythonw.exe').write_bytes(b'fixture pythonw')
    def prepare(self):return schedule.prepare(self.root,self.sources)
    def test_three_natural_allocations_only_dated_folders_preserve_original_and_old_inboxes(self):
        path,value=self.prepare();self.assertEqual(len(value['payload']['batches']),3)
        for day,batch in value['payload']['batches'].items():
            self.assertEqual({(r['account'],r['target']) for r in batch['assignments']},self.pub.EXPECTED)
            self.assertEqual([r['video_filename'] for r in batch['assignments']],[str(n)+'.mp4' for n in range(1,61)])
            self.assertEqual(batch['leftover_count'],3)
            for row in batch['assignments']:
                dest=schedule.day_inbox(self.root,row['account'],row['target'],day)
                for part in row['files']:self.assertEqual(hashlib.sha256((dest/part['destination_name']).read_bytes()).hexdigest(),part['sha256'])
                self.assertTrue((self.sources[day]/row['video_filename']).is_file())
        self.assertEqual((self.root/'logs/publish_state.json').read_bytes(),self.before_state)
        self.assertEqual((self.root/'material-staging/eligible60-pending-import.json').read_bytes(),self.oldpointer)
        for p,b in self.protected.items():self.assertEqual(p.read_bytes(),b)
    def test_insufficient_third_day_creates_no_media_or_schedule(self):
        for p in list(self.sources[schedule.DAYS[2]].glob('*.mp4'))[:5]:p.unlink()
        with self.assertRaisesRegex(ValueError,'素材不足'):self.prepare()
        self.assertFalse((self.root/schedule.MANIFEST).exists());self.assertFalse(list((self.root/'videos').glob('fb*/*/scheduled/*/inbox/*.mp4')))
    def test_cross_day_duplicate_excluded_and_replaced_by_next_natural_clip(self):
        shutil=__import__('shutil');shutil.copyfile(self.sources[schedule.DAYS[0]]/'1.mp4',self.sources[schedule.DAYS[1]]/'1.mp4')
        _,value=self.prepare();self.assertEqual([r['video_filename'] for r in value['payload']['batches'][schedule.DAYS[1]]['assignments']],[str(n)+'.mp4' for n in range(2,62)])
    def test_copy_interruption_resumes_same_three_sources_and_exact_plan(self):
        native=schedule.materials.copy_exact;calls=[]
        def stop(*args):
            native(*args)
            if not calls:calls.append(True);raise KeyboardInterrupt
        with patch.object(schedule.materials,'copy_exact',side_effect=stop):
            with self.assertRaises(KeyboardInterrupt):self.prepare()
        raw=(self.root/schedule.MANIFEST).read_bytes()
        with patch.object(schedule,'choose_sources',side_effect=AssertionError('Do not repick')):self.prepare()
        self.assertEqual((self.root/schedule.MANIFEST).read_bytes(),raw)
    def test_low_disk_stops_before_copy(self):
        with patch.object(schedule.shutil,'disk_usage',return_value=MagicMock(free=1)):
            with self.assertRaisesRegex(ValueError,'磁盘可用空间不足'):self.prepare()
        self.assertFalse((self.root/schedule.MANIFEST).exists())
    def test_real_confirmation_required(self):
        with self.assertRaisesRegex(ValueError,'未确认'):schedule.setup(self.root,self.sources)
    def test_xml_one_shot_explicit_beijing_offset_pythonw_and_fixed_date_runner(self):
        _,value=self.prepare()
        for day in schedule.DAYS:
            task=ET.fromstring(schedule.task_xml(self.root,day,value));ns={'t':schedule.NS}
            self.assertEqual(len(task.findall('t:Triggers/t:TimeTrigger',ns)),1)
            self.assertEqual(task.find('t:Triggers/t:TimeTrigger/t:StartBoundary',ns).text,day+'T17:10:00+08:00')
            self.assertFalse(task.findall('.//t:Repetition',ns))
            self.assertEqual(task.find('t:Actions/t:Exec/t:Command',ns).text,str(self.root/'.venv/Scripts/pythonw.exe'))
            self.assertIn('weekend60_run_'+day.replace('-','')+'.py',task.find('t:Actions/t:Exec/t:Arguments',ns).text)
            self.assertEqual(task.find('t:Principals/t:Principal/t:LogonType',ns).text,'InteractiveToken')
    def test_early_or_wrong_day_does_not_enter_publisher(self):
        self.prepare()
        with patch.object(self.pub,'execute',side_effect=AssertionError('Never early')):
            with self.assertRaisesRegex(ValueError,'尚未到'):schedule.run_day(self.root,schedule.DAYS[0])
            with self.assertRaisesRegex(ValueError,'不在本批'):schedule.run_day(self.root,schedule.DAYS[1])
    def test_register_readback_has_all_three_and_does_not_execute_publish_code(self):
        _,value=self.prepare();tasks=[]
        def register(args,**kwargs):
            self.assertIn('-NonInteractive',args);data=json.loads(kwargs['input']);tasks.extend(data['tasks'])
            return MagicMock(returncode=0,stdout=('\n'.join(json.dumps(dict(TaskName=t['name'],State='Ready',StartBeijing=t['start'])) for t in data['tasks'])).encode(),stderr=b'')
        with patch.object(schedule.sys,'platform','win32'),patch.object(schedule.subprocess,'run',side_effect=register),patch.object(self.pub,'execute',side_effect=AssertionError('Setup never publishes')):
            receipts=schedule.register(self.root,value)
        self.assertEqual(len(receipts),3);self.assertEqual([t['start'] for t in tasks],[d+'T17:10:00+08:00' for d in schedule.DAYS])
    def integration_run(self,day,unknown=False):
        self.fx.runfx.now=datetime.fromisoformat(day+'T17:10:00+08:00').astimezone(timezone.utc)
        if self.clock not in self.fx.runfx.clocks:self.fx.runfx.clocks.append(self.clock)
        for clock in self.fx.runfx.clocks:clock.now.return_value=self.fx.runfx.now
        value=schedule.checked_json(self.root,self.root/schedule.MANIFEST)
        self.fx.runfx.material=schedule.allocation(self.root,day,value)[3]
        with patch.object(schedule,'inspect_workers',return_value=[]),patch.object(self.pub.workers,'active_workers',return_value=[]),patch.object(self.pub.browser.staged.lock_recovery,'recover_locks'), \
             patch.object(self.pub.extra,'wait_session'),patch.object(self.pub.extra,'ensure_background_identity',side_effect=lambda prev,p,e:prev(p,e)), \
             patch.object(self.pub.owners,'discover_background',side_effect=self.fx.fx.discover), \
             patch.object(self.pub.first,'execute',side_effect=lambda real:schedule.run_day(self.root,day,value['sha256'])):
            return self.fx.runfx.core(unknown=unknown,include_new=True)
    def test_full_three_days_use_only_their_60_and_no_repost_on_replay(self):
        _,value=self.prepare()
        for day in schedule.DAYS:
            result,events,comments=self.integration_run(day)
            self.assertEqual(result,0)
            self.assertEqual({p for e,p in events if e=='post'},self.pub.EXPECTED)
            self.assertEqual(sum(e=='post' for e,p in events),60)
            state=schedule.upload.read_json(self.root/'logs/publish_state.json',{})
            for row in value['payload']['batches'][day]['assignments']:
                name=row['files'][-1]['destination_name']
                records=[r for r in state.values() if str(r.get('video','')).replace('\\','/').rsplit('/',1)[-1]==name]
                self.assertEqual(len(records),1);self.assertEqual(records[0]['status'],'published');self.assertEqual(records[0]['comment_status'],'sent');self.assertIn('/scheduled/'+day+'/inbox/',str(records[0]['video']).replace('\\','/'))
            _,events,_=self.integration_run(day);self.assertFalse(any(e=='post' for e,p in events))
        for path,data in self.protected.items():self.assertEqual(path.read_bytes(),data)
    def test_pending_submissions_are_not_reuploaded_and_no_manual_prompt_blocks(self):
        self.prepare()
        result,events,_=self.integration_run(schedule.DAYS[0],unknown=True)
        self.assertEqual(result,3);self.assertEqual(sum(e=='post' for e,p in events),60)
        _,events,_=self.integration_run(schedule.DAYS[0],unknown=True);self.assertFalse(any(e=='post' for e,p in events))
    def test_different_schedule_sha_does_not_publish(self):
        self.prepare();self.clock.now.return_value=datetime(2026,11,20,9,10,tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError,'原三天计划已变化'):schedule.run_day(self.root,schedule.DAYS[0],'0'*64)

    def test_live_new_pause_prevents_further_copy_without_reassigning(self):
        p=dict(schema='publication-account-exclusions-v1',excluded_accounts=sorted(self.pub.BLOCKED|{'fb04'}));schedule.upload.save_json(self.root/self.pub.AVAILABILITY,dict(payload=p,sha256=schedule.digest(p)))
        with self.assertRaisesRegex(ValueError,'暂停名单已扩大'):self.prepare()
    def test_per_day_allocation_does_not_import_or_replace_nov19_pointer(self):
        _,value=self.prepare();_,source,journal,distribution=schedule.allocation(self.root,schedule.DAYS[1],value)
        self.assertEqual(source['payload']['date'],schedule.DAYS[1]);self.assertEqual(distribution['payload']['date'],schedule.DAYS[1])
        self.assertEqual((self.root/'material-staging/eligible60-pending-import.json').read_bytes(),self.oldpointer)
        for p,b in self.protected.items():self.assertEqual(p.read_bytes(),b)

if __name__=='__main__':unittest.main()
