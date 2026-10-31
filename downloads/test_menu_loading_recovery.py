"""Reproduce the diagnostic Menu skeleton with no Reel button after five seconds."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import fb_upload as upload


class MenuLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)

    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.page=self.browser.new_page()
        self.temp=tempfile.TemporaryDirectory();self.video=Path(self.temp.name)/'original.mp4';self.video.write_bytes(b'exact original')
        self.page.set_content('''<div role="dialog" aria-label="Menu" id="menu"><div id="skeleton">Loading</div></div>
          <input id="file" type="file" hidden onchange="window.files=(window.files||0)+1">
          <button onclick="window.post=(window.post||0)+1">Post</button>''')
        self.reel=self.page.get_by_role('dialog',name='Menu',exact=True).get_by_role('button',name='Reel',exact=True)
        self.silence=contextlib.redirect_stdout(io.StringIO());self.silence.__enter__()

    def tearDown(self):self.silence.__exit__(None,None,None);self.page.close();self.temp.cleanup()

    def show_reel_later(self,delay=150,disabled=False):
        self.page.evaluate('''({delay,disabled})=>setTimeout(()=>{
            document.querySelector('#skeleton').remove();
            const b=document.createElement('button');b.textContent='Reel';b.disabled=disabled;
            b.onclick=()=>{window.reelClicks=(window.reelClicks||0)+1;document.querySelector('#file').click()};
            document.querySelector('#menu').append(b);
        },delay)''',dict(delay=delay,disabled=disabled))

    def test_menu_skeleton_waits_until_reel_is_ready_then_selects_original_once(self):
        self.show_reel_later(delay=400)
        self.assertEqual(upload.select_reel_video(self.page,self.reel,self.video,timeout_ms=150,entry_timeout_ms=1000),'native_file_chooser')
        self.assertEqual(self.page.evaluate('window.files'),1)
        self.assertEqual(self.page.evaluate('window.reelClicks'),1)
        self.assertIsNone(self.page.evaluate('window.post'))

    def test_entry_wait_timeout_happens_before_any_file_selection(self):
        with self.assertRaises(upload.ReelEntryNotReady):
            upload.select_reel_video(self.page,self.reel,self.video,timeout_ms=1000,entry_timeout_ms=80)
        self.assertIsNone(self.page.evaluate('window.files'))
        self.assertIsNone(self.page.evaluate('window.post'))

    def test_disabled_reel_waits_for_enabled_state(self):
        self.show_reel_later(10,True)
        self.page.evaluate("setTimeout(()=>document.querySelector('#menu button').disabled=false,200)")
        upload.wait_reel_button_ready(self.page,self.reel,1000)
        self.assertTrue(self.reel.is_enabled())
        self.assertIsNone(self.page.evaluate('window.files'))

    def test_unknown_modal_is_not_bypassed_or_refreshed(self):
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=\"alertdialog\">Confirm identity</div>')")
        with self.assertRaisesRegex(RuntimeError,'未知弹窗'):
            upload.wait_reel_button_ready(self.page,self.reel,100)
        self.assertIsNone(self.page.evaluate('window.files'))

    def test_ambiguous_reel_buttons_are_not_guessed(self):
        self.page.locator('#menu').evaluate("e=>e.innerHTML='<button>Reel</button><button>Reel</button>'")
        with self.assertRaisesRegex(RuntimeError,'不唯一'):
            upload.wait_reel_button_ready(self.page,self.reel,100)

    def test_one_get_recovery_only_before_file_selection_and_identity_is_rechecked(self):
        entry=dict(type='page',url='https://www.facebook.com/profile.php?id=1001')
        with patch.object(upload,'navigate_profile') as navigate,patch.object(upload,'ensure_identity',return_value={}) as identity, \
             patch.object(upload,'require_english_interface'),patch.object(upload,'recheck_publish_identity') as recheck, \
             patch.object(upload,'target_key',return_value='id:1001'),patch.object(upload,'open_facebook_menu') as menu, \
             patch.object(upload,'select_reel_video',side_effect=[upload.ReelEntryNotReady('menu loading'),'native_file_chooser']) as select, \
             patch.object(upload,'wait_reel_layout',return_value='modern'),patch.object(upload,'recover_empty_modern_editor'),patch.object(upload,'prepare_modern_reel',return_value='post'):
            upload.prepare_reel(self.page,entry,self.video,'original caption')
        self.assertEqual(navigate.call_count,2);self.assertEqual(identity.call_count,2)
        self.assertEqual(menu.call_count,2);self.assertEqual(select.call_count,2);recheck.assert_called_once()

    def test_two_readiness_failures_stop_after_one_reload(self):
        entry=dict(type='page',url='https://www.facebook.com/profile.php?id=1001')
        with patch.object(upload,'navigate_profile') as navigate,patch.object(upload,'ensure_identity',return_value={}), \
             patch.object(upload,'require_english_interface'),patch.object(upload,'recheck_publish_identity'), \
             patch.object(upload,'target_key',return_value='id:1001'),patch.object(upload,'open_facebook_menu'), \
             patch.object(upload,'select_reel_video',side_effect=upload.ReelEntryNotReady('still loading')) as select:
            with self.assertRaises(upload.ReelEntryNotReady):upload.prepare_reel(self.page,entry,self.video,'caption')
        self.assertEqual(navigate.call_count,2);self.assertEqual(select.call_count,2)

    def test_filechooser_or_upload_error_is_never_recovered_by_refreshing_page(self):
        entry=dict(type='page',url='https://www.facebook.com/profile.php?id=1001')
        with patch.object(upload,'navigate_profile') as navigate,patch.object(upload,'ensure_identity',return_value={}), \
             patch.object(upload,'require_english_interface'),patch.object(upload,'open_facebook_menu'), \
             patch.object(upload,'select_reel_video',side_effect=RuntimeError('chooser already started; upload failed')) as select:
            with self.assertRaises(RuntimeError):upload.prepare_reel(self.page,entry,self.video,'caption')
        navigate.assert_called_once();select.assert_called_once()
