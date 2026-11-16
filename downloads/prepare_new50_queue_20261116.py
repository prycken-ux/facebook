"""Prepare exactly fb25-74 real footage, then open a non-Python queue waiter."""
import hashlib,importlib.util,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parent))
import publish_all_distributed_nov13 as owned
first=owned.first
AUTH='user-confirmed-real-new50-request-20261116-v1'
POINTER='material-staging/new50-real-20261116-queue.json'
VERSION='1.0-reserved50-real-source-queue'


def sibling(name):
    spec=importlib.util.spec_from_file_location('_new50_'+Path(name).stem,Path(__file__).resolve().with_name(name))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


stage=sibling('stage_new50_materials_v3.py')


def checked_queue(root):
    stage.setup(root);owned.reservation()
    path=stage.safe_child(root,root/POINTER);value=first.archive.checked_json(path);p=value['payload']
    if (p.get('schema')!='new50-real-material-queue-v1' or p.get('authorization')!=AUTH or p.get('accounts')!=sorted(owned.NEW)
            or p.get('ai_label') is not False or p.get('real_footage_confirmed') is not True or p.get('generation')!=owned.BATCH_ID):raise ValueError('新增50个账号的实拍排队授权异常。')
    manifest=stage.safe_child(root,root/p['stage_manifest']);_,source=stage.validate_stage(root,manifest)
    d=source['payload']['distribution']['payload']
    if (source['sha256']!=p.get('stage_sha256') or source['payload']['date']!=p.get('material_date') or d.get('target_scope')!='reserved50'
            or len(d['assignments'])!=50 or {(r['account'],r['target']) for r in d['assignments']}!={(a,'personal') for a in owned.NEW}):raise ValueError('新增50个账号素材清单范围或指纹变化。')
    content=first.batch.preferences.content_policy(p['material_date'],p['content_sha256'])
    if content['payload']['caption']!=first.batch.preferences.EVERYDAY_CAPTION or content['payload']['comment']!=first.batch.preferences.EVERYDAY_COMMENT:raise ValueError('排队正文或评论不是原批准版本。')
    return path,value,manifest,source


def prepare(root,source=None):
    root=stage.setup(root);owned.reservation();pointer=stage.safe_child(root,root/POINTER)
    if pointer.exists():
        _,value,_,_=checked_queue(root);print('继续原新增50个账号的固定素材队列，不重新分配。',flush=True);return pointer,value
    folder=stage.safe_child(root,root/'material-staging/new50-prepare');folder.mkdir(parents=True,exist_ok=True)
    with stage.staging_lock(folder):
        preparing=stage.safe_child(root,folder/'source.json')
        saved_preparing=first.upload.read_json(preparing,{})
        if source is None:
            saved=first.upload.read_json(root/stage.materials.SETTINGS,{})
            candidate=saved_preparing.get('source') or saved.get('source')
            if candidate and Path(candidate).is_dir():source=candidate
        while True:
            if source is None:source=stage.materials.choose_source()
            source=stage.materials.validate_source(Path(source).resolve())
            resume=None
            if saved_preparing.get('source')==str(source) and saved_preparing.get('manifest'):
                candidate=stage.safe_child(root,root/saved_preparing['manifest'])
                if candidate.is_file():resume=candidate
            if resume is None:
                day=datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()
                token=hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]
                resume_path=root/'material-staging'/day/(token+'-reserved50')/'manifest.json'
                first.upload.save_json(preparing,dict(authorization=AUTH,source=str(source),manifest=str(resume_path.relative_to(root))))
                if resume_path.is_file():resume=resume_path
            try:manifest,value=stage.prepare(root,source,scope='reserved50',resume_manifest=resume);break
            except ValueError as error:
                if source is not None and '素材不足' in str(error):
                    print('原总目录剩余未分配素材不足50条，请选择新增实拍视频的总文件夹。',flush=True);source=stage.materials.choose_source();saved_preparing={};continue
                raise
        d=value['payload']['distribution']['payload'];rows=d['assignments']
        if len(rows)!=50 or {(r['account'],r['target']) for r in rows}!={(a,'personal') for a in owned.NEW}:raise ValueError('不是新增50个账号的准确范围。')
        content=first.batch.preferences.content_policy(d['date'])
        if not content or content['payload']['caption']!=first.batch.preferences.EVERYDAY_CAPTION or content['payload']['comment']!=first.batch.preferences.EVERYDAY_COMMENT:raise ValueError('原批准文案或评论缺失。')
        previous=first.upload.read_json(root/'material-staging/first24-pending-import.json',{})
        previous_sha=previous.get('sha256')
        if previous_sha:
            old=stage.safe_child(root,root/previous['manifest']);_,old_value=stage.validate_stage(root,old)
            if old_value['sha256']!=previous_sha:raise ValueError('前面44条分配记录异常。')
        p=dict(schema='new50-real-material-queue-v1',authorization=AUTH,accounts=sorted(owned.NEW),generation=owned.BATCH_ID,
               ai_label=False,real_footage_confirmed=True,stage_manifest=str(manifest.relative_to(root)),stage_sha256=value['sha256'],material_date=d['date'],
               content_sha256=content['sha256'],first24_stage_sha256=previous_sha,created_at=datetime.now(timezone.utc).isoformat())
        result=dict(payload=p,sha256=stage.materials.digest(p));first.upload.save_json(pointer,result)
        print('新增50个账号素材已独立准备，AI标签关闭；当前44个目标的素材、发布及AI设置均保留。',flush=True)
        return pointer,result


def start(root):
    root=Path(root).resolve()
    if sys.platform!='win32':raise ValueError('请在原Windows电脑的新PowerShell窗口运行。')
    stage.setup(root);owned.reservation();pointer=stage.safe_child(root,root/POINTER)
    folder=Path(__file__).resolve().parent
    args=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(folder/'queue_new50_after_first24.ps1'),
          '-Root',str(root),'-Queue',str(pointer),'-Prepare',str(folder/'prepare_new50_queue_20261116.py'),'-Publisher',str(folder/'publish_queued_new50_20261116.py')]
    subprocess.Popen(args,creationflags=0x00000010,close_fds=True)
    print('已另开“新增50账号排队发布”窗口，请保留该窗口；本准备窗口可以关闭。它会等前面44个目标收尾后自动发布，不占用旧任务的Python启动链。',flush=True)
    return 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if '--prepare-only' in sys.argv[2:]:prepare(Path(sys.argv[1]));raise SystemExit(0)
        raise SystemExit(start(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停，保留素材及分配进度；重跑同一指令继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
