"""Prepare a separate dated material staging tree; import only after workers exit."""
import argparse,contextlib,copy,hashlib,json,os,re,shutil,subprocess,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[2]).resolve())) if len(sys.argv)>2 else None
import fb_upload as upload
import distribute_video_materials as materials

VERSION='1.6-eligible60-skipping34-independent-staging'
SCOPES={'all','existing24','reserved50','eligible78','eligible62','eligible60'}
UNAVAILABLE={f'fb{n:02d}' for n in (17,23,25,27,28,29,30,33,34,35,36,38,39,40,41,42,43,44,48,50,53,56,57,58,59,61,64,65,67,69,71,72,73,74)}
ALLOCATION_SKIP=UNAVAILABLE
LEGACY62_UNAVAILABLE=UNAVAILABLE-{'fb40','fb43'}
LEGACY_UNAVAILABLE={f'fb{n:02d}' for n in (17,28,30,33,35,36,38,41,58,64,69,71,72,73,74)}
LEGACY_SKIP=LEGACY_UNAVAILABLE|{'fb23'}
ALL_TARGETS=({(f'fb{n:02d}','page01' if n in {1,2,5,6,12,13} else 'personal') for n in range(1,25)}|{(a,f'page{n:02d}') for a in ('fb09','fb10') for n in range(1,11)}|{(f'fb{n:02d}','personal') for n in range(25,75)})
EXPECTED={pair for pair in ALL_TARGETS if pair[0] not in UNAVAILABLE}
LEGACY62_EXPECTED={pair for pair in ALL_TARGETS if pair[0] not in LEGACY62_UNAVAILABLE}
LEGACY_EXPECTED={pair for pair in ALL_TARGETS if pair[0] not in LEGACY_SKIP}

def check_scope(rows,scope='eligible60'):
    pairs=[(r['account'],r['target']) for r in rows]
    expected={'eligible60':EXPECTED,'eligible62':LEGACY62_EXPECTED,'eligible78':LEGACY_EXPECTED}[scope]
    excluded={'eligible60':UNAVAILABLE,'eligible62':LEGACY62_UNAVAILABLE,'eligible78':LEGACY_SKIP}[scope]
    if len(pairs)!=len(expected) or set(pairs)!=expected or any(a in excluded for a,t in pairs):
        raise ValueError('本次必须是60个原登记目标，跳过完整34个暂停账号；旧清单仅核对历史，不导入或重排。' if scope=='eligible60' else '旧分配目标范围异常。')

def check_live_pauses(root,rows):
    path=safe_child(root,root/'publication_account_exclusions.json');value=upload.read_json(path,None)
    if value is None:return
    p=value.get('payload',{})
    if value.get('sha256')!=materials.digest(p) or p.get('schema')!='publication-account-exclusions-v1' or not isinstance(p.get('excluded_accounts'),list):raise ValueError('当前暂停规则记录异常，未导入素材。')
    if {r['account'] for r in rows}&set(p['excluded_accounts']):raise ValueError('当前暂停名单已扩大，本批60清单与之冲突；暂存保留，不向新暂停账号复制或重排。')

