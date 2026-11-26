import base64,hashlib,json,zlib
from pathlib import Path
NAMES=('resume_nov25_selected18_20261126.py','resume18_target_watchdog_20261126.py','queue_resume_nov25_selected18_20261126.ps1','set_login_abnormal_fb32_fb52_20261126.py','pending_video_comment_lookup_20261119.py','actual_reels_comment_lookup.py')
def build():
    root=Path(__file__).parent;files={n:(root/n).read_bytes() for n in NAMES}
    fp=hashlib.sha256(json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in files.items()},sort_keys=True).encode()).hexdigest()
    payload=base64.b64encode(zlib.compress(json.dumps({n:base64.b64encode(b).decode() for n,b in files.items()},sort_keys=True).encode(),9)).decode()
    expr="{n:base64.b64decode(b) for n,b in json.loads(zlib.decompress(base64.b64decode("+repr(payload)+"))).items()}"
    text=(root/'start_resume_nov25_selected18_20261126.template.py').read_text().replace('import ast,','import base64,zlib,ast,').replace('ADDITIONS={}','ADDITIONS='+expr).replace("FINGERPRINT=''",'FINGERPRINT='+repr(fp));data=text.encode();assert len(data)<=131072
    (root/'start_resume_nov25_selected18_20261126.py').write_bytes(data);print('fingerprint',fp,'starter SHA256',hashlib.sha256(data).hexdigest(),'bytes',len(data))
if __name__=='__main__':build()
