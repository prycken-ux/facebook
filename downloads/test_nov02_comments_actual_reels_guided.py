import contextlib,copy,io,json,unittest
from unittest.mock import MagicMock,patch
from playwright.sync_api import sync_playwright
import nov02_comments_actual_reels_guided as guided


class DirectEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.link='https://www.facebook.com/reel/9001';self.node=dict(__typename='Video',id='9001',owner={'id':'1001'},description={'text':'Exact caption'},creation_time=1000)
    def proof(self,node):
        p=guided.Evidence('1001','Exact caption',900,1100,self.link);p.add(node);return p
    def test_complete_video_metadata_matches_without_requiring_a_published_flag(self):
        p=self.proof(self.node);self.assertTrue(p.matched);self.assertFalse(p.blocked);self.assertFalse(p.published)
        self.assertNotIn('Exact caption',json.dumps(p.diagnostic()))
    def test_owned_creation_story_is_tied_to_this_video_but_generic_parent_caption_is_not(self):
        node=dict(__typename='Video',id='9001',creation_story=dict(actors=[{'id':'1001'}],message={'text':'Exact caption'},creation_time=1000))
        self.assertTrue(self.proof(node).matched)
        nested=dict(message={'text':'Exact caption'},media={k:v for k,v in self.node.items() if k!='description'})
        self.assertFalse(self.proof(nested).matched)
    def test_wrong_owner_caption_time_id_and_pending_or_conflicting_metadata_never_qualify(self):
        for change in [dict(owner={'id':'other'}),dict(description='other'),dict(creation_time=10),dict(id='9002')]:
            p=self.proof(dict(self.node,**change));self.assertFalse(p.matched and not p.blocked)
        for change in [dict(is_published=False),dict(is_pending=True),dict(is_draft=True),dict(permalink_url='https://www.facebook.com/reel/999')]:
            p=self.proof(dict(self.node,**change));self.assertTrue(p.blocked)
        p=self.proof(self.node);p.add(dict(self.node,is_pending=True));self.assertTrue(p.blocked)
    def test_absolute_epoch_or_zoned_time_only(self):
        self.assertEqual(guided.stamp('1970-01-01T00:16:40+00:00'),1000)
        self.assertEqual(guided.stamp('1970-01-01T00:16:40'),0);self.assertEqual(guided.stamp('2h'),0)


