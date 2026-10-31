"""One explicitly authorized comment on the exact user-supplied fb06 reel URL.

Does not infer an MP4 mapping, upload media, or change publication status records.
"""
import hashlib
import json
import subprocess
import sys
import time
import traceback
import zipfile
from datetime import datetime,timezone
from pathlib import Path

LINK='https://www.facebook.com/reel/1009711495487891'
PAIR=('fb06','page01')
OWNER='https://www.facebook.com/profile.php?id=61595024560435'
TEXT='Get your own copy:\nhttps://www.amazon.com/s?maas=maas_adg_B87EF70D0CB3092D4D7277407B28F038_afap_abs&ref_=aa_maas&tag=maas&me=AEFRCMPTGXRXD&marketplaceID=ATVPDKIKX0DER'


def send_one(root,output_dir=None,open_result=True,verify_timeout_ms=30000):
    sys.path.insert(0,str(root))
    import fb_upload as upload
    import safe_video_comments as comments
    from add_fb_accounts import locked,find_chrome
    from diagnose_personal_identity import close_selected_window
    from playwright.sync_api import sync_playwright
    if upload.ROOT.resolve()!=Path(root).resolve():raise ValueError('上传程序目录不一致')
    if upload.VERSION not in {'2.42','2.43'} or getattr(comments,'COMMENT_WORKFLOW_VERSION','') not in {'1.1-url-dedup','1.2-future-reload','1.3-facebook-attribution'}:
        raise ValueError('需先安装配套的单条评论更新')
    key=hashlib.sha256(('direct-url-comment\0'+PAIR[0]+'\0'+PAIR[1]+'\0'+LINK).encode()).hexdigest()
    comment_key=hashlib.sha256((key+'\0'+comments.text_hash(TEXT)).encode()).hexdigest()
    started=datetime.now(timezone.utc).isoformat()
    folder=upload.ROOT/'logs'/('fb06-single-comment-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True)
    result=dict(account=PAIR[0],target=PAIR[1],permalink=LINK,text=TEXT,started_at=started,status='manual_required',error='',video_reuploaded=False)
    context=None;page=None;entry=None;record=None
    with locked():
        try:
            matches=[e for e in upload.read_json(upload.CONFIG,{}).get('targets',[]) if (e.get('account'),e.get('target'))==PAIR]
            if len(matches)!=1 or upload.target_key(matches[0]['url'])!=upload.target_key(OWNER):
                raise ValueError('fb06/page01 配置不是唯一的原公共主页，未选择其他身份')
            entry=dict(matches[0],auto_switch_personal=True)
            upload.validate_entry(entry)
            state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
            if any(r.get('account')==PAIR[0] and r.get('status') in {'preparing','posting'} for r in state.values()):
                raise ValueError('fb06 尚有准备中或提交中的视频任务，未关闭浏览器或发送评论')
            close_selected_window(PAIR[0])
            with sync_playwright() as playwright:
                context=upload.launch_context(playwright,entry)
                try:
                    pages=list(context.pages);page=pages[0] if pages else context.new_page();page.set_default_timeout(15000)
                    page.goto(upload.english_url(entry['url']),wait_until='domcontentloaded',timeout=30000)
                    proof=upload.ensure_identity(page,entry)
                    # This is a URL-bound comment receipt, not an assertion about an MP4 job.
                    record=dict(status='published',confirmation_method='user_supplied_published_video_url',permalink=LINK)
                    item=comments.after_publication(page,context,entry,proof,key,record,TEXT,None,
                        verified_link=(LINK,'user_supplied_exact_job_link'),require_reload_verification=True)
                    result.update(status=item['status'],error=item.get('error',''))
                    if item['status']=='manual_required' and '发送意图' in item.get('error',''):
                        result['status']='needs_review'
                    if item['status'] in {'sent','already_present','verifying'}:
                        try:
                            # Reload the exact video and check a server-rendered own comment.
                            page.goto(upload.english_url(LINK),wait_until='domcontentloaded',timeout=30000)
                            upload.checkpoint(page);upload.require_no_advanced_protection(page)
                            upload.recheck_publish_identity(page,entry,proof)
                            if not upload.page_actor_matches(page,entry):raise ValueError('刷新后评论身份未确认')
                            deadline=time.monotonic()+verify_timeout_ms/1000
                            expanded=False
                            while time.monotonic()<deadline:
                                if comments.scan_comments(page,entry,TEXT):break
                                if not expanded:
                                    comments.ready_comment_field(page,timeout_ms=5000);expanded=True
                                page.wait_for_timeout(500)
                            else:raise ValueError('刷新后未再次看到本人规定评论，需手动核实，未再次发送')
                            ledger_path=upload.ROOT/'logs/video_comments.json';ledger=upload.read_json(ledger_path,{})
                            verified=ledger.get(comment_key,dict(item))
                            verified.update(status='already_present' if item['status']=='already_present' else 'sent',
                                verification='own_comment_seen_after_reload',verified_at=datetime.now(timezone.utc).isoformat())
                            ledger[comment_key]=verified;upload.save_json(ledger_path,ledger)
                            result.update(status=verified['status'],verification=verified['verification'],error='')
                        except Exception as error:
                            ledger_path=upload.ROOT/'logs/video_comments.json';ledger=upload.read_json(ledger_path,{})
                            uncertain=ledger.get(comment_key,dict(item))
                            uncertain.update(status='needs_review',status_before_reload_check=item['status'],
                                error='发送后刷新核验未完成，勿重复发：'+(str(error) or type(error).__name__))
                            ledger[comment_key]=uncertain;upload.save_json(ledger_path,ledger)
                            result.update(status='needs_review',error=uncertain['error'])
                except Exception as error:
                    message=str(error) or type(error).__name__
                    result.update(error=message,status='needs_review' if '发送意图' in message else 'manual_required')
                    (folder/'error.txt').write_text(traceback.format_exc(),encoding='utf-8')
                finally:
                    if page is not None:
                        try:
                            if not page.locator('input[type=password]:visible').count():
                                page.screenshot(path=str(folder/'page.png'),timeout=10000)
                                (folder/'page.aria.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
                        except Exception:pass
                    try:context.close()
                    except Exception:pass
        except Exception as error:
            result.update(error=str(error) or type(error).__name__)
            (folder/'error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        finally:
            result['finished_at']=datetime.now(timezone.utc).isoformat()
            upload.save_json(folder/'result.json',result)
            out=Path(output_dir) if output_dir and Path(output_dir).is_dir() else upload.ROOT/'logs'
            archive=out/('fb06单条评论结果-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
                for file in folder.iterdir():
                    if file.is_file():z.write(file,file.name)
            print('单条评论结果：',result['status'],result['error'],flush=True)
            print('结果包：',archive,flush=True)
            if result['status'] in {'sent','already_present'} and result.get('verification')=='own_comment_seen_after_reload':
                print('SUCCESS：刷新视频后，已确认本人规定评论实际存在。',flush=True)
            else:print('未确认评论成功；未再次发送，请保留结果包核实。',flush=True)
    if open_result and entry:
        try:
            subprocess.Popen([str(find_chrome()),'--user-data-dir='+str(upload.ROOT/'profiles'/PAIR[0]),
                '--profile-directory=Default','--new-window',upload.english_url(LINK)],cwd=str(upload.ROOT))
        except Exception:pass
    return 0 if result['status'] in {'sent','already_present'} and result.get('verification')=='own_comment_seen_after_reload' else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    root=Path(sys.argv[1]);output=Path(sys.argv[2]) if len(sys.argv)>2 else None
    raise SystemExit(send_one(root,output))
