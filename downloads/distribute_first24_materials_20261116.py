"""Prepare all44 exact first24 targets, then import automatically once idle."""
import copy,importlib.util,json,sys,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    sys.path.insert(0,str(Path(__file__).resolve().parent))


def sibling(name):
    spec=importlib.util.spec_from_file_location('_first24_'+Path(name).stem,Path(__file__).resolve().with_name(name))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


stage=sibling('stage_next_materials_20261116_v2.py')
workers=sibling('material_distribution_worker_check.py')
recovery=sibling('verified_publication_lock_recovery.py')
VERSION='1.0-prepare44-auto-import-when-idle'
EXPECTED={(f'fb{n:02d}','page01' if n in {1,2,5,6,12,13} else 'personal') for n in range(1,25)}|{(a,f'page{n:02d}') for a in ('fb09','fb10') for n in range(1,11)}


def check_scope(rows):
    pairs=[(r['account'],r['target']) for r in rows]
    if len(rows)!=44 or set(pairs)!=EXPECTED:raise ValueError('登记范围不是原fb01–fb24及fb09/fb10各10个公共主页的44个目标；未猜选或改绑。')


def inspect_workers(root):return workers.active_workers(root,Path(__file__).resolve())


def execute(root,source=None):
    root=stage.setup(root)
    folder=stage.safe_child(root,root/'material-staging/first24-dispatch');folder.mkdir(parents=True,exist_ok=True)
    with stage.staging_lock(folder):return dispatch(root,source)


def dispatch(root,source=None):
    upload=stage.upload
    rows,_=stage.target_snapshot(root,scope='existing24');check_scope(rows)
    pointer=stage.safe_child(root,root/'material-staging/first24-pending-import.json')
    saved=upload.read_json(pointer,{})
    pending=None
    if saved and saved.get('complete') is not True and source is None:
        pending=stage.safe_child(root,root/saved['manifest']);_,value=stage.validate_stage(root,pending)
        if saved.get('sha256')!=value['sha256']:raise ValueError('待导入清单指纹异常。')
        if value['payload']['distribution']['payload'].get('target_scope')!='existing24':raise ValueError('待导入清单不是fb01–fb24范围。')
        check_scope(value['payload']['distribution']['payload']['assignments'])
        print('继续上次已准备的44条素材；保留原分配，不重新选择或重排。',flush=True)
    else:
        pending,value=stage.prepare(root,source,scope='existing24');check_scope(value['payload']['distribution']['payload']['assignments'])
    upload.save_json(pointer,dict(manifest=str(pending.relative_to(root)),sha256=value['sha256'],complete=False))
    # Override the old manual import hint: this wrapper carries the correctly
    # verified venv process-chain checker through the final import as well.
    command='& '+' '.join("'"+a.replace("'","''")+"'" for a in (sys.executable,'-u',str(Path(__file__).resolve()),str(root)))
    (pending.parent/'导入指令.txt').write_text(command+'\n',encoding='utf-8-sig')
    print('44条分配已准备：fb01–fb24及20个公共主页，包含fb17；fb25及以后不分配。原件保留，不发布视频。',flush=True)
    print('接下来自动等待当前视频、评论及登录检查退出后导入正式inbox；请保留此窗口。中断后重跑同一入口可继续。',flush=True)
    while True:
        live=inspect_workers(root)
        if live:
            print('素材已准备，等待原任务结束后自动导入。运行任务PID：',','.join(str(r['pid']) for r in live),'；15秒后检查。',flush=True)
            time.sleep(15);continue
        try:
            recovery.recover_locks(root)
            with patch.object(stage,'active_workers',side_effect=inspect_workers):stage.import_stage(root,pending)
            break
        except RuntimeError as error:
            if not any(word in str(error) for word in ('仍有上传任务或遗留锁','仍有任务进程运行','锁内进程仍在运行')):raise
            print('原任务仍在收尾，素材保留；15秒后继续检查。',flush=True);time.sleep(15)
    upload.save_json(pointer,dict(manifest=str(pending.relative_to(root)),sha256=value['sha256'],complete=True))
    summary=['已正式分配44个目标，每个目标1条视频；原素材保留，没有发布视频。']
    for row in value['payload']['distribution']['payload']['assignments']:
        path=stage.materials.safe_inbox(row['account'],row['target'])/row['files'][-1]['destination_name']
        summary.append(row['account']+'/'+row['target']+' <- '+row['video_filename']+' -> '+str(path))
    (pending.parent/'分配完成清单.txt').write_text('\n'.join(summary),encoding='utf-8-sig')
    print('正式分配完成：44个目标；清单：',pending.parent/'分配完成清单.txt',flush=True)
    return 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if sys.platform!='win32':raise ValueError('请在原Windows上传电脑的另一个PowerShell窗口运行。')
        raise SystemExit(execute(Path(sys.argv[1])))
    except KeyboardInterrupt:print('已暂停素材分配；原发布任务、原素材、暂存及导入进度均保留，重跑本入口继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
