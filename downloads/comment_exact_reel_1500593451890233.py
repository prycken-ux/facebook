"""One authorized comment via the user's exact Reel URL; never search the timeline."""
import ast,copy,hashlib,re,shutil,ssl,sys,urllib.request,uuid
from datetime import datetime,timezone
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import safe_video_comments as comments
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

PAIR=('fb10','page02')
NAME='Drascreflo Chajundfro'
OWNER='https://www.facebook.com/profile.php?id=61595204068114'
LINK='https://www.facebook.com/reel/1500593451890233'
FILENAME='新脚本_20261101-181104.mp4'
PREFIX='f6cc163c'


def load_target():
    matches=[e for e in upload.read_json(upload.CONFIG,{}).get('targets',[]) if (e.get('account'),e.get('target'))==PAIR]
    if (len(matches)!=1 or upload.target_key(matches[0]['url'])!=upload.target_key(OWNER)
            or comments.normalized(matches[0].get('name','')).casefold()!=NAME.casefold()):
        raise ValueError('fb10/page02不是唯一的Drascreflo Chajundfro目标，未改选其他身份')
    entry=dict(matches[0],auto_switch_personal=True);upload.validate_entry(entry)
    paths=[p for p in (upload.ROOT/'logs').glob('frozen-material-2026-11-02-'+PREFIX+'*.json')
           if re.fullmatch(r'frozen-material-2026-11-02-[a-f0-9]{16}\.json',p.name)]
    if len(paths)!=1:raise ValueError('没有唯一11月2日f6cc163c原清单')
    source=paths[0];value=upload.read_json(source,{});payload=value.get('payload',{});checksum=batch.digest(payload)
    if (value.get('sha256')!=checksum or not checksum.startswith(PREFIX) or not source.stem.endswith(checksum[:16])
            or payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-11-02'
            or payload.get('comment_text')!=daily.COMMENT or len(payload.get('jobs',[]))!=30 or value.get('report_format')!='text'):
        raise ValueError('原视频清单或授权评论校验失败')
    jobs=[j for j in payload['jobs'] if (j.get('account'),j.get('target'))==PAIR and j.get('filename')==FILENAME]
    if len(jobs)!=1 or upload.target_key(jobs[0]['url'])!=upload.target_key(OWNER):raise ValueError('原视频与目标不一致')
    job=jobs[0];state=upload.read_json(upload.ROOT/'logs/publish_state.json',{});row=state.get(job['key'])
    if (not isinstance(row,dict) or (row.get('account'),row.get('target'))!=PAIR or row.get('status')!='published'
            or upload.target_key(row.get('url',''))!=upload.target_key(OWNER)
            or str(row.get('video','')).replace('\\','/').split('/')[-1]!=FILENAME):
        raise ValueError('原fb10/page02视频没有对应的已成功记录，未创建或上传视频')
    return source,value,job,entry,state


def write_result(result,source=None,value=None):
    path=upload.ROOT/'logs'/'fb10-page02-direct-comment-1500593451890233.json';upload.save_json(path,result)
    if source is not None:
        prior=upload.read_json(source.with_name(source.stem+'-results.json'),{})
        if prior.get('manifest')==source.name and isinstance(prior.get('attempts'),list):batch.results(source,value,prior['attempts'],None,final=False)
    names={'sent':'评论已刷新确认成功','already_present':'已有规定评论，未重复发送','needs_review':'评论结果待核实，未重复发送','manual_required':'评论未完成'}
    print('\nfb10/page02 '+NAME,flush=True);print('视频：'+LINK,flush=True)
    print('结果：'+names.get(result['status'],result['status'])+('；'+result['error'] if result.get('error') else ''),flush=True)
    print('本次未上传视频，未搜索主页动态，未处理其他视频。',flush=True)


