"""Prepare a separate dated material staging tree; import only after workers exit."""
import argparse,contextlib,copy,hashlib,json,os,re,shutil,subprocess,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[2]).resolve())) if len(sys.argv)>2 else None
import fb_upload as upload
import distribute_video_materials as materials

VERSION='1.0-independent-material-staging'
SCHEMA='next-material-staging-v1'
STAGING='material-staging'
WORKERS=r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$d=[Console]::In.ReadToEnd() | ConvertFrom-Json
$result=@()
foreach($p in @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop)) {
  if([long]$p.ProcessId -eq [long]$d.pid){continue}
  $line=[string]$p.CommandLine
  $exe=[string]$p.ExecutablePath
  if([string]::IsNullOrWhiteSpace($line) -and [string]::IsNullOrWhiteSpace($exe)){throw 'Cannot inspect a Python process safely'}
  $sameExe=[string]::Equals($exe,[string]$d.python,[StringComparison]::OrdinalIgnoreCase)
  $sameRoot=$line.IndexOf([string]$d.root,[StringComparison]::OrdinalIgnoreCase) -ge 0
  if(-not($sameExe -or $sameRoot)){continue}
  if($line -match '(?i)(?:stage_next_materials_20261114_v1|start_stage_next_materials_20261114)\.py'){continue}
  $result += [pscustomobject]@{pid=[long]$p.ProcessId;name=[string]$p.Name}
}
ConvertTo-Json -InputObject @($result) -Compress
'''


def setup(root):
    root=Path(root).resolve()
    if upload.ROOT.resolve()!=root:raise ValueError('请在原上传目录运行，未访问其他账号目录。')
    materials.ROOT=root
    safe_child(root,root/STAGING)
    return root


def safe_child(root,path):
    root=Path(root).resolve();path=Path(path)
    path.resolve().relative_to(root)
    for item in (path,*path.parents):
        if item==root:break
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):raise ValueError('目录包含链接，未复制：'+str(item))
    return path


@contextlib.contextmanager
def staging_lock(folder):
    path=safe_child(folder,folder/'prepare.lock');handle=path.open('a+b')
    try:
        handle.seek(0)
        if handle.read(1)==b'':handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise RuntimeError('同一批素材的暂存/导入程序仍在运行；未启动第二份。') from None
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
    finally:handle.close()


def target_snapshot(root):
    paths=[root/n for n in ('upload_config.json','account_registry.json','additional_personal_accounts.json')]
    read=upload.read_json
    for _ in range(5):
        before={p:p.read_bytes() if p.is_file() else None for p in paths}
        values={p:json.loads(blob.decode('utf-8-sig')) if blob is not None else None for p,blob in before.items()}
        def from_snapshot(path,default):return copy.deepcopy(values[path] if values[path] is not None else default) if path in values else read(path,default)
        try:
            with patch.object(upload,'read_json',side_effect=from_snapshot):selected=materials.targets(upload,scope='all')
        except Exception:
            if any((p.read_bytes() if p.is_file() else None)!=blob for p,blob in before.items()):time.sleep(.2);continue
            raise
        if all((p.read_bytes() if p.is_file() else None)==blob for p,blob in before.items()):
            generations={a:s.get('batch_id') for a,s in (values[paths[2]] or {}).get('slots',{}).items()}
            return selected,generations
        time.sleep(.2)
    raise ValueError('账号登记正在更新，暂未取得稳定快照；请稍后重试，未改动当前发布任务。')


def validate_stage(root,path):
    path=safe_child(root/STAGING,Path(path));value=upload.read_json(path,{})
    p=value.get('payload',{})
    if value.get('sha256')!=materials.digest(p) or p.get('schema')!=SCHEMA:raise ValueError('暂存清单指纹异常。')
    source=Path(p.get('source','')).resolve();token=hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]
    if (not re.fullmatch(r'\d{4}-\d{2}-\d{2}',p.get('date','')) or p.get('source_id')!=token
            or path!=root/STAGING/p['date']/token/'manifest.json'):raise ValueError('暂存清单路径或原素材来源异常。')
    distribution=p.get('distribution',{});d=distribution.get('payload',{})
    if (distribution.get('sha256')!=materials.digest(d) or d.get('schema')!=materials.SCHEMA or d.get('date')!=p['date']
            or d.get('source')!=str(source) or d.get('target_scope')!='all' or not isinstance(d.get('assignments'),list) or not d['assignments']):raise ValueError('暂存的正式分配清单异常。')
    pairs=[]
    for row in d['assignments']:
        materials.safe_inbox(row['account'],row['target']);pairs.append((row['account'],row['target']))
        for info in row['files']:
            if any(not isinstance(info.get(k),str) or Path(info[k]).name!=info[k] or re.search(r'[\\/:\x00-\x1f]',info[k]) for k in ('name','destination_name')):raise ValueError('素材文件名异常。')
        upload.validate_video_filename(row['files'][-1]['name']);upload.validate_video_filename(row['files'][-1]['destination_name'])
    if len(set(pairs))!=len(pairs):raise ValueError('暂存发布目标重复。')
    return path,value


def prepare(root,source=None):
    root=setup(root)
    if source is None:
        print('请选择今天的素材总文件夹。本窗口仅准备暂存素材，当前发布任务继续运行。',flush=True)
        source=materials.choose_source()
    source=materials.validate_source(Path(source).resolve())
    if source.is_relative_to((root/STAGING).resolve()):raise ValueError('请选择素材总文件夹，不要选择已生成的暂存目录。')
    day=datetime.now(timezone.utc).astimezone(materials.BJ).date().isoformat()
    token=hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]
    folder=safe_child(root/STAGING,root/STAGING/day/token);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'manifest.json'
    with staging_lock(folder):
        if path.exists():path,value=validate_stage(root,path)
        else:
            selected,generations=target_snapshot(root)
            journal=root/'logs/material-distribution'/token
            if (journal/(day+'.json')).exists():raise ValueError('此素材目录今天已有正式分配清单，未另建或重排，请先核对原分配记录。')
            processed=set()
            for old in journal.glob('*.json') if journal.is_dir() else ():
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:-reserved50)?\.json',old.name):continue
                saved=materials.read_plan(upload,old);progress=upload.read_json(old.with_name(old.stem+'-progress.json'),{})
                if progress.get('sha256')!=saved['sha256'] or progress.get('complete') is not True:raise ValueError('该总目录还有未完成的正式分配；先保留当前任务，本次未重新分配。')
                processed.update(r['source_token'] for r in saved['payload']['assignments'])
            files=[]
            for file in sorted(source.iterdir(),key=lambda f:(materials.natural(f.name),f.name)):
                if not file.is_file() or file.suffix.lower()!='.mp4':continue
                upload.validate_video_filename(file.name);info=materials.file_info(file)
                if not info['size']:raise ValueError('视频为空：'+file.name)
                identity=materials.digest(dict(name=file.name.casefold(),sha256=info['sha256']))
                if identity not in processed:files.append((file,info,identity))
            if len(files)<len(selected):raise ValueError('素材不足：'+str(len(selected))+'个目标需要各1条，新素材只有'+str(len(files))+'条。本次没有复制或更改正式文件夹。')
            rows=[]
            prefix=day.replace('-','')+'-'+token[:8]+'-'
            for target,(file,info,identity) in zip(selected,files):
                parts=[materials.file_info(p) for p in (file.with_suffix('.txt'),file.with_suffix('.comment.txt')) if p.exists()]+[info]
                rows.append(dict(target,source_token=identity,video_filename=file.name,files=[dict(part,destination_name=prefix+part['name']) for part in parts]))
            d=dict(schema=materials.SCHEMA,source=str(source),date=day,assignments=rows,leftover_count=len(files)-len(rows),copy_mode='retain-source',target_scope='all',publication_order=['fb01-fb24-and-registered-pages','fb25-fb74'])
            p=dict(schema=SCHEMA,date=day,source=str(source),source_id=token,generations=generations,distribution=dict(payload=d,sha256=materials.digest(d)))
            value=dict(payload=p,sha256=materials.digest(p));upload.save_json(path,value)
        rows=value['payload']['distribution']['payload']['assignments']
        progress_path=folder/'prepare-progress.json';progress=upload.read_json(progress_path,dict(sha256=value['sha256'],done=[]))
        keys={r['account']+'/'+r['target'] for r in rows}
        if (progress.get('sha256')!=value['sha256'] or not isinstance(progress.get('done'),list)
                or len(set(progress['done']))!=len(progress['done']) or not set(progress['done'])<=keys):raise ValueError('暂存进度异常，未重新分配。')
        for index,row in enumerate(rows,1):
            pair=row['account']+'/'+row['target'];inbox=safe_child(folder,folder/'videos'/row['account']/row['target']/'inbox');inbox.mkdir(parents=True,exist_ok=True)
            for info in row['files']:materials.copy_exact(source/info['name'],inbox/info['name'],info)
            if pair not in progress['done']:progress['done'].append(pair)
            upload.save_json(progress_path,progress);print(str(index)+'/'+str(len(rows)),pair,'←',row['video_filename'],'（暂存）',flush=True)
        progress['complete']=True;upload.save_json(progress_path,progress)
        arguments=[sys.executable,'-u',str(Path(__file__).resolve()),'import',str(root),'--manifest',str(path)]
        command='& '+' '.join("'"+argument.replace("'","''")+"'" for argument in arguments)
        (folder/'导入指令.txt').write_text(command+'\n',encoding='utf-8-sig')
        lines=['暂存完成，每个目标1条，保留总目录原件；尚未放入正式inbox。',*[(r['account']+'/'+r['target']+' <- '+r['video_filename']) for r in rows],'','当前视频、评论及登录检查全部结束后，另开PowerShell运行：',command]
        (folder/'分配清单.txt').write_text('\n'.join(lines),encoding='utf-8-sig')
        print('暂存完成：',len(rows),'个目标。当前发布记录、正式inbox和分配设置均未改动。',flush=True)
        print('暂存目录：',folder,flush=True);print('等当前发布、评论及手动检查全部结束后，再运行下面这条导入指令：',flush=True);print(command,flush=True)
    return path,value


def active_workers(root):
    if sys.platform!='win32':raise ValueError('导入前的发布进程检查必须在原Windows电脑执行。')
    data=dict(root=str(root),python=str(root/'.venv/Scripts/python.exe'),pid=os.getpid())
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',WORKERS],input=json.dumps(data).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=False,creationflags=0x08000000)
    if result.returncode:raise RuntimeError('无法核对当前发布进程，暂未导入。')
    rows=json.loads(result.stdout.decode('utf-8-sig'))
    if not isinstance(rows,list) or any(not isinstance(r,dict) or type(r.get('pid')) is not int or r.get('name','').lower() not in {'python.exe','pythonw.exe'} for r in rows):raise ValueError('发布进程检查结果异常，暂未导入。')
    return rows


def import_stage(root,manifest):
    root=setup(root);path,value=validate_stage(root,manifest);folder=path.parent
    from add_fb_accounts import locked
    with staging_lock(folder),locked():
        workers=active_workers(root)
        if workers:raise RuntimeError('原上传环境仍有任务进程运行（PID：'+','.join(str(r['pid']) for r in workers)+'）。本次没有导入；请等视频、评论及登录检查全部结束后重试。')
        ready=upload.read_json(folder/'prepare-progress.json',{})
        if ready.get('sha256')!=value['sha256'] or ready.get('complete') is not True:raise ValueError('暂存素材尚未全部准备完成。')
        selected,generations=target_snapshot(root);current={(r['account'],r['target']):r for r in selected}
        distribution=value['payload']['distribution'];d=distribution['payload'];rows=d['assignments']
        if set(current)!={(r['account'],r['target']) for r in rows}:raise ValueError('准备后账号/公共主页范围变化，未自动重排素材。')
        for row in rows:
            now=current[row['account'],row['target']]
            if row.get('url') and (not now.get('url') or upload.target_key(row['url'])!=upload.target_key(now['url'])):raise ValueError('某个编号的已登记身份变化，未导入：'+row['account'])
            if value['payload']['generations'].get(row['account'])!=generations.get(row['account']):raise ValueError('账号预留批次变化，未导入：'+row['account'])
            for info in row['files']:
                staged=safe_child(folder,folder/'videos'/row['account']/row['target']/'inbox'/info['name'])
                if materials.file_info(staged)!=dict(name=info['name'],size=info['size'],sha256=info['sha256']):raise ValueError('暂存原素材变化，未替换其他视频。')
        journal=root/'logs/material-distribution'/value['payload']['source_id']/(d['date']+'.json')
        if journal.exists() and materials.read_plan(upload,journal)['sha256']!=distribution['sha256']:raise ValueError('同一天此总目录已有另一份分配，未覆盖。')
        progress_path=journal.with_name(journal.stem+'-progress.json');progress=upload.read_json(progress_path,dict(sha256=distribution['sha256'],done=[],complete=False))
        keys={r['account']+'/'+r['target'] for r in rows}
        if (progress.get('sha256')!=distribution['sha256'] or not isinstance(progress.get('done'),list)
                or len(set(progress['done']))!=len(progress['done']) or not set(progress['done'])<=keys
                or (progress.get('complete') is True and set(progress['done'])!=keys)):raise ValueError('正式导入进度异常。')
        receipt=upload.read_json(folder/'imported.json',{})
        if receipt.get('sha256')==value['sha256'] and progress.get('complete') is True:
            print('这批素材已导入完成，未重复复制或改动当前分配设置。',flush=True);return distribution
        backup=folder/'import-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f');backup.mkdir(parents=True)
        for old in (root/materials.SETTINGS,journal,progress_path):
            if old.is_file():shutil.copy2(old,backup/old.name)
        upload.save_json(journal,distribution);upload.save_json(progress_path,progress)
        state=upload.read_json(root/'logs/publish_state.json',{})
        for row in rows:
            pair=row['account']+'/'+row['target']
            if pair in progress['done']:continue
            staged=folder/'videos'/row['account']/row['target']/'inbox';owner=current[row['account'],row['target']].get('url')
            if owner and upload.job_key(dict(url=owner),staged/row['files'][-1]['name']) in state:
                progress.setdefault('existing_video_records',[]).append(pair);print('已有此视频任务记录，未重复放入：',pair,flush=True)
            else:
                inbox=materials.safe_inbox(row['account'],row['target']);inbox.mkdir(parents=True,exist_ok=True)
                for info in row['files']:materials.copy_exact(staged/info['name'],inbox/info['destination_name'],info)
                print('已导入：',pair,'←',row['video_filename'],flush=True)
            progress['done'].append(pair);upload.save_json(progress_path,progress)
        progress['complete']=True;upload.save_json(progress_path,progress)
        upload.save_json(root/materials.SETTINGS,dict(schema=materials.SCHEMA,source=d['source'],scope='all-known-and-reserved-targets',target_scope='all',rule='one-per-target-natural-order',copy_mode='retain-source',publication_order=d['publication_order']))
        journal.with_suffix('.txt').write_text('\n'.join([r['account']+'/'+r['target']+' <- '+r['video_filename'] for r in rows]),encoding='utf-8-sig')
        upload.save_json(folder/'imported.json',dict(sha256=value['sha256'],distribution_sha256=distribution['sha256'],journal=str(journal)))
        print('正式导入完成：',len(rows),'个目标。没有发布视频或发送评论，原素材保留。',flush=True)
        return distribution


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','import']);parser.add_argument('root');parser.add_argument('--source');parser.add_argument('--manifest')
    args=parser.parse_args();sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if args.action=='prepare':prepare(args.root,args.source)
        else:import_stage(args.root,args.manifest)
    except KeyboardInterrupt:print('已取消；保留当前发布任务、原素材和暂存进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
