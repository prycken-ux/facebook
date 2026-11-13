import contextlib,hashlib,io,json,tempfile,unittest
from pathlib import Path
import summarize_nov12_readonly as app


class ReadonlySummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.logs=self.root/'logs';self.logs.mkdir()
        self.jobs=[];state={}
        for n,status in enumerate(('published','failed_before_post','needs_review','preparing','posting','not_started'),1):
            key=str(n)*64;url='https://www.facebook.com/profile.php?id='+str(1000+n)
            job=dict(account=f'fb{n:02d}',target='personal',filename=f'new{n}.mp4',key=key,url=url)
            self.jobs.append(job)
            if status!='not_started':state[key]=dict(account=job['account'],target='personal',url=url,status=status,comment_status='needs_review' if status=='published' else 'not_started')
        self.save(self.logs/'publish_state.json',state)
        self.manifest=self.freeze(dict(date=app.DAY,current_material_scope=app.SCOPE,jobs=self.jobs))
        payload=dict(scope=app.SCOPE,date=app.DAY,records=[dict(account=j['account'],target='personal',filename=j['filename']) for j in self.jobs]+[dict(account='fb18',target='personal',filename='new18.mp4')])
        self.save(self.logs/'nov12-current-materials-original-accounts.json',dict(payload=payload,sha256=self.digest(payload),plans=[],setup_issues=[dict(account='fb18',reason='identity not ready')]))
    def save(self,path,value):path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    def digest(self,value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    def freeze(self,payload):
        sha=self.digest(payload);path=self.logs/('frozen-material-'+app.DAY+'-'+sha[:16]+'.json');self.save(path,dict(payload=payload,sha256=sha));return path
    def test_closed_window_states_remain_pending_and_reading_changes_no_files(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        rows,plans,snapshot=app.collect(self.root)
        self.assertEqual(plans,1);self.assertTrue(snapshot)
        self.assertEqual([r['video_status'] for r in rows],['发布成功','发布前失败','待核实','待核实','待核实','未开始','未进入发布清单'])
        self.assertEqual(rows[-1]['reason'],'identity not ready')
        for p,data in before.items():self.assertEqual(p.read_bytes(),data)
        self.assertEqual(set(before),{p for p in self.root.rglob('*') if p.is_file()})
    def test_same_day_old_retry_batches_are_excluded_and_duplicate_owned_plans_deduplicate(self):
        self.freeze(dict(date=app.DAY,jobs=[dict(account='fb09',target='page02',key='a'*64,filename='old.mp4')]))
        self.freeze(dict(date=app.DAY,current_material_scope=app.SCOPE,jobs=self.jobs,extra='second wave'))
        rows,plans,_=app.collect(self.root)
        self.assertEqual(len(rows),7);self.assertEqual(plans,2)
        self.assertTrue(all(r['filename']!='old.mp4' for r in rows))
    def test_no_saved_batch_is_reported_as_missing_without_creating_a_new_batch(self):
        for p in self.logs.iterdir():p.unlink()
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):app.summarize(self.root)
        self.assertIn('未找到该批次',stream.getvalue());self.assertEqual(list(self.logs.iterdir()),[])
    def test_hash_tampering_or_contradictory_post_intent_is_not_treated_as_safe_failure(self):
        state=json.loads((self.logs/'publish_state.json').read_text())
        state['2'*64]['post_intent_at']='before interruption'
        self.save(self.logs/'publish_state.json',state)
        self.assertEqual(app.collect(self.root)[0][1]['video_status'],'待核实')
        value=json.loads(self.manifest.read_text());value['payload']['jobs'][0]['filename']='changed.mp4';self.save(self.manifest,value)
        with self.assertRaises(ValueError):app.collect(self.root)


if __name__=='__main__':unittest.main()