def execute(verify_timeout_ms=30000):
    from playwright.sync_api import sync_playwright
    if upload.VERSION!='2.47':raise ValueError('本条直达补评使用当前核心2.47，未改装程序')
    if datetime.now(timezone.utc).astimezone(batch.BJ).date().isoformat()!='2026-11-03':raise ValueError('此单条评论仅限北京时间11月3日')
    result=dict(account=PAIR[0],target=PAIR[1],permalink=LINK,status='manual_required',error='',video_reuploaded=False)
    state_path=upload.ROOT/'logs/publish_state.json'
    with locked(),daily.keep_awake():
        source,value,job,entry,state=load_target();row=state[job['key']]
        ledger_path=upload.ROOT/'logs/video_comments.json';ledger=upload.read_json(ledger_path,{})
        key=hashlib.sha256((job['key']+'\0'+comments.text_hash(daily.COMMENT)).encode()).hexdigest();prior=ledger.get(key,{})
        if prior.get('status') in {'sent','already_present','sending','verifying','needs_review'} or row.get('comment_status') in {'sent','already_present','sending','verifying','needs_review'}:
            same=comments.direct_link(prior.get('permalink',''))==LINK
            known=prior.get('status') in {'sent','already_present'} and prior.get('verification')=='own_comment_seen_after_reload'
            result.update(status='already_present' if same and known else 'needs_review',error='' if same and known else '已有发送记录或待核实结果，保留原记录，不重复发送')
            write_result(result,source,value);return 0 if same and known else 3
        if any(r.get('account')==PAIR[0] and r.get('status') in {'preparing','posting'} for r in state.values()):raise ValueError('fb10另有准备或提交中的任务，未关闭其浏览器')
        backup=upload.ROOT/'backups'/('fb10-page02-direct-comment-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8]);backup.mkdir(parents=True)
        for path in (state_path,ledger_path,source.with_name(source.stem+'-results.json')):
            if path.is_file():shutil.copy2(path,backup/path.name)
        page=None
        try:
            close_selected_window(PAIR[0])
            with sync_playwright() as playwright:
                context=upload.launch_context(playwright,entry)
                try:
                    identity=context.new_page();identity.set_default_timeout(15000)
                    # Profile header is for actor switching only; no post list or search is used.
                    identity.goto(upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000)
                    proof=upload.ensure_identity(identity,entry)
                    page=context.new_page();page.set_default_timeout(15000)
                    page.goto(upload.english_url(LINK),wait_until='domcontentloaded',timeout=30000)
                    upload.checkpoint(page);upload.require_no_advanced_protection(page)
                    if comments.direct_link(page.url)!=LINK:raise ValueError('直达链接跳转到不同视频，未发送')
                    comments.require_video_author(page,entry)
                    upload.recheck_publish_identity(page,entry,proof)
                    row.update(permalink=LINK,comment_link_job_key=job['key'],comment_link_method='user_supplied_exact_job_link')
                    upload.save_json(state_path,state)
                    print('直接给用户指定的视频发送规定评论：fb10/page02 '+LINK,flush=True)
                    item=comments.after_publication(page,context,entry,proof,job['key'],row,daily.COMMENT,None,
                        verified_link=(LINK,'user_supplied_exact_job_link'),require_reload_verification=True)
                    item=comments.verify_after_reload(page,entry,proof,job['key'],daily.COMMENT,item,timeout_ms=verify_timeout_ms)
                    row.update(comment_status=item['status'],comment_error=item.get('error',''));upload.save_json(state_path,state)
                    result.update(status=item['status'],error=item.get('error',''),verification=item.get('verification',''))
                except Exception as error:
                    if page is not None:comments.capture_failure(page,job['key'],error)
                    raise
                finally:
                    try:context.close()
                    except Exception as error:print('本次评论窗口关闭需检查：',str(error).split('\n',1)[0],flush=True)
        except KeyboardInterrupt:raise
        except Exception as error:
            current=upload.read_json(ledger_path,{}).get(key,{})
            status=current.get('status') if current.get('status') in {'sending','verifying','needs_review'} else 'manual_required'
            result.update(status=status,error=(str(error) or type(error).__name__).split('\n',1)[0][:1200])
            latest=upload.read_json(state_path,{})
            if latest.get(job['key'],{}).get('status')=='published':
                latest[job['key']].update(comment_status=status,comment_error=result['error']);upload.save_json(state_path,latest)
        write_result(result,source,value)
    return 0 if result['status'] in {'sent','already_present'} and result.get('verification')=='own_comment_seen_after_reload' else 3


def recover_locks(root):
    context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
    expected='2d6b7913bbbce473b4beaf2739700231be9ce9bb30ba2526021023c93d80a3c3'
    for base in ('https://raw.githubusercontent.com/prycken-ux/facebook/','https://github.com/prycken-ux/facebook/raw/'):
        try:
            url=base+'d8c998c705801c948a230c0504fcb65653ae8086/downloads/recover_resume_new_batch.py'
            with urllib.request.urlopen(url,context=context,timeout=25) as response:data=response.read(131073)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Lock helper checksum mismatch')
            ast.parse(data.decode('utf-8-sig'));break
        except Exception as error:print('Download failed:',str(error).split('\n',1)[0],flush=True)
    else:raise RuntimeError('锁核验组件下载失败，未启动评论')
    namespace={'__name__':'verified_lock_cleanup_library','__file__':'verified_lock_cleanup.py'}
    exec(compile(data,'verified-lock-cleanup','exec'),namespace);namespace['recover_locks'](root)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        root=Path(sys.argv[1]).resolve()
        if sys.platform!='win32' or upload.ROOT.resolve()!=root:raise ValueError('请在原Windows上传电脑运行')
        recover_locks(root);raise SystemExit(execute())
    except KeyboardInterrupt:print('已停止，保留发送记录，不要清空后重复发送。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
