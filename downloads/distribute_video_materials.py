"""Copy one naturally ordered MP4 per known target; retain sources and batch journal."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = 'one-video-per-target-distribution-v1'
SETTINGS = 'material_distribution_settings.json'
BJ = timezone(timedelta(hours=8))


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def natural(value):
    return tuple((0,int(p)) if p.isdecimal() else (1,p.casefold()) for p in re.split(r'(\d+)',value))


def file_info(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('素材缺失或是文件链接：'+str(path))
    before=path.stat()
    value=hashlib.sha256()
    with path.open('rb') as source:
        for part in iter(lambda:source.read(1024*1024),b''):
            value.update(part)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('素材正在变化，请复制完成后再分配：'+path.name)
    return dict(name=path.name,size=after.st_size,sha256=value.hexdigest())


def safe_inbox(account,target):
    if not re.fullmatch(r'fb(?:0[1-9]|[1-9][0-9]+)',account) or not re.fullmatch(r'personal|page[0-9]{2,}',target):
        raise ValueError('发布目标编号格式异常。')
    path=ROOT/'videos'/account/target/'inbox'
    for part in (path,*path.parents):
        if part==ROOT:break
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
            raise ValueError('视频目录包含链接，未复制：'+str(part))
    path.resolve().relative_to((ROOT/'videos').resolve())
    return path


def targets(upload):
    config=upload.read_json(ROOT/'upload_config.json',None)
    registry=upload.read_json(ROOT/'account_registry.json',None)
    if not isinstance(config,dict) or not isinstance(config.get('targets'),list) or not isinstance(registry,dict) or not isinstance(registry.get('accounts'),list):
        raise ValueError('缺少原账号配置或账号对应表，未按文件夹名字猜选。')
    result={}
    def add(row,configured=False):
        account=row.get('account','')
        target=row.get('target') or ('personal' if row.get('type')=='personal' else 'page01')
        safe_inbox(account,target)
        if configured:
            upload.validate_entry(row)
        key=(account,target)
        if key in result and row.get('url') and result[key].get('url') and upload.target_key(row['url'])!=upload.target_key(result[key]['url']):
            raise ValueError('同一目标有不同的登记身份：'+'/'.join(key))
        item=result.setdefault(key,dict(account=account,target=target,name=row.get('name',account),url=row.get('url'),pending=False))
        if row.get('url'):item['url']=row['url']
    for row in config['targets']:add(row,True)
    for row in registry['accounts']:add(row)
    manifest=upload.read_json(ROOT/'additional_personal_accounts.json',dict(schema='additional-personal-logins-v1',slots={},batches={}))
    if not isinstance(manifest,dict) or manifest.get('schema')!='additional-personal-logins-v1' or not isinstance(manifest.get('slots'),dict):
        raise ValueError('新增账号预留登记异常。')
    for account,slot in manifest['slots'].items():
        if not isinstance(slot,dict) or slot.get('state') not in {'pending','registered'}:
            raise ValueError('新增账号预留状态异常。')
        if any(a==account for a,t in result):continue
        if not (ROOT/'profiles'/account).is_dir():
            raise ValueError('新增账号缺少已预留的独立资料目录：'+account)
        safe_inbox(account,'personal')
        result[(account,'personal')]=dict(account=account,target='personal',name=account+'（待核验登记）',url=None,pending=True)
    if not result:raise ValueError('没有可分配的已登记或已预留发布目标。')
    return sorted(result.values(),key=lambda r:(int(r['account'][2:]),0 if r['target']=='personal' else int(r['target'][4:]),r['target']))


def read_plan(upload,path):
    value=upload.read_json(path,{})
    if not isinstance(value,dict) or value.get('sha256')!=digest(value.get('payload',{})) or value.get('payload',{}).get('schema')!=SCHEMA:
        raise ValueError('原素材分配清单指纹不一致，未重新排列素材。')
    return value


def plan(upload,source,day,selected):
    source=source.resolve()
    if not source.is_dir():raise ValueError('素材总文件夹不存在：'+str(source))
    for excluded in ('videos','profiles','logs','backups'):
        if source.is_relative_to((ROOT/excluded).resolve()):
            raise ValueError('请使用独立的素材总文件夹，不要选择发布、登录或日志目录。')
    source_id=hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]
    folder=ROOT/'logs/material-distribution'/source_id
    path=folder/(day+'.json')
    if path.exists():
        value=read_plan(upload,path)
        if value['payload'].get('source')!=str(source) or value['payload'].get('date')!=day:
            raise ValueError('原分配清单的素材路径或日期不一致。')
        current={(r['account'],r['target']) for r in selected}
        if any((r['account'],r['target']) not in current for r in value['payload']['assignments']):
            raise ValueError('原分配目标已删除或变更，未重新创建该账号目录。')
        return path,value
    processed=set()
    if folder.is_dir():
        for old_path in folder.glob('????-??-??.json'):
            old=read_plan(upload,old_path)
            progress=upload.read_json(old_path.with_name(old_path.stem+'-progress.json'),{})
            if progress.get('sha256')!=old['sha256'] or progress.get('complete') is not True:
                raise ValueError('还有未完成的素材分配：'+old_path.stem+'；先续完原批次，未另开一批。')
            processed.update(r['source_token'] for r in old['payload']['assignments'])
    files=[]
    candidates=[p for p in sorted(source.iterdir(),key=lambda p:(natural(p.name),p.name)) if p.suffix.lower()=='.mp4' and p.is_file()]
    for index,file in enumerate(candidates,1):
        if index==1 or index%10==0:print('正在核对总目录视频：',index,'/',len(candidates),flush=True)
        info=file_info(file)
        if not info['size']:raise ValueError('视频为空：'+file.name)
        token=digest(dict(name=file.name.casefold(),sha256=info['sha256']))
        if token not in processed:files.append((file,info,token))
    if len(files)<len(selected):
        raise ValueError('素材不足：共有'+str(len(selected))+'个发布目标，未分配新视频只有'+str(len(files))+'条，还差'+str(len(selected)-len(files))+'条；本次尚未复制。')
    assignments=[]
    for target,(file,info,token) in zip(selected,files):
        inbox=safe_inbox(target['account'],target['target'])
        parts=[]
        for companion in (file.with_suffix('.txt'),file.with_suffix('.comment.txt')):
            if companion.exists():parts.append(file_info(companion))
        parts.append(info)  # Commit the video after its companion text files.
        prefix=''
        for number in range(10000):
            if all(not (inbox/(prefix+p['name'])).exists() or file_info(inbox/(prefix+p['name']))['sha256']==p['sha256'] for p in parts):break
            prefix=day.replace('-','')+'-'+str(number+1)+'-'
        else:raise ValueError('无法为目标选择不覆盖旧素材的文件名。')
        assignments.append(dict(target,source_token=token,video_filename=file.name,
                                files=[dict(p,destination_name=prefix+p['name']) for p in parts]))
    payload=dict(schema=SCHEMA,source=str(source),date=day,assignments=assignments,leftover_count=len(files)-len(selected),copy_mode='retain-source')
    value=dict(payload=payload,sha256=digest(payload))
    upload.save_json(path,value)
    return path,value


def copy_exact(source,destination,info):
    if destination.exists():
        if file_info(destination)['sha256']!=info['sha256']:raise ValueError('目标文件与原分配清单冲突，未覆盖：'+str(destination))
        return
    if file_info(source)!=dict(name=info['name'],size=info['size'],sha256=info['sha256']):
        raise ValueError('已选素材变化，未用其他文件代替：'+str(source))
    temporary=destination.with_name('.'+destination.name+'.distribution-'+uuid.uuid4().hex+'.part')
    try:
        with source.open('rb') as reader,temporary.open('xb') as writer:
            shutil.copyfileobj(reader,writer,1024*1024)
            writer.flush();os.fsync(writer.fileno())
        if file_info(temporary)['sha256']!=info['sha256'] or file_info(source)['sha256']!=info['sha256']:
            raise ValueError('复制时素材发生变化，未提交到目标文件夹。')
        shutil.copystat(source,temporary)
        if os.name=='nt':temporary.rename(destination)  # Windows refuses an existing destination.
        else:os.link(temporary,destination);temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def choose_source():
    if sys.platform!='win32':raise ValueError('选择素材文件夹需在原Windows电脑上运行。')
    script=r'''[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$dialog=New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description='Choose the source folder containing all MP4 videos'
$dialog.ShowNewFolderButton=$false
try { if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){[Console]::WriteLine($dialog.SelectedPath)} } finally {$dialog.Dispose()}
'''
    result=subprocess.run(['powershell.exe','-STA','-NoProfile','-Command',script],capture_output=True,encoding='utf-8',check=True)
    value=result.stdout.strip()
    if not value:raise KeyboardInterrupt
    return value


def distribute(root,source=None,day=None,choose=False):
    global ROOT
    ROOT=Path(root).resolve()
    sys.path.insert(0,str(ROOT))
    import fb_upload as upload
    from add_fb_accounts import locked
    if upload.ROOT.resolve()!=ROOT:raise ValueError('原上传程序目录不一致。')
    if source is None and not choose:
        source=upload.read_json(ROOT/SETTINGS,{}).get('source')
    if choose or not source:
        print('请选择素材总文件夹；以后会记住该目录。',flush=True)
        source=choose_source()
    source=Path(source).resolve()
    day=day or datetime.now(timezone.utc).astimezone(BJ).date().isoformat()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):raise ValueError('分配日期格式无效。')
    with locked():
        selected=targets(upload)
        if not source.is_dir() or any(source.is_relative_to((ROOT/name).resolve()) for name in ('videos','profiles','logs','backups')):
            raise ValueError('请使用独立且存在的素材总文件夹。')
        upload.save_json(ROOT/SETTINGS,dict(schema=SCHEMA,source=str(source),scope='all-known-and-reserved-targets',rule='one-per-target-natural-order',copy_mode='retain-source'))
        path,value=plan(upload,source,day,selected)
        progress_path=path.with_name(path.stem+'-progress.json')
        progress=upload.read_json(progress_path,dict(sha256=value['sha256'],done=[],complete=False))
        keys={r['account']+'/'+r['target'] for r in value['payload']['assignments']}
        if (not isinstance(progress,dict) or progress.get('sha256')!=value['sha256'] or not isinstance(progress.get('done'),list)
                or len(set(progress['done']))!=len(progress['done']) or not set(progress['done'])<=keys
                or (progress.get('complete') is True and set(progress['done'])!=keys)):
            raise ValueError('原素材分配进度异常，未重置。')
        rows=value['payload']['assignments']
        if progress.get('complete'):
            print('当天原分配已完成：',len(rows),'个目标；未重复复制或重新分配。',flush=True)
            print('分配清单：',path.with_suffix('.txt'),flush=True)
            return value
        print('按账号编号及目标顺序分配：',len(rows),'个目标，每个1条视频。',flush=True)
        upload.save_json(progress_path,progress)
        state=upload.read_json(ROOT/'logs/publish_state.json',{})
        current={(r['account'],r['target']):r for r in selected}
        for index,row in enumerate(rows,1):
            key=row['account']+'/'+row['target']
            if key in progress['done']:continue
            video_info=row['files'][-1]
            video_source=source/video_info['name']
            if file_info(video_source)['sha256']!=video_info['sha256']:
                raise ValueError('已选原视频发生变化，未重排素材：'+video_source.name)
            owner=row.get('url') or current[(row['account'],row['target'])].get('url')
            if owner and upload.job_key(dict(url=owner),video_source) in state:
                progress['done'].append(key)
                progress.setdefault('existing_video_records',[]).append(key)
                upload.save_json(progress_path,progress)
                print(str(index)+'/'+str(len(rows)),key,'已有此视频任务记录，未重复放入。',flush=True)
                continue
            inbox=safe_inbox(row['account'],row['target'])
            inbox.mkdir(parents=True,exist_ok=True)
            for info in row['files']:
                copy_exact(source/info['name'],inbox/info['destination_name'],info)
            progress['done'].append(key)
            upload.save_json(progress_path,progress)
            video=row['files'][-1]['destination_name']
            print(str(index)+'/'+str(len(rows)),key,'←',row['video_filename'],'→',video,flush=True)
        summary=['每个发布目标1条视频；复制分配，保留总文件夹原件。','素材总目录：'+str(source),'']
        known=set(progress.get('existing_video_records',[]))
        summary.extend(r['account']+'/'+r['target']+' <- '+r['video_filename']+' -> '+('已有此视频任务记录，未重复放入' if r['account']+'/'+r['target'] in known else str(safe_inbox(r['account'],r['target'])/r['files'][-1]['destination_name'])) for r in rows)
        path.with_suffix('.txt').write_text('\n'.join(summary),encoding='utf-8-sig')
        progress['complete']=True
        upload.save_json(progress_path,progress)
        known=len(progress.get('existing_video_records',[]))
        print('分配处理完成：',len(rows),'个目标；其中',known,'个已有该视频任务记录，未重复放入。总文件夹另有',value['payload']['leftover_count'],'条尚未分配。',flush=True)
        print('分配清单：',path.with_suffix('.txt'),flush=True)
        print('本次只分配素材；账号仍按原接入状态管理，没有发布视频或发送评论。',flush=True)
        return value


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default=str(ROOT));parser.add_argument('--source')
    parser.add_argument('--choose',action='store_true');parser.add_argument('--pause',action='store_true')
    args=parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:distribute(args.root,args.source,choose=args.choose)
    except KeyboardInterrupt:print('已取消；保留素材及分配进度。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
    finally:
        if args.pause:
            try:input('处理结束，按回车关闭窗口：')
            except (EOFError,KeyboardInterrupt):pass
