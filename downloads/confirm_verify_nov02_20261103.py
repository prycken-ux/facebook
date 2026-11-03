"""Record the user's Nov-2 confirmations, then verify only fb10/page07 and page08."""
import ast,copy,hashlib,re,shutil,ssl,sys,urllib.request,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import fb_upload as upload
import scheduled_material_batch as batch
import daily_publish_and_comments as daily
import safe_video_comments as comments
import published_video_lookup as lookup
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window

PREFIX='f6cc163c'
USER_CONFIRMED={
 ('fb07','personal'):'97f5f98b98e8',
 ('fb03','personal'):'aec6e81aeb5e', ('fb05','page01'):'27a09f06a816', ('fb10','page01'):'66d690b685fd',
 ('fb08','personal'):'a4b07c959620', ('fb10','personal'):'039dcaacb422', ('fb11','personal'):'03b90f9f7c29',
 ('fb14','personal'):'f35b8f43507b', ('fb15','personal'):'61bad5a4816b', ('fb17','personal'):'def02221852e',
 ('fb19','personal'):'8538aaccdead', ('fb20','personal'):'dae0a9829354', ('fb22','personal'):'219df014e5a9',
}
VERIFY={('fb10','page07'):'8ae46e51b98e',('fb10','page08'):'32a7138d90cb'}
USER_METHOD='user_confirmed_nov02_published_20261103'
ONLINE_METHOD='verified_nov02_owner_caption_time_video_20261103'


def load_source():
    paths=[p for p in (upload.ROOT/'logs').glob('frozen-material-2026-11-02-'+PREFIX+'*.json')
           if re.fullmatch(r'frozen-material-2026-11-02-[a-f0-9]{16}\.json',p.name)]
    if len(paths)!=1:raise ValueError('没有唯一的11月2日f6cc163c原清单，未改选31号或今天批次')
    path=paths[0];value=upload.read_json(path,{});payload=value.get('payload',{});checksum=batch.digest(payload)
    if (value.get('sha256')!=checksum or not checksum.startswith(PREFIX) or not path.stem.endswith(checksum[:16])
            or payload.get('schema')!=batch.SCHEMA or payload.get('date')!='2026-11-02'
            or len(payload.get('jobs',[]))!=30 or value.get('report_format')!='text'):raise ValueError('11月2日原30条文字结果清单校验失败')
    original=upload.read_json(path.with_name(path.stem+'-results.json'),{})
    if original.get('manifest')!=path.name or not isinstance(original.get('attempts'),list):
        raise ValueError('原批次结果或尝试记录不匹配，未覆盖其他报告')
    selected={}
    for pair,prefix in list(USER_CONFIRMED.items())+list(VERIFY.items()):
        jobs=[j for j in payload['jobs'] if (j.get('account'),j.get('target'))==pair
              and re.fullmatch(r'[a-f0-9]{64}',str(j.get('key',''))) and j['key'].startswith(prefix)]
        if len(jobs)!=1:raise ValueError('原任务匹配不唯一：'+'/'.join(pair))
        selected[pair]=copy.deepcopy(jobs[0])
    return path,value,selected


def record_for(job,state):
    row=state.get(job['key'])
    if (not isinstance(row,dict) or (row.get('account'),row.get('target'))!=(job['account'],job['target'])
            or upload.target_key(row.get('url',''))!=upload.target_key(job['url'])
            or str(row.get('video','')).replace('\\','/').split('/')[-1]!=job['filename']):
        raise ValueError('当前记录与11月2日指定原视频不一致')
    if row.get('status') not in {'needs_review','published'}:
        raise ValueError('当前任务不是待核实或已成功状态，未改动其他处理阶段')
    return row


def publication_window(row):
    posted=datetime.fromisoformat(row['post_intent_at'])
    created=datetime.fromisoformat(row['created'])
    if posted.tzinfo is None or created.tzinfo is None or created>posted:
        raise ValueError('原任务缺少可信的创建/提交时间，未扩大到其他日期')
    return created.timestamp()-60,(posted+timedelta(minutes=30)).timestamp()


def mark(state,job,source,method,audit,link=None,link_method=None):
    row=record_for(job,state)
    if row.get('status')=='published':return False
    start,end=publication_window(row)
    if link is not None and comments.direct_link(link)!=link:raise ValueError('线上核验不是规范视频链接')
    before=copy.deepcopy(row)
    row.update(status='published',confirmation_method=method,confirmed_at=datetime.now(timezone.utc).isoformat(),
        confirmed_source_manifest=source.name,
        confirmed_batch_lookup_cutoff=datetime.fromtimestamp(end,timezone.utc).isoformat(),error='')
    row.pop('review_reason',None)
    if link is not None:
        row.update(permalink=link,comment_link_job_key=job['key'],comment_link_method=link_method)
    audit.append(dict(account=job['account'],target=job['target'],key=job['key'],method=method,
        prior_record=before,verified_link=link))
    return True


def online_verify(page,context,entry,job,row):
    start,end=publication_window(row)
    link,method=lookup.find_published(page,context,entry,job['caption_text'],start,end,timeout_ms=45000,
        diagnostic_path=upload.ROOT/'logs'/('verify-nov02-'+job['key'][:12]+'-lookup.json'))
    page.goto(upload.english_url(link),wait_until='domcontentloaded',timeout=30000)
    upload.checkpoint(page);upload.require_no_advanced_protection(page)
    if comments.direct_link(page.url)!=link:raise ValueError('视频页跳转到不同视频，保留待核实')
    comments.require_video_author(page,entry)
    return link,method


