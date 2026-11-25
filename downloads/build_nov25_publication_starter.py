"""Render the immutable, source-verifiable Nov25 Windows installer."""
import hashlib,json
from pathlib import Path
NAMES=('publish_eligible60_real_20261125.py','publication_target_watchdog_20261125.py','queue_publish_guarded_nov25_20261125.ps1','nov25_publication_policy.py','comment_deadline_windows_job_20261124.py','reel_audience_dialog_recovery.py','publication_response_finish_guard.py','publication_file_state_20261124.py','release_idle_publication_profile_20261124.ps1')
def build():
    root=Path(__file__).parent;files={n:(root/n).read_bytes() for n in NAMES}
    fp=hashlib.sha256(json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in files.items()},sort_keys=True).encode()).hexdigest()
    text=(root/'start_publish_guarded_nov25_20261125.template.py').read_text().replace('ADDITIONS={}','ADDITIONS='+repr(files)).replace("FINGERPRINT=''",'FINGERPRINT='+repr(fp))
    data=text.encode();assert len(data)<=131072
    (root/'start_publish_guarded_nov25_20261125.py').write_bytes(data)
    print('fingerprint',fp,'starter SHA256',hashlib.sha256(data).hexdigest(),'bytes',len(data))
if __name__=='__main__':build()