def save_paused_policy(root):
    path=safe_child(root,root/'publication_account_exclusions.json');old=upload.read_json(path,None)
    if old is not None and (old.get('sha256')!=materials.digest(old.get('payload',{})) or old.get('payload',{}).get('schema')!='publication-account-exclusions-v1'):raise ValueError('原暂停名单指纹异常，未覆盖。')
    p=copy.deepcopy(old['payload']) if old else dict(schema='publication-account-exclusions-v1')
    p.update(effective_from='2026-11-19',excluded_accounts=sorted(UNAVAILABLE|set(p.get('excluded_accounts',[]))),
             reason='user-confirmed-inaccessible34-including-fb40-fb43',skip_material_allocation=True,skip_verification=True,skip_publication=True,skip_video_retries=True,skip_comment_retries=True)
    value=dict(payload=p,sha256=materials.digest(p))
    if old==value:return
    if path.exists():
        backup=root/'backups'/('eligible60-paused34-policy-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True);shutil.copy2(path,backup/path.name)
    upload.save_json(path,value)

def scope_suffix(scope):return '-'+scope if scope in {'existing24','reserved50','eligible78','eligible62','eligible60'} else ''
def journal_suffix(scope):return '-'+scope if scope in {'reserved50','eligible78','eligible62','eligible60'} else ''
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
  if($line -match '(?i)(?:stage_next_materials_20261114_v1|start_stage_(?:next|first24)_materials_20261114)\.py'){continue}
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


def target_snapshot(root,scope='eligible60'):
    if scope not in SCOPES:raise ValueError('暂存分配范围无效。')
    paths=[root/n for n in ('upload_config.json','account_registry.json','additional_personal_accounts.json')]
    read=upload.read_json
    for _ in range(5):
        before={p:p.read_bytes() if p.is_file() else None for p in paths}
        values={p:json.loads(blob.decode('utf-8-sig')) if blob is not None else None for p,blob in before.items()}
        def from_snapshot(path,default):
            value=copy.deepcopy(values[path] if values[path] is not None else default) if path in values else read(path,default)
            if scope in {'eligible78','eligible62','eligible60'} and path in paths and isinstance(value,dict):
                excluded=UNAVAILABLE if scope=='eligible60' else LEGACY62_UNAVAILABLE if scope=='eligible62' else LEGACY_SKIP
                for key in ('targets','accounts'):
                    if isinstance(value.get(key),list):value[key]=[r for r in value[key] if r.get('account') not in excluded]
                if isinstance(value.get('slots'),dict):value['slots']={a:r for a,r in value['slots'].items() if a not in excluded}
            return value
        try:
            with patch.object(upload,'read_json',side_effect=from_snapshot):selected=materials.targets(upload,scope='all' if scope in {'eligible78','eligible62','eligible60'} else scope)
            if scope in {'eligible78','eligible62','eligible60'}:check_scope(selected,scope=scope)
            if scope=='eligible60':check_live_pauses(root,selected)
        except Exception:
            if any((p.read_bytes() if p.is_file() else None)!=blob for p,blob in before.items()):time.sleep(.2);continue
            raise
        if all((p.read_bytes() if p.is_file() else None)==blob for p,blob in before.items()):
            generations={a:s.get('batch_id') for a,s in (values[paths[2]] or {}).get('slots',{}).items() if scope!='eligible60' or a in {r['account'] for r in selected}}
            return selected,generations
        time.sleep(.2)
    raise ValueError('账号登记正在更新，暂未取得稳定快照；请稍后重试，未改动当前发布任务。')


def validate_stage(root,path):
    path=safe_child(root/STAGING,Path(path));value=upload.read_json(path,{})
    p=value.get('payload',{})
    if value.get('sha256')!=materials.digest(p) or p.get('schema')!=SCHEMA:raise ValueError('暂存清单指纹异常。')
    source=Path(p.get('source','')).resolve();token=hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]
    distribution=p.get('distribution',{});d=distribution.get('payload',{})
    scope=d.get('target_scope')
    if scope not in SCOPES:raise ValueError('暂存清单的分配范围异常。')
    folder=token+scope_suffix(scope)
    if (not re.fullmatch(r'\d{4}-\d{2}-\d{2}',p.get('date','')) or p.get('source_id')!=token
            or path!=root/STAGING/p['date']/folder/'manifest.json'):raise ValueError('暂存清单路径或原素材来源异常。')
    if (distribution.get('sha256')!=materials.digest(d) or d.get('schema')!=materials.SCHEMA or d.get('date')!=p['date']
            or d.get('source')!=str(source) or not isinstance(d.get('assignments'),list) or not d['assignments']):raise ValueError('暂存的正式分配清单异常。')
    pairs=[]
    for row in d['assignments']:
        materials.safe_inbox(row['account'],row['target']);pairs.append((row['account'],row['target']))
        if scope=='existing24' and not 1<=int(row['account'][2:])<=24:raise ValueError('本批fb01–fb24素材清单混入范围外账号。')
        if scope=='reserved50' and (not 25<=int(row['account'][2:])<=74 or row['target']!='personal'):raise ValueError('新增50账号范围异常。')
        for info in row['files']:
            if any(not isinstance(info.get(k),str) or Path(info[k]).name!=info[k] or re.search(r'[\\/:\x00-\x1f]',info[k]) for k in ('name','destination_name')):raise ValueError('素材文件名异常。')
        upload.validate_video_filename(row['files'][-1]['name']);upload.validate_video_filename(row['files'][-1]['destination_name'])
    if scope=='eligible78':
        check_scope(d['assignments'],scope='eligible78')
        if d.get('excluded_accounts')!=sorted(LEGACY_UNAVAILABLE) or d.get('manually_prepared_accounts')!=['fb23']:raise ValueError('跳过名单或fb23保留标记异常。')
    if scope=='eligible62':
        check_scope(d['assignments'],scope='eligible62')
        if d.get('excluded_accounts')!=sorted(LEGACY62_UNAVAILABLE) or d.get('paused_policy')!='user-paused32-nov18-v1':raise ValueError('旧62范围暂停记录异常。')
    if scope=='eligible60':
        check_scope(d['assignments'])
        if d.get('excluded_accounts')!=sorted(UNAVAILABLE) or d.get('paused_policy')!='user-paused34-nov19-v1':raise ValueError('34个暂停账号的分配范围记录异常。')
    if len(set(pairs))!=len(pairs):raise ValueError('暂存发布目标重复。')
    return path,value