def summary(source,value,results,audit,backup):
    prior=upload.read_json(source.with_name(source.stem+'-results.json'),{})
    if prior.get('manifest')!=source.name:raise ValueError('原结果报告变化，未覆盖')
    batch.results(source,value,prior['attempts'],None,final=False)
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    counts={}
    for job in value['payload']['jobs']:
        status=state.get(job['key'],{}).get('status','not_started');counts[status]=counts.get(status,0)+1
    print('\n11月2日批次当前结果：成功',counts.get('published',0),'；发布前失败',counts.get('failed_before_post',0),
          '；待核实',sum(counts.get(k,0) for k in ('needs_review','posting','preparing')),'；未开始',counts.get('not_started',0),flush=True)
    for result in results:print(result,flush=True)
    print('本次没有上传、补发或发送评论。用户确认与线上核验使用不同的确认来源。',flush=True)
    upload.save_json(backup/'confirmation-audit.json',dict(source_manifest=source.name,changes=audit,results=results,counts=counts))


def execute():
    from playwright.sync_api import sync_playwright
    if upload.VERSION!='2.47' or getattr(lookup,'LOOKUP_WORKFLOW_VERSION','')!='1.1-reels-tabs':
        raise ValueError('需使用当前已安装核心2.47及定位1.1，未安装或覆盖任何程序')
    state_path=upload.ROOT/'logs/publish_state.json';results=[];audit=[]
    with locked(),daily.keep_awake():
        source,value,jobs=load_source();state=upload.read_json(state_path,{})
        backup=upload.ROOT/'backups'/('confirm-nov02-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8])
        backup.mkdir(parents=True);upload.save_json(backup/'publish_state.json',state)
        for prior in (source,source.with_name(source.stem+'-results.json'),source.with_name(source.stem+'-results.txt'),
                      upload.ROOT/'logs'/('今日定时发布与评论-2026-11-02-'+value['sha256'][:8]+'.zip')):
            if prior.is_file():shutil.copy2(prior,backup/prior.name)
        for pair in USER_CONFIRMED:
            job=jobs[pair]
            try:
                daily.configured(job)
                changed=mark(state,job,source,USER_METHOD,audit)
                results.append('/'.join(pair)+('：已按用户确认补记成功' if changed else '：原记录已成功，保留'))
            except Exception as error:results.append('/'.join(pair)+'：未改记录；'+str(error).split('\n',1)[0])
        if audit:
            upload.save_json(backup/'confirmation-audit.json',dict(source_manifest=source.name,changes=audit))
            upload.save_json(state_path,state)
        print('用户确认结果已补记；现在只核验 fb10/page07 和 page08，不补发。',flush=True)
        for pair in VERIFY:
            print('\n线上核验：','/'.join(pair),jobs[pair]['filename'],flush=True)
            context=None
            try:
                state=upload.read_json(state_path,{});job=jobs[pair];row=copy.deepcopy(record_for(job,state));entry=daily.configured(job)
                if row['status']=='published':results.append('/'.join(pair)+'：原记录已成功，未重复标记');continue
                if any(r.get('account')=='fb10' and r.get('status') in {'preparing','posting'} for r in state.values()):
                    raise ValueError('fb10另有准备或提交中的任务，未关闭窗口或核验')
                close_selected_window('fb10')
                with sync_playwright() as playwright:
                    context=upload.launch_context(playwright,entry)
                    try:
                        page=context.new_page();page.set_default_timeout(15000)
                        link,method=online_verify(page,context,entry,job,row)
                    finally:
                        try:context.close()
                        except Exception as error:print('本次核验窗口关闭需检查：',str(error).split('\n',1)[0],flush=True)
                        context=None
                current=upload.read_json(state_path,{})
                if current.get(job['key'])!=row:raise ValueError('核验期间原记录变化，未覆盖')
                mark(current,job,source,ONLINE_METHOD,audit,link,method)
                upload.save_json(backup/'confirmation-audit.json',dict(source_manifest=source.name,changes=audit))
                upload.save_json(state_path,current)
                results.append('/'.join(pair)+'：线上核验通过，已标记成功；'+link)
            except KeyboardInterrupt:raise
            except Exception as error:
                results.append('/'.join(pair)+'：仍待核实，未标记成功；'+(str(error) or type(error).__name__).split('\n',1)[0])
            print(results[-1],flush=True)
        summary(source,value,results,audit,backup)
    return results


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
    else:raise RuntimeError('锁核验组件下载失败，未改动发布记录')
    namespace={'__name__':'verified_lock_cleanup_library','__file__':'verified_lock_cleanup.py'}
    exec(compile(data,'verified-lock-cleanup','exec'),namespace);namespace['recover_locks'](root)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        root=Path(sys.argv[1]).resolve()
        if sys.platform!='win32' or upload.ROOT.resolve()!=root:raise ValueError('请在原Windows上传电脑运行')
        recover_locks(root);execute()
    except KeyboardInterrupt:print('已停止，已完成的确认保留；没有补发或评论。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
