import contextlib
import io
import tempfile
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

import comment_ai as ai

KEY = 'sk-not-a-real-key-for-local-tests-only'


class Field:
    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def delete(self, *args):
        self.value = ''

    def insert(self, index, value):
        self.value = value


class Status:
    def __init__(self):
        self.value = ''

    def set(self, value):
        self.value = value


class GuiSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.field, self.status, self.window = Field(), Status(), MagicMock()
        self.dialog = ai.KeySetupDialog(self.root,self.window,self.field,self.status)
        self.output = io.StringIO()
        self.silence = contextlib.redirect_stdout(self.output)
        self.silence.__enter__()
        self.addCleanup(self.silence.__exit__,None,None,None)

    def test_explicit_paste_replaces_old_content_without_echoing(self):
        self.field.value = 'old clipboard text'
        self.window.clipboard_get.assert_not_called()
        self.window.clipboard_get.return_value = ' \n' + KEY + '\n'
        self.dialog.paste()
        self.assertEqual(self.field.value,KEY)
        self.window.clipboard_get.assert_called_once()
        self.assertNotIn(KEY,self.status.value)
        self.assertNotIn(KEY,self.output.getvalue())

    def test_save_encrypts_and_clears_the_field_before_closing(self):
        self.field.value = KEY
        with patch.object(ai,'dpapi',side_effect=[b'ENCRYPTED-GUI',KEY.encode()]):
            self.dialog.save()
        self.assertEqual((self.root/ai.KEY_NAME).read_bytes(),b'ENCRYPTED-GUI')
        self.assertNotIn(KEY,(self.root/ai.CONFIG_NAME).read_text())
        self.assertEqual(self.field.value,'')
        self.assertEqual(self.dialog.result,0)
        self.window.destroy.assert_called_once()
        self.assertNotIn(KEY,self.output.getvalue())

    def test_command_or_masked_key_rejected_then_valid_paste_can_recover(self):
        values = ['Invoke-WebRequest -Uri https://example.com/',
                  'sk-proj-**************', 'sk-proj-...masked-display', 'sk-proj-…masked-display',
                  '', 'sk-short', '"'+KEY+'"']
        with patch.object(ai,'save_setup') as save:
            for value in values:
                self.field.value = value
                self.dialog.save()
                self.assertNotEqual(self.dialog.result,0)
                self.window.destroy.assert_not_called()
                save.assert_not_called()
                self.assertNotIn(KEY,self.status.value)
            self.window.clipboard_get.return_value = KEY
            self.dialog.paste()
            self.dialog.save()
        save.assert_called_once_with(self.root,KEY)
        self.assertEqual(self.dialog.result,0)

    def test_save_error_does_not_expose_exception_or_close_window(self):
        self.field.value = KEY
        with patch.object(ai,'save_setup',side_effect=RuntimeError(KEY)):
            self.dialog.save()
        self.assertNotIn(KEY,self.output.getvalue())
        self.assertNotIn(KEY,self.status.value)
        self.window.destroy.assert_not_called()
        self.assertEqual(self.dialog.result,2)

    def test_cancel_never_changes_an_existing_encrypted_key(self):
        existing = self.root/ai.KEY_NAME
        existing.parent.mkdir()
        existing.write_bytes(b'RETAIN-OLD-ENCRYPTED')
        self.field.value = KEY
        self.dialog.cancel()
        self.assertEqual(existing.read_bytes(),b'RETAIN-OLD-ENCRYPTED')
        self.assertEqual(self.field.value,'')
        self.assertEqual(self.dialog.result,2)
        self.window.destroy.assert_called_once()

    def test_clipboard_failure_is_not_echoed_and_does_not_erase_field(self):
        self.field.value = 'existing masked entry'
        self.window.clipboard_get.side_effect = RuntimeError(KEY)
        self.dialog.paste()
        self.assertEqual(self.field.value,'existing masked entry')
        self.assertNotIn(KEY,self.status.value)
        self.assertNotIn(KEY,self.output.getvalue())

    def test_gui_builder_masks_entry_and_does_not_read_clipboard_automatically(self):
        tk, ttk = ModuleType('tkinter'), ModuleType('tkinter.ttk')
        window = MagicMock()
        tk.Tk = MagicMock(return_value=window)
        tk.StringVar = MagicMock()
        tk.ttk = ttk
        for widget in ('Frame','Label','Entry','Button'):
            setattr(ttk,widget,MagicMock())
        with patch.dict('sys.modules',{'tkinter':tk,'tkinter.ttk':ttk}):
            self.assertEqual(ai.setup_gui(self.root),2)
        self.assertEqual(ttk.Entry.call_args.kwargs['show'],'*')
        window.clipboard_get.assert_not_called()
        window.mainloop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