def prepare(root,source=None,scope='eligible60',resume_manifest=None):
    root=setup(root)
    if scope!='eligible60':raise ValueError('此入口仅授权当前60个目标，不新建旧范围分配。')
    if source is None:
        print('请选择今天的素材总文件夹。本窗口仅准备暂存素材，当前发布任务继续运行。',flush=True)
        source=materials.choose_source()
    source=materials.validate_source(Path(source).resolve())
    if source.is_relative_to((root/STAGING).resolve()):raise ValueError('请选择素材总文件夹，不要选择已生成的暂存目录。')
    day=datetime.now(timezone.utc).astimezone(materials.BJ).date().isoformat()
    if resume_manifest is not None:
        _,previous=validate_stage(root,Path(resume_manifest))
        if previous['payload']['source']!=str(source) or previous['payload']['distribution']['payload']['target_scope']!=scope:
            raise ValueError('原暂存来源或范围不符，未重排。')
        # Continue an existing immutable allocation date. All actual execution
        # timestamps still use the real clock; no new plan is backdated.
        day=previous['payload']['date']
    token=hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]
    folder=safe_child(root/STAGING,root/STAGING/day/(token+scope_suffix(scope)));folder.mkdir(parents=True,exist_ok=True)
    path=folder/'manifest.json'
    with staging_lock(folder):
        if path.exists():path,value=validate_stage(root,path)
        else:
            selected,generations=target_snapshot(root,scope=scope)
            journal=root/'logs/material-distribution'/token
            if (journal/(day+journal_suffix(scope)+'.json')).exists():raise ValueError('此素材目录今天已有正式分配清单，未另建或重排，请先核对原分配记录。')
            processed=set()
            for old in journal.glob('*.json') if journal.is_dir() else ():
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:-reserved50|-eligible78|-eligible62|-eligible60)?\.json',old.name):continue
                saved=materials.read_plan(upload,old);progress=upload.read_json(old.with_name(old.stem+'-progress.json'),{})
                if progress.get('sha256')!=saved['sha256'] or progress.get('complete') is not True:raise ValueError('该总目录还有未完成的正式分配；先保留当前任务，本次未重新分配。')
                processed.update(r['source_token'] for r in saved['payload']['assignments'])
            # Exclude previously assigned footage, including renamed byte-identical
            # copies from the first AI batch. The new50 REAL confirmation must
            # never silently apply to those earlier AI assets.
            processed_hashes=set()
            for other in (root/STAGING).glob('*/*/manifest.json'):
                if other==path:continue
                _,prepared=validate_stage(root,other)
                other_rows=prepared['payload']['distribution']['payload']['assignments']
                processed_hashes.update(r['files'][-1]['sha256'] for r in other_rows)
                if prepared['payload'].get('source_id')==token:processed.update(r['source_token'] for r in other_rows)
            for old in (root/'logs/material-distribution').glob('*/*.json'):
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:-reserved50|-eligible78|-eligible62|-eligible60)?\.json',old.name):continue
                old_value=materials.read_plan(upload,old)
                processed_hashes.update(r['files'][-1]['sha256'] for r in old_value['payload']['assignments'])
            ledger=upload.read_json(safe_child(root,root/'logs/user_confirmed_archived_media.json'),None)
            if ledger is not None:
                if ledger.get('schema')!='user-confirmed-archived-media-v1' or not isinstance(ledger.get('rows'),dict):raise ValueError('既有归档台账格式异常，未重新分配旧视频。')
                for record in ledger['rows'].values():
                    if not isinstance(record,dict):raise ValueError('既有归档台账条目异常。')
                    if record.get('status')=='published' and re.fullmatch('[a-f0-9]{64}',str(record.get('video_sha256',''))):processed_hashes.add(record['video_sha256'])
            cleanup=upload.read_json(root/'logs/user-video-cleanup-20261119-progress.json',None)
            if cleanup is not None:
                plan=upload.read_json(root/'logs/user-video-cleanup-20261119.json',{})
                if (plan.get('sha256')!=materials.digest(plan.get('payload',{})) or cleanup.get('plan_sha256')!=plan.get('sha256') or not isinstance(cleanup.get('rows'),dict)):raise ValueError('原视频清理记录指纹异常，未复用旧素材。')
                processed_hashes.update(r['sha256'] for r in cleanup['rows'].values() if r.get('status')=='deleted' and re.fullmatch('[a-f0-9]{64}',str(r.get('sha256',''))))
            if scope=='eligible78':
                # Preserve the manually prepared fb23 video even if the source
                # folder still contains the same bytes under another filename.
                manual=materials.safe_inbox('fb23','personal')
                if manual.is_dir():
                    for file in manual.iterdir():
                        if file.suffix.lower()=='.mp4' and file.is_file():processed_hashes.add(materials.file_info(file)['sha256'])
            files=[];total_mp4=0
            for file in sorted(source.iterdir(),key=lambda f:(materials.natural(f.name),f.name)):
                if not file.is_file() or file.suffix.lower()!='.mp4':continue
                total_mp4+=1
                upload.validate_video_filename(file.name);info=materials.file_info(file)
                if not info['size']:raise ValueError('视频为空：'+file.name)
                identity=materials.digest(dict(name=file.name.casefold(),sha256=info['sha256']))
                if identity not in processed and info['sha256'] not in processed_hashes:files.append((file,info,identity))
            print('素材目录：',source,'；第一层MP4：',total_mp4,'；历史重复排除：',total_mp4-len(files),'；可用新素材：',len(files),flush=True)
            if len(files)<len(selected):raise ValueError('素材不足：'+str(len(selected))+'个目标需要各1条，新素材只有'+str(len(files))+'条。本次没有复制或更改正式文件夹。')
            rows=[]
            prefix=day.replace('-','')+'-'+token[:8]+'-eligible60-'
            for target,(file,info,identity) in zip(selected,files):
                parts=[materials.file_info(p) for p in (file.with_suffix('.txt'),file.with_suffix('.comment.txt')) if p.exists()]+[info]
                rows.append(dict(target,source_token=identity,video_filename=file.name,files=[dict(part,destination_name=prefix+part['name']) for part in parts]))
            order=['fb25-fb74'] if scope=='reserved50' else ['fb01-fb24-and-registered-pages'] if scope=='existing24' else ['fb01-fb24-and-registered-pages','fb25-fb74']
            d=dict(schema=materials.SCHEMA,source=str(source),date=day,assignments=rows,leftover_count=len(files)-len(rows),copy_mode='retain-source',target_scope=scope,publication_order=order)
            if scope=='eligible60':d.update(excluded_accounts=sorted(UNAVAILABLE),paused_policy='user-paused34-nov19-v1')
            p=dict(schema=SCHEMA,date=day,source=str(source),source_id=token,generations=generations,distribution=dict(payload=d,sha256=materials.digest(d)))
            value=dict(payload=p,sha256=materials.digest(p));upload.save_json(path,value)
        rows=value['payload']['distribution']['payload']['assignments']
        progress_path=folder/'prepare-progress.json';progress=upload.read_json(progress_path,dict(sha256=value['sha256'],done=[]))
        keys={r['account']+'/'+r['target'] for r in rows}
        if (progress.get('sha256')!=value['sha256'] or not isinstance(progress.get('done'),list)
                or len(set(progress['done']))!=len(progress['done']) or not set(progress['done'])<=keys):raise ValueError('暂存进度异常，未重新分配。')
        missing=0
        for row in rows:
            for info in row['files']:
                staged=folder/'videos'/row['account']/row['target']/'inbox'/info['name']
                inbox=materials.safe_inbox(row['account'],row['target'])/info['destination_name']
                missing+=info['size']*((not staged.exists())+(not inbox.exists()))
        if shutil.disk_usage(root).free<missing+64*1024*1024:
            raise ValueError('磁盘可用空间不足以完成暂存及导入；原文件和发布任务均保留，请先清理空间后重跑。')
        for index,row in enumerate(rows,1):
            pair=row['account']+'/'+row['target'];inbox=safe_child(folder,folder/'videos'/row['account']/row['target']/'inbox');inbox.mkdir(parents=True,exist_ok=True)
            for info in row['files']:materials.copy_exact(source/info['name'],inbox/info['name'],info)
            if pair not in progress['done']:progress['done'].append(pair)
            upload.save_json(progress_path,progress);print(str(index)+'/'+str(len(rows)),pair,'←',row['video_filename'],'（暂存）',flush=True)
        progress['complete']=True;upload.save_json(progress_path,progress)
        lines=['暂存完成，每个目标1条，保留总目录原件；外层分配入口会等待原任务结束后自动导入。',*[(r['account']+'/'+r['target']+' <- '+r['video_filename']) for r in rows]]
        (folder/'分配清单.txt').write_text('\n'.join(lines),encoding='utf-8-sig')
        print('暂存完成：',len(rows),'个目标。当前发布记录、正式inbox和分配设置均未改动。',flush=True)
        print('暂存目录：',folder,'；分配入口会自动检查并导入，无需另外粘贴导入命令。',flush=True)
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
    if value['payload']['distribution']['payload']['target_scope']!='eligible60':raise ValueError('本入口不导入旧范围清单，只处理当前60个目标。')
    from add_fb_accounts import locked
    with staging_lock(folder),locked():
        workers=active_workers(root)
        if workers:raise RuntimeError('原上传环境仍有任务进程运行（PID：'+','.join(str(r['pid']) for r in workers)+'）。本次没有导入；请等视频、评论及登录检查全部结束后重试。')
        ready=upload.read_json(folder/'prepare-progress.json',{})
        if ready.get('sha256')!=value['sha256'] or ready.get('complete') is not True:raise ValueError('暂存素材尚未全部准备完成。')
        distribution=value['payload']['distribution'];d=distribution['payload'];rows=d['assignments']
        selected,generations=target_snapshot(root,scope=d['target_scope']);current={(r['account'],r['target']):r for r in selected}
        if set(current)!={(r['account'],r['target']) for r in rows}:raise ValueError('准备后账号/公共主页范围变化，未自动重排素材。')
        for row in rows:
            now=current[row['account'],row['target']]
            if row.get('url') and (not now.get('url') or upload.target_key(row['url'])!=upload.target_key(now['url'])):raise ValueError('某个编号的已登记身份变化，未导入：'+row['account'])
            if value['payload']['generations'].get(row['account'])!=generations.get(row['account']):raise ValueError('账号预留批次变化，未导入：'+row['account'])
            for info in row['files']:
                staged=safe_child(folder,folder/'videos'/row['account']/row['target']/'inbox'/info['name'])
                if materials.file_info(staged)!=dict(name=info['name'],size=info['size'],sha256=info['sha256']):raise ValueError('暂存原素材变化，未替换其他视频。')
        journal=root/'logs/material-distribution'/value['payload']['source_id']/(d['date']+journal_suffix(d['target_scope'])+'.json')
        if journal.exists() and materials.read_plan(upload,journal)['sha256']!=distribution['sha256']:raise ValueError('同一天此总目录已有另一份分配，未覆盖。')
        progress_path=journal.with_name(journal.stem+'-progress.json');progress=upload.read_json(progress_path,dict(sha256=distribution['sha256'],done=[],complete=False))
        keys={r['account']+'/'+r['target'] for r in rows}
        if (progress.get('sha256')!=distribution['sha256'] or not isinstance(progress.get('done'),list)
                or len(set(progress['done']))!=len(progress['done']) or not set(progress['done'])<=keys
                or (progress.get('complete') is True and set(progress['done'])!=keys)):raise ValueError('正式导入进度异常。')
        save_paused_policy(root)
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
        description='eligible60-excluding34-paused-accounts' if d['target_scope']=='eligible60' else 'eligible78-excluding-problem-accounts-and-manual-fb23' if d['target_scope']=='eligible78' else 'reserved-accounts-25-to-74' if d['target_scope']=='reserved50' else 'original-accounts-and-registered-pages' if d['target_scope']=='existing24' else 'all-known-and-reserved-targets'
        upload.save_json(root/materials.SETTINGS,dict(schema=materials.SCHEMA,source=d['source'],scope=description,target_scope=d['target_scope'],rule='one-per-target-natural-order',copy_mode='retain-source',publication_order=d['publication_order'],excluded_accounts=sorted(UNAVAILABLE),allocation_date=d['date']))
        journal.with_suffix('.txt').write_text('\n'.join([r['account']+'/'+r['target']+' <- '+r['video_filename'] for r in rows]),encoding='utf-8-sig')
        upload.save_json(folder/'imported.json',dict(sha256=value['sha256'],distribution_sha256=distribution['sha256'],journal=str(journal)))
        print('正式导入完成：',len(rows),'个目标。没有发布视频或发送评论，原素材保留。',flush=True)
        return distribution


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','import']);parser.add_argument('root');parser.add_argument('--source');parser.add_argument('--manifest');parser.add_argument('--scope',choices=['eligible60'],default='eligible60')
    args=parser.parse_args();sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if args.action=='prepare':prepare(args.root,args.source,scope=args.scope)
        else:import_stage(args.root,args.manifest)
    except KeyboardInterrupt:print('已取消；保留当前发布任务、原素材和暂存进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
