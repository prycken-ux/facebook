"""Exercise the recorded personal workflow in Chromium against local fixture HTML."""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright, expect as real_expect

import fb_upload as upload


HTML = '''<main><section><h1>Example Person</h1><button>Edit profile</button></section>
<button onclick="document.querySelector('#reel').hidden=false">Facebook menu</button>
<button id="reel" hidden onclick="document.querySelector('form').hidden=false">Reel</button>
<form aria-label="Reels" hidden onsubmit="return false">
<input type="file" accept="video/*" onchange="window.selectedFile=this.files[0].name">
<button type="button" id="next" onclick="window.steps=(window.steps||0)+1;
if(window.steps===2){this.hidden=true;document.querySelector('#settings').hidden=false}">Next</button>
<div id="settings" hidden><button id="audience" type="button"
onclick="window.audienceOpened=(window.audienceOpened||0)+1;document.querySelector('#audience-dialog').hidden=false">Public Anyone on or off Facebook</button>
<div id="audience-dialog" role="dialog" aria-label="Choose audience" hidden>
<input type="radio" id="public-option" aria-label="Public Anyone on or off Facebook">
<button type="button" onclick="if(document.querySelector('#public-option').checked){document.querySelector('#audience').textContent='Public Anyone on or off Facebook'};document.querySelector('#audience-dialog').hidden=true">Done</button>
</div>
<textarea aria-label="Describe your reel..." oninput="update()"></textarea>
<input type="checkbox" role="switch" aria-label="Add AI label" onchange="update()">
<button id="post" type="button" disabled onclick="window.postClicks=(window.postClicks||0)+1">Post</button>
</div></form></main><script>
function update(){document.querySelector('#post').disabled=!(document.querySelector('textarea').value &&
document.querySelector('[role=switch]').checked)}
</script>'''


def fast_expect(locator):
    assertion = real_expect(locator)
    class FastAssertion:
        def __getattr__(self, name):
            method = getattr(assertion, name)
            return lambda *args, **kwargs: method(*args, **dict(kwargs, timeout=300))
    return FastAssertion()


class PersonalBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.entry = {"account": "fb03", "target": "personal", "type": "personal",
                      "workflow": "personal_recording_v1", "name": "Example Person",
                      "url": "https://www.facebook.com/profile.php?id=1003", "ai_label": True}
        self.context = self.browser.new_context()
        self.context.route("https://www.facebook.com/**", self.route)
        self.html = HTML
        self.me_url = None
        self.me_html = None
        self.me_cookie = None
        self.english_html = None
        self.page = self.context.new_page()
        self.cookies()
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()
        self.expect_patch = patch("playwright.sync_api.expect", side_effect=fast_expect)
        self.expect_patch.start()

    def route(self, route):
        if urlparse(route.request.url).path.rstrip("/") == "/me":
            headers = {"Content-Type": "text/html"}
            if self.me_cookie:
                headers["Set-Cookie"] = self.me_cookie
            route.fulfill(headers=headers, body='<script>location.replace(' + json.dumps(self.me_url or self.entry["url"]) + ')</script>')
        else:
            html = self.me_html if self.me_url and upload.target_key(route.request.url) == upload.target_key(self.me_url) and self.me_html else self.html
            if self.english_html and parse_qs(urlparse(route.request.url).query).get("locale") == ["en_US"]:
                html = self.english_html
            route.fulfill(body=html, content_type="text/html")

    def tearDown(self):
        self.expect_patch.stop()
        self.silence.__exit__(None, None, None)
        self.context.close()

    def cookies(self, person="1003", actor=None):
        self.context.clear_cookies()
        rows = [{"name": "c_user", "value": person}, {"name": "xs", "value": "SESSION-SECRET"}]
        if actor is not None:
            rows.append({"name": "i_user", "value": actor})
        self.context.add_cookies([dict(row, domain=".facebook.com", path="/", secure=True) for row in rows])

    def prepare(self):
        return upload.prepare_reel(self.page, self.entry, Path(__file__), "Fixture caption\n#Example")

    def test_recorded_flow_sets_caption_ai_and_public_without_clicking_post(self):
        button, proof = self.prepare()
        self.assertTrue(button.is_enabled())
        self.assertEqual(self.page.get_by_role("textbox").input_value(), "Fixture caption\n#Example")
        self.assertTrue(self.page.get_by_role("switch").is_checked())
        self.assertEqual(self.page.evaluate("window.selectedFile"), Path(__file__).name)
        self.assertEqual(self.page.evaluate("window.steps"), 2)
        self.assertIsNone(self.page.evaluate("window.postClicks"))
        self.assertEqual(proof["method"], "personal_actor_id_match")
        for secret in ("SESSION-SECRET", "1003"):
            self.assertNotIn(secret, proof["session_marker"])
        self.assertNotIn("SESSION-SECRET", self.silence._new_target.getvalue())
        upload.recheck_publish_identity(self.page, self.entry, proof)

    def test_already_checked_ai_label_stays_on(self):
        self.html = HTML.replace('role="switch"', 'checked role="switch"')
        self.prepare()
        self.assertTrue(self.page.get_by_role("switch").is_checked())

    def test_locale_query_overrides_chinese_ui_before_upload(self):
        self.html = '<html lang="zh-CN">' + HTML.replace("Facebook menu", "菜单") + '</html>'
        self.english_html = '<html lang="en-US">' + HTML + '</html>'
        self.prepare()
        self.assertEqual(self.page.locator("html").get_attribute("lang"), "en-US")
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_site_still_chinese_stops_before_opening_menu_or_selecting_file(self):
        self.html = '<html lang="zh-CN">' + HTML.replace("Facebook menu", "菜单") + '</html>'
        with self.assertRaisesRegex(RuntimeError, "Facebook 界面仍不是英语"):
            self.prepare()
        self.assertIsNone(self.page.evaluate("window.selectedFile"))
        self.assertFalse(self.page.get_by_role("button", name="Reel", exact=True).is_visible())

    def test_alternative_english_menu_name_is_supported(self):
        self.html = HTML.replace('>Facebook menu</button>', '>Menu</button>')
        self.prepare()
        self.assertEqual(self.page.evaluate("window.steps"), 2)

    def test_page_actor_or_wrong_person_stops_before_file_selection(self):
        for person, actor in (("1003", "9000"), ("1004", None)):
            with self.subTest(person=person, actor=actor):
                self.cookies(person, actor)
                with self.assertRaises(RuntimeError):
                    self.prepare()
                self.assertIsNone(self.page.evaluate("window.selectedFile"))

    def test_friends_audience_is_changed_to_public_and_verified_before_filling(self):
        self.html = HTML.replace('>Public Anyone on or off Facebook</button>', '>Friends Your friends on Facebook</button>', 1)
        self.prepare()
        self.assertTrue(self.page.get_by_role("button", name="Public Anyone on or off Facebook", exact=True).is_visible())
        self.assertEqual(self.page.evaluate("window.audienceOpened"), 1)
        self.assertEqual(self.page.get_by_role("textbox").input_value(), "Fixture caption\n#Example")
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_already_public_does_not_open_or_toggle_audience(self):
        self.prepare()
        self.assertIsNone(self.page.evaluate("window.audienceOpened"))

    def test_unknown_audience_stops_before_filling_or_post(self):
        self.html = HTML.replace('>Public Anyone on or off Facebook</button>', '>Only me</button>', 1)
        with self.assertRaisesRegex(RuntimeError, "未识别到 Friends 选择入口"):
            self.prepare()
        self.assertEqual(self.page.get_by_role("textbox").input_value(), "")
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_public_selection_not_saved_stops_before_filling_or_post(self):
        self.html = HTML.replace('>Public Anyone on or off Facebook</button>', '>Friends Your friends on Facebook</button>', 1)
        self.html = self.html.replace("if(document.querySelector('#public-option').checked)", "if(false)")
        with self.assertRaises(AssertionError):
            self.prepare()
        self.assertEqual(self.page.get_by_role("textbox").input_value(), "")
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_vanity_profile_verified_by_me_without_edit_button(self):
        self.entry["url"] = "https://www.facebook.com/example.person.123"
        self.html = HTML.replace("Edit profile", "Message")
        _, proof = self.prepare()
        self.assertEqual(proof["method"], "personal_me_redirect_match")
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_other_profile_even_with_same_name_and_edit_control_is_rejected(self):
        self.entry["url"] = "https://www.facebook.com/example.person.123"
        self.me_url = "https://www.facebook.com/some.other.person"
        with self.assertRaisesRegex(RuntimeError, "无法通过 Facebook 本人主页入口确认"):
            self.prepare()
        self.assertIsNone(self.page.evaluate("window.selectedFile"))

    def test_me_numeric_redirect_requires_matching_actor_and_canonical(self):
        self.entry["url"] = "https://www.facebook.com/example.person.123"
        self.html = HTML.replace("Edit profile", "Message")
        self.me_url = "https://www.facebook.com/profile.php?id=1003"
        self.me_html = '<link rel="canonical" href="' + self.entry["url"] + '">' + self.html
        _, proof = self.prepare()
        self.assertEqual(proof["method"], "personal_me_redirect_match")

    def test_wrong_numeric_redirect_not_accepted_even_if_canonical_matches(self):
        self.entry["url"] = "https://www.facebook.com/example.person.123"
        self.me_url = "https://www.facebook.com/profile.php?id=1004"
        self.me_html = '<link rel="canonical" href="' + self.entry["url"] + '">' + self.html
        with self.assertRaisesRegex(RuntimeError, "无法通过 Facebook 本人主页入口确认"):
            self.prepare()
        self.assertIsNone(self.page.evaluate("window.selectedFile"))

    def test_identity_change_during_me_redirect_stops_before_upload(self):
        self.entry["url"] = "https://www.facebook.com/example.person.123"
        self.me_cookie = "c_user=1004; Domain=.facebook.com; Path=/; Secure"
        with self.assertRaisesRegex(RuntimeError, "本人主页期间登录身份变化"):
            self.prepare()
        self.assertIsNone(self.page.evaluate("window.selectedFile"))

    def test_session_change_before_post_is_rejected_for_vanity_profile(self):
        self.entry["url"] = "https://www.facebook.com/example.person.123"
        _, proof = self.prepare()
        self.cookies(person="1004")
        with self.assertRaisesRegex(RuntimeError, "个人登录身份已变化"):
            upload.recheck_publish_identity(self.page, self.entry, proof)
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_page_actor_equal_to_person_is_allowed(self):
        self.cookies(actor="1003")
        self.prepare()


class PersonalQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(upload, "ROOT", self.root)
        self.root_patch.start()
        self.entry = {"account": "fb03", "target": "personal", "type": "personal",
                      "workflow": "personal_recording_v1", "name": "Example Person",
                      "url": "https://www.facebook.com/profile.php?id=1003", "enabled": True}
        self.folder = upload.inbox_for(self.entry)
        self.folder.mkdir(parents=True)
        self.video = self.folder / "fixture.mp4"
        self.video.write_bytes(b"fixture video bytes")
        self.caption = self.video.with_suffix(".txt")
        self.caption.write_text("Fixture caption")
        for path in (self.video, self.caption):
            os.utime(path, (time.time() - 120, time.time() - 120))
        self.state, self.state_path = {}, self.root / "logs" / "publish_state.json"
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()

    def tearDown(self):
        self.silence.__exit__(None, None, None)
        self.root_patch.stop()
        self.temporary.cleanup()

    def run_browser(self, receipt_error=None, marker="fixture-marker"):
        button, context = MagicMock(), MagicMock()
        context.pages = [MagicMock()]
        proof = {"method": "personal_actor_id_match", "session_marker": "fixture-marker"}
        with patch("playwright.sync_api.sync_playwright"), \
                patch.object(upload, "launch_context", return_value=context), \
                patch.object(upload, "prepare_reel", return_value=(button, proof)), \
                patch.object(upload, "personal_actor_fingerprint", return_value=marker), \
                patch.object(upload, "page_actor_matches") as page_check, \
                patch.object(upload, "install_receipt_watch"), \
                patch.object(upload, "wait_for_receipt", return_value="Your reel is published.", side_effect=receipt_error):
            try:
                upload.run_entry(self.entry, self.state, self.state_path, True)
            finally:
                page_check.assert_not_called()
                self.button = button

    def test_uncertain_personal_post_remains_blocked_without_archiving(self):
        with self.assertRaises(RuntimeError):
            self.run_browser(receipt_error=RuntimeError("No receipt"))
        self.assertEqual(next(iter(self.state.values()))["status"], "needs_review")
        self.button.click.assert_called_once()
        self.assertTrue(self.video.exists())
        with patch.object(upload, "launch_context") as launch, self.assertRaises(RuntimeError):
            upload.run_entry(self.entry, self.state, self.state_path, True)
        launch.assert_not_called()

    def test_personal_success_archives_and_preserves_duplicate_protection(self):
        self.run_browser()
        record = next(iter(upload.read_json(self.state_path, {}).values()))
        self.assertEqual(record["status"], "published")
        self.assertEqual(record["identity_validation"]["method"], "personal_actor_id_match")
        self.assertFalse(self.video.exists())
        self.assertTrue((self.folder.parent / "completed" / self.video.name).exists())
        self.video.write_bytes(b"fixture video bytes")
        self.caption.write_text("Different caption")
        for path in (self.video, self.caption):
            os.utime(path, (time.time() - 120, time.time() - 120))
        self.assertEqual(list(upload.pending_jobs(self.entry, self.state)), [])

    def test_personal_session_change_stops_transaction_before_post(self):
        with self.assertRaises(RuntimeError):
            self.run_browser(marker="changed-session")
        self.button.click.assert_not_called()
        self.assertEqual(next(iter(self.state.values()))["status"], "failed_before_post")


if __name__ == "__main__":
    unittest.main()
