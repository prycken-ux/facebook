import contextlib
import unittest
from unittest.mock import patch
import page_reel_ai_compat as compat
import fb_upload as upload
from test_modern_editor import ModernEditorTests, EDITOR


class StyledAIEditorTests(ModernEditorTests):
    def test_hidden_native_checkbox_off_is_verified_without_clicking_or_posting(self):
        self.entry['ai_label'] = False
        self.editor = EDITOR.replace('id="ai" type="checkbox"','id="ai" style="display:none" type="checkbox"')
        with compat.installed():
            button,proof = self.prepare()
        self.assertFalse(self.page.locator('#ai').is_checked())
        self.assertTrue(button.is_enabled())
        self.assertIsNone(self.page.evaluate('window.postClicks'))
        self.assertIsNone(self.page.evaluate('window.aiChanges'))

    def test_hidden_on_switch_is_changed_by_visible_parent_then_verified(self):
        self.entry['ai_label'] = False
        self.editor = EDITOR.replace('id="ai" type="checkbox"','id="ai" checked style="display:none" type="checkbox"')
        self.editor = self.editor.replace('aria-label="Add AI label Add AI label We require you to label content"',
            'aria-label="Add AI label Add AI label We require you to label content" onclick="document.querySelector(\'#ai\').checked=!document.querySelector(\'#ai\').checked;window.aiParentClicks=(window.aiParentClicks||0)+1"')
        with compat.installed():
            self.prepare()
        self.assertFalse(self.page.locator('#ai').is_checked())
        self.assertEqual(self.page.evaluate('window.aiParentClicks'),1)
        self.assertIsNone(self.page.evaluate('window.postClicks'))

    def test_aria_pressed_ai_button_does_not_touch_unrelated_switch(self):
        self.page.set_content('''<button aria-label="Add AI label" aria-pressed="true" onclick="this.setAttribute('aria-pressed','false')">AI</button>
            <input type="checkbox" aria-label="Notifications" checked><button onclick="window.posts=1">Post</button>''')
        compat.set_modern_ai(self.page,dict(ai_label=False),timeout_ms=500)
        self.assertEqual(self.page.get_by_role('button',name='Add AI label').get_attribute('aria-pressed'),'false')
        self.assertTrue(self.page.get_by_label('Notifications').is_checked())
        self.assertIsNone(self.page.evaluate('window.posts'))

    def test_duplicate_ai_controls_and_unreadable_state_are_rejected(self):
        self.page.set_content('<button aria-label="Add AI label" aria-pressed="false">A</button>'*2)
        with self.assertRaisesRegex(RuntimeError,'多个可见'):
            compat.set_modern_ai(self.page,dict(ai_label=False),timeout_ms=100)
        self.page.set_content('<button aria-label="Add AI label"><span>Off</span></button>')
        with self.assertRaises(RuntimeError):
            compat.set_modern_ai(self.page,dict(ai_label=False),timeout_ms=100)

    def test_unknown_overlay_is_never_forced_through_and_hook_restores(self):
        self.page.set_content('''<button aria-label="Add AI label" aria-pressed="true" onclick="window.toggled=1">AI</button>
            <div role="dialog" style="position:fixed;inset:0;background:white;z-index:100">Unknown confirmation</div>''')
        original = upload.set_ai_label
        with self.assertRaises(Exception):
            with compat.installed():
                compat.set_modern_ai(self.page,dict(ai_label=False),timeout_ms=150)
        self.assertIsNone(self.page.evaluate('window.toggled'))
        self.assertIs(upload.set_ai_label,original)


if __name__ == '__main__':
    unittest.main()
