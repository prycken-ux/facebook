"""Record the user's explicit confirmation of all 30 Nov-2 publications; no browser."""
import ast,copy,hashlib,re,shutil,ssl,sys,urllib.request,uuid
from datetime import datetime,timezone
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
from add_fb_accounts import locked

PREFIX='f6cc163c'
METHOD='user_confirmed_all_nov02_published_20261103'


def load_source():
    paths=[p for p in (upload.ROOT/'logs').glob('frozen-material-2026-11-02-'+PREFIX+'*.json')
           if re.fullmatch(r'frozen-material-2026-11-02-[a-f0-9]{16}\.json',p.name)]
    if len(paths)!=1:raise ValueError('没有唯一的11月2日原30条清单，未选择其他日期')
    source=paths[0];value=upload.read_json(source,{});payload=value.get('payload',{});checksum=batch.digest(payload)
    jobs=payload.get('jobs',[])
    if (value.get('sha256')!=checksum or not checksum.startswith(PREFIX) or not source.stem.endswith(checksum[:16])
            or payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-11-02'
            or value.get('report_format')!='text' or payload.get('comment_text')!=daily.COMMENT
            or set(payload.get('excluded_accounts',[]))!={'fb16','fb18','fb21'}
            or len(jobs)!=30 or {(j.get('account'),j.get('target')) for j in jobs}!=daily.EXPECTED_PAIRS
            or len({j.get('key') for j in jobs})!=30
            or any(not re.fullmatch(r'[a-f0-9]{64}',str(j.get('key',''))) for j in jobs)):
        raise ValueError('11月2日原清单指纹、范围或日期校验失败，未修改记录')
    report=upload.read_json(source.with_name(source.stem+'-results.json'),{})
    if report.get('manifest')!=source.name or not isinstance(report.get('attempts'),list):
        raise ValueError('原批次结果不匹配，未修改记录')
    return source,value,report


def plan_changes(source,value,state):
    if not isinstance(state,dict):raise ValueError('发布账本格式异常')
    updated=copy.deepcopy(state);changes=[];now=datetime.now(timezone.utc).isoformat()
    for job in value['payload']['jobs']:
        entry=daily.configured(job);upload.validate_video_filename(job['filename'])
        row=updated.get(job['key'])
        if job['key'] in updated:
            if (not isinstance(row,dict) or (row.get('account'),row.get('target'))!=(job['account'],job['target'])
                    or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
                    or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):
                raise ValueError('原任务身份或视频不匹配：'+job['account']+'/'+job['target'])
            if row.get('status')=='published':continue
        before=copy.deepcopy(row)
        if row is None:
            # This is a user-confirmed record, not a fabricated upload attempt.
            row=dict(account=job['account'],target=job['target'],url=job['url'],
                     video=str(upload.inbox_for(entry)/job['filename']),comment_status='not_started',
                     record_origin='user_confirmation_from_frozen_manifest')
            updated[job['key']]=row
        row.update(status='published',confirmation_method=METHOD,confirmed_at=now,
                   confirmed_source_manifest=source.name,published_caption_text=job['caption_text'],error='')
        row.setdefault('confirmed_batch_lookup_cutoff','2026-11-03T00:00:00+08:00')
        row.pop('review_reason',None)
        changes.append(dict(key=job['key'],account=job['account'],target=job['target'],
                            filename=job['filename'],prior_record=before,new_record=copy.deepcopy(row)))
    return updated,changes


def execute():
    with locked():
        source,value,prior=load_source();state_path=upload.ROOT/'logs/publish_state.json'
        original=upload.read_json(state_path,{})
        state,changes=plan_changes(source,value,original)
        backup=upload.ROOT/'backups'/('confirm-all-nov02-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8])
        backup.mkdir(parents=True)
        for path in (state_path,source,source.with_name(source.stem+'-results.json'),source.with_name(source.stem+'-results.txt'),
                     upload.ROOT/'logs'/('今日定时发布与评论-2026-11-02-'+value['sha256'][:8]+'.zip')):
            if path.is_file():shutil.copy2(path,backup/path.name)
        upload.save_json(backup/'confirmation-audit.json',dict(source_manifest=source.name,source_sha256=value['sha256'],
            confirmation_method=METHOD,scope='all_30_original_nov02_jobs',changes=changes,
            prior_state_present=state_path.exists(),comment_states_modified=False,video_upload_started=False))
        if upload.read_json(state_path,{})!=original:raise ValueError('记录在核对期间发生变化，未覆盖')
        if changes:upload.save_json(state_path,state)
        try:batch.results(source,value,prior['attempts'],None,final=False)
        except Exception:
            print('30条发布成功状态已保存；结果报告刷新未完成，可重跑本命令刷新。',flush=True)
            raise
        count=sum(state[j['key']]['status']=='published' for j in value['payload']['jobs'])
        if count!=30:raise RuntimeError('成功数量不符合原30条清单')
        print('11月2日原批次：发布成功30条，发布失败0条，待核实0条，尚未开始0条。',flush=True)
        print('本次按你的确认新标记',len(changes),'条；其余原记录已成功。确认来源：用户确认。',flush=True)
        print('评论结果保留原状态；本次没有上传、补发视频或发送评论。',flush=True)
        print('原记录和操作审计已备份：',backup,flush=True)
    return 0


def recover_locks():
    if not any((upload.ROOT/'logs'/name).exists() for name in ('batch.lock','upload.lock')):return
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    expected='2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3'
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            with urllib.request.urlopen(base+'d8c998c705801c948a230c0504fcb65653ae8086/downloads/recover_resume_new_batch.py',context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Lock helper checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));break
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    else:raise RuntimeError('锁核验组件下载失败，未修改记录')
    namespace={'__name__':'verified_lock_library','__file__':'verified_lock_library.py'}
    exec(compile(data,'verified-lock-library','exec'),namespace);namespace['recover_locks'](upload.ROOT)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if sys.platform!='win32' or upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原Windows上传电脑运行')
        recover_locks();raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止；保留已保存的成功标记及备份。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
