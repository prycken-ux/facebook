"""Apply the tested audience prompt recovery only inside this publisher run."""
import contextlib
from unittest.mock import patch
import fb_upload as upload
import reel_audience_dialog_recovery as recovery

VERSION='1.0-scoped-audience-close-continue-before-public'


@contextlib.contextmanager
def installed():
    original=upload.ensure_personal_public_audience
    def ensure(page):
        from playwright.sync_api import expect
        settings=page.get_by_role('dialog',name='Reel settings',exact=True,include_hidden=True)
        expect(settings).to_be_visible(timeout=240000)
        expect(settings.get_by_role('textbox',name='Describe your reel...',exact=True,include_hidden=True)).to_be_visible(timeout=240000)
        choice=settings.get_by_role('button',name=recovery.re.compile(r'^(Public|Friends)\b'))
        recovery.wait_for_public_controls(page,settings,choice)
        return original(page)
    with patch.object(upload,'ensure_personal_public_audience',side_effect=ensure):
        yield
