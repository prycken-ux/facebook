import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import fb_upload as upload


class FilePickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.video = Path(self.temporary.name) / "fixture.mp4"
        self.video.write_bytes(b"video fixture bytes")
        self.page = self.browser.new_page()
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()

    def tearDown(self):
        self.silence.__exit__(None, None, None)
        self.page.close()
        self.temporary.cleanup()

    def native(self, delay=False, in_form=False):
        trigger = "setTimeout(()=>document.querySelector('#file').click(),100)" if delay else "document.querySelector('#file').click()"
        field = '<input id="file" type="file" hidden onchange="window.changes=(window.changes||0)+1;window.selected=this.files[0].name">'
        if in_form:
            field = '<form aria-label="Reels">' + field + '</form>'
        self.page.set_content('<button onclick="' + trigger + '">Reel</button>' + field)

    def select(self, timeout_ms=3000):
        return upload.select_reel_video(self.page, self.page.get_by_role("button", name="Reel", exact=True), self.video, timeout_ms)

    def test_native_picker_outside_reels_form_selects_known_file(self):
        self.native()
        self.assertEqual(self.select(), "native_file_chooser")
        self.assertEqual(self.page.evaluate("window.selected"), self.video.name)
        self.assertEqual(self.page.evaluate("window.changes"), 1)

    def test_delayed_native_picker_is_captured_without_form(self):
        self.native(delay=True)
        self.assertEqual(self.select(), "native_file_chooser")
        self.assertEqual(self.page.evaluate("window.changes"), 1)

    def test_web_form_upload_remains_supported(self):
        self.page.set_content('''<button onclick="document.querySelector('form').hidden=false">Reel</button>
        <form aria-label="Reels" hidden><input type="file" onchange="window.changes=(window.changes||0)+1;window.selected=this.files[0].name"></form>''')
        self.assertEqual(self.select(), "reels_form_file_input")
        self.assertEqual(self.page.evaluate("window.selected"), self.video.name)
        self.assertEqual(self.page.evaluate("window.changes"), 1)

    def test_native_event_with_existing_form_does_not_upload_twice(self):
        self.native(in_form=True)
        self.assertIn(self.select(), {"native_file_chooser", "reels_form_file_input"})
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate("window.changes"), 1)

    def test_missing_picker_and_form_stops_and_removes_listener(self):
        self.page.set_content('<button>Reel</button><button onclick="window.postClicks=1">Post</button>')
        with patch.object(self.page, "remove_listener", wraps=self.page.remove_listener) as remove:
            with self.assertRaisesRegex(RuntimeError, "未捕获到选文件窗口"):
                self.select(timeout_ms=100)
            remove.assert_called_once()
        self.assertIsNone(self.page.evaluate("window.postClicks"))

    def test_ambiguous_file_inputs_are_not_selected(self):
        self.page.set_content('<button>Reel</button><form aria-label="Reels"><input type="file"><input type="file"></form>')
        with self.assertRaisesRegex(RuntimeError, "多个文件输入框"):
            self.select()
        self.assertEqual(self.page.locator('input[type="file"]').evaluate_all("xs=>xs.map(x=>x.files.length)"), [0, 0])


if __name__ == "__main__":
    unittest.main()