class GuidedSelectionTests(unittest.TestCase):
    def test_unique_verified_candidate_is_chosen_after_all_candidates_not_first_or_newest(self):
        jobs=[dict(account='fb01',target='page01',filename='old-source.mp4')];entry=dict(account='fb01',target='page01');page=MagicMock();context=MagicMock();context.pages=[page]
        links=['https://www.facebook.com/reel/9001','https://www.facebook.com/reel/9002']
        with patch.object(guided,'collect_links',return_value=links),patch.object(guided,'inspect_video',side_effect=[(False,{}),(True,{})]) as inspect,patch.object(guided,'require_target_author'),patch.object(guided,'manual_choice',side_effect=AssertionError('must use proven unique candidate')),contextlib.redirect_stdout(io.StringIO()):
            result=guided.make_finder(jobs,True)(page,context,entry,'caption',900,1100)
        self.assertEqual(inspect.call_count,2);self.assertEqual(result,(links[1],'verified_owner_caption_time'))
    def test_multiple_matching_candidates_require_manual_target_not_a_guess(self):
        jobs=[dict(account='fb01',target='page01',filename='old-source.mp4')];entry=dict(account='fb01',target='page01');page=MagicMock();context=MagicMock();context.pages=[page]
        manual=('https://www.facebook.com/reel/9002','user_supplied_exact_job_link')
        with patch.object(guided,'collect_links',return_value=['https://www.facebook.com/reel/9001','https://www.facebook.com/reel/9002']),patch.object(guided,'inspect_video',return_value=(True,{})),patch.object(guided,'manual_choice',return_value=manual) as choose,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guided.make_finder(jobs,True)(page,context,entry,'caption',900,1100),manual)
        choose.assert_called_once()
    def test_enter_uses_only_this_selection_page_not_restored_old_video_tabs(self):
        page=MagicMock();page.url='https://www.facebook.com/reel/9001';page.is_closed.return_value=False
        restored=MagicMock();restored.url='https://www.facebook.com/reel/9999';restored.is_closed.return_value=False
        context=MagicMock();context.pages=[page,restored];entry=dict(account='fb01',target='page01');job=dict(filename='source.mp4')
        with patch('builtins.input',return_value=''),patch.object(guided,'validate_selected',return_value=page.url) as validate,contextlib.redirect_stdout(io.StringIO()):
            result=guided.manual_choice(page,context,entry,job,{page,restored})
        self.assertEqual(result,(page.url,'user_supplied_exact_job_link'));self.assertEqual(validate.call_args.args[2],page.url)
    def test_ambiguous_tabs_can_be_skipped_and_q_aborts_without_selecting(self):
        page=MagicMock();page.url='https://www.facebook.com/reel/9001';page.is_closed.return_value=False
        other=MagicMock();other.url='https://www.facebook.com/reel/9002';other.is_closed.return_value=False
        context=MagicMock();context.pages=[page,other];entry=dict(account='fb01',target='page01');job=dict(filename='source.mp4')
        with patch('builtins.input',side_effect=['','S']),patch.object(guided,'validate_selected') as validate,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):guided.manual_choice(page,context,entry,job,{page})
        validate.assert_not_called()
        with patch('builtins.input',return_value='Q'),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):guided.manual_choice(page,context,entry,job,{page})


class DirectVideoBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context();self.page=self.context.new_page();self.entry=dict(name='Example Page',url='https://www.facebook.com/profile.php?id=1001',account='fb01',target='page01',type='page')
        self.node=dict(__typename='Video',id='9001',owner={'id':'1001'},description='Exact caption',creation_time=1000);self.video=True;self.editor=False;self.author_in_comment=False
        def route(r):
            body='<a href="'+self.entry['url']+'">Example Page</a>'
            if self.author_in_comment:body='<article role=article aria-label="Comment by Example Page">'+body+'</article>'
            if self.video:body+='<video controls></video>'
            if self.editor:body+='<form role=form aria-label=Reels>Unpublished editor</form>'
            body+='<script type="application/json">'+json.dumps(self.node)+'</script>'
            r.fulfill(content_type='text/html',body=body)
        self.context.route('https://www.facebook.com/**',route)
    def tearDown(self):self.context.close()
    def inspect(self):return guided.inspect_video(self.page,self.context,self.entry,'Exact caption',900,1100,'https://www.facebook.com/reel/9001',seconds=1.4)
    def test_visible_exact_video_and_owner_complete_missing_publish_flag_proof(self):
        valid,proof=self.inspect();self.assertTrue(valid);self.assertTrue(proof['visible_video']);self.assertFalse(proof['explicit_published'])
    def test_missing_player_without_explicit_publication_or_visible_editor_are_not_accepted(self):
        self.video=False;valid,_=self.inspect();self.assertFalse(valid)
        self.video=True;self.editor=True;valid,proof=self.inspect();self.assertFalse(valid);self.assertTrue(proof['editor'])
    def test_mobile_exact_link_is_normalized_and_other_authors_never_pass(self):
        result=guided.validate_selected(self.page,self.entry,'https://m.facebook.com/reel/9001?locale=en_US');self.assertEqual(result,'https://www.facebook.com/reel/9001')
        with self.assertRaises(ValueError):guided.validate_selected(self.page,self.entry,'https://outside.example/reel/9001')
    def test_a_comment_author_link_is_not_used_as_video_author_evidence(self):
        self.author_in_comment=True
        with self.assertRaises(ValueError):guided.validate_selected(self.page,self.entry,'https://www.facebook.com/reel/9001')
