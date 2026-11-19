import unittest
import fb_upload as upload
import reel_audience_prompt_hook_20261119 as hook
from test_reel_audience_dialog_recovery import AudienceRecoveryTests,CONTINUE


class ScopedHookTests(AudienceRecoveryTests):
    def test_scoped_hook_handles_prompt_with_unmodified_original_core(self):
        upload.ensure_personal_public_audience=self.original
        self.load(CONTINUE)
        with hook.installed():
            upload.ensure_personal_public_audience(self.page)
        self.assertIs(upload.ensure_personal_public_audience,self.original)
        self.assertEqual(self.page.evaluate('window.promptClicks'),1)
        self.assertIn('Public',self.page.locator('#audience').inner_text());self.verify_kept()

    def test_scoped_hook_restores_core_on_unknown_dialog(self):
        upload.ensure_personal_public_audience=self.original
        self.load(CONTINUE.replace('Review audience','Unknown popup'))
        with self.assertRaises(RuntimeError):
            with hook.installed():upload.ensure_personal_public_audience(self.page)
        self.assertIs(upload.ensure_personal_public_audience,self.original)
        self.assertIsNone(self.page.evaluate('window.promptClicks'));self.verify_kept()


if __name__=='__main__':unittest.main()
