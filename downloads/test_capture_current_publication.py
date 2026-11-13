import copy,json,unittest
from datetime import datetime,timezone
from unittest.mock import MagicMock
import capture_current_publication as app
from test_scheduled_material_batch import ScheduledMaterialTests


class PassiveCaptureTests(unittest.TestCase):
    def setUp(self):
        self.fx=ScheduledMaterialTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.root=self.fx.root;self.entry=self.fx.entries[0];self.video=self.fx.videos[(self.entry['account'],self.entry['target'])]
        self.now=datetime.now(timezone.utc);self.created=self.now.isoformat();self.key=app.upload.job_key(self.entry,self.video)
        self.caption='Exact current caption'
        self.job=dict(account=self.entry['account'],target=self.entry['target'],url=self.entry['url'],filename=self.video.name,key=self.key,caption_text=self.caption)
        self.path=self.root/'logs/frozen-material-2026-11-13-1234567890abcdef.json'
        self.value=dict(payload=dict(jobs=[self.job]),created_at=self.created,sha256='scope-sha')
        self.state={self.key:dict(account=self.entry['account'],target=self.entry['target'],url=self.entry['url'],video=str(self.video),
                                  created=self.created,post_intent_at=self.created,status='posting')}
        self.response=MagicMock(url='https://www.facebook.com/api/graphql')
    def video_node(self,ident='9001',**extra):
        owner=app.upload.target_key(self.entry['url'])[3:]
        return dict(__typename='Video',id=ident,owner={'id':owner},message={'text':self.caption},creation_time=self.now.timestamp(),is_published=True,**extra)
    def send(self,collector,node):
        self.response.text.return_value=json.dumps({'data':node});collector.receive(self.response)

    def test_explicit_published_hint_survives_core_timeout_save_without_marking_success(self):
        with app.installed(self.path,self.value):
            app.upload.save_json(self.fx.state_path,self.state)
            collector=app.comments.PublicationLinks(MagicMock(),self.entry,self.caption,self.created);collector.armed=True
            self.send(collector,self.video_node())
            stale=copy.deepcopy(self.state);stale[self.key].update(status='needs_review',error='receipt timeout')
            app.upload.save_json(self.fx.state_path,stale)
        row=app.upload.read_json(self.fx.state_path,{})[self.key]
        self.assertEqual(row['status'],'needs_review')
        self.assertEqual(row['fresh_publication_candidate'],'https://www.facebook.com/reel/9001')
        self.assertTrue(row['fresh_publication_explicit_published'])
        self.assertEqual(row['source_frozen_manifest'],self.path.name)
        self.assertNotIn('permalink',row)

    def test_no_armed_candidate_wrong_owner_and_wrong_caption_never_supply_success_evidence(self):
        with app.installed(self.path,self.value):
            app.upload.save_json(self.fx.state_path,self.state)
            collector=app.comments.PublicationLinks(MagicMock(),self.entry,self.caption,self.created)
            self.send(collector,self.video_node());collector.armed=True
            node=self.video_node();node['owner']={'id':'999999'};self.send(collector,node)
            node=self.video_node();node['message']={'text':'Different caption'};self.send(collector,node)
        self.assertNotIn('fresh_publication_candidate',app.upload.read_json(self.fx.state_path,{})[self.key])

    def test_multiple_links_remove_the_previously_unique_hint_and_never_guess(self):
        with app.installed(self.path,self.value):
            app.upload.save_json(self.fx.state_path,self.state)
            collector=app.comments.PublicationLinks(MagicMock(),self.entry,self.caption,self.created);collector.armed=True
            self.send(collector,self.video_node());self.send(collector,self.video_node('9002'))
        row=app.upload.read_json(self.fx.state_path,{})[self.key]
        self.assertEqual(row['fresh_publication_candidate_count'],2)
        self.assertNotIn('fresh_publication_candidate',row)

    def test_conflicting_pending_flag_never_qualifies_as_published_metadata(self):
        with app.installed(self.path,self.value):
            app.upload.save_json(self.fx.state_path,self.state)
            collector=app.comments.PublicationLinks(MagicMock(),self.entry,self.caption,self.created);collector.armed=True
            self.send(collector,self.video_node(is_pending=True))
        row=app.upload.read_json(self.fx.state_path,{})[self.key]
        self.assertFalse(row.get('fresh_publication_explicit_published'))
        self.assertEqual(row['status'],'posting')


if __name__=='__main__':unittest.main()
