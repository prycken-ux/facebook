"""Import the exact Nov14 staged first24 originals and publish only that batch."""
import importlib.util,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import publish_distributed_nov13_first24 as first
import diagnose_login_and_resume_fifteen_nov14 as guided

DAY='2026-11-14'
SOURCE_ID='ee49926eedf51de8'
STAGE=Path('material-staging')/DAY/(SOURCE_ID+'-existing24')/'manifest.json'
SCOPE='nov14-staged-first24-ee49926eedf51de8-new-real-footage-v1'
POINTER='nov14-staged-first24-ee49926eedf51de8-publication.json'
PAUSED={'fb17'}
ALLOWED={f'fb{n:02d}' for n in range(1,25)}-PAUSED
EXPECTED={(f'fb{n:02d}','page01' if n in {1,2,5,6,12,13} else 'personal') for n in range(1,25)}|{(a,f'page{n:02d}') for a in ('fb09','fb10') for n in range(1,11)}
PAGE_ROUTE_VERSION='1.0-owned-picker-after-home-redirect'
RUN=first.execute
DISTRIBUTION=first.distribution
NUMERIC=first.numeric.ensure
PERSONAL=first.personals.ensure_personal


def sibling(name):
    path=Path(__file__).resolve().with_name(name)
    spec=importlib.util.spec_from_file_location('_nov14_'+path.stem,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


stage=sibling('stage_next_materials_20261114_v1.py')
lock_recovery=sibling('verified_publication_lock_recovery.py')


def require_day():
    if datetime.now(timezone.utc).astimezone(first.batch.BJ).date().isoformat()!=DAY:raise ValueError('此指令只授权11月14日发布本批已暂存的新视频。')


def allow_launcher_workers():
    # The verified parent only installs this immutable package and waits for us.
    # Other existing publication workers, including the old46 runner, still block.
    script=stage.WORKERS.replace('stage_next_materials_20261114_v1|','start_publish_staged_first24_nov14|stage_next_materials_20261114_v1|')
    return patch.object(stage,'WORKERS',script)


def checked_stage():
    path,value=stage.validate_stage(first.upload.ROOT,first.upload.ROOT/STAGE);payload=value['payload'];d=payload['distribution']['payload']
    pairs={(r['account'],r['target']) for r in d['assignments']}
    if (payload.get('date')!=DAY or payload.get('source_id')!=SOURCE_ID or d.get('target_scope')!='existing24'
            or len(d['assignments'])!=44 or pairs!=EXPECTED):raise ValueError('不是刚才这44条fb01–fb24及公共主页的新素材清单，未猜选其他批次。')
    return path,value


def wait_previous():
    while True:
        require_day();workers=stage.active_workers(first.upload.ROOT)
        if not workers:return
        print('上一批任务仍在运行，先保留本批暂存视频；等待其视频、评论及登录检查全部结束。任务PID：',','.join(str(r['pid']) for r in workers),'；15秒后再检查。',flush=True)
        time.sleep(15)


def page_identity(page,entry,timeout_ms=15000,interactive=False):
    if entry.get('type')!='page':return NUMERIC(page,entry,timeout_ms=timeout_ms,interactive=False)
    first.upload.checkpoint(page);first.upload.require_no_advanced_protection(page)
    expected=first.upload.target_key(entry['url'])
    if not expected.startswith('id:'):return NUMERIC(page,entry,timeout_ms=timeout_ms,interactive=False)
    try:current=first.upload.target_key(page.url)
    except ValueError:
        parsed=urlparse(page.url)
        if (parsed.scheme!='https' or parsed.hostname not in {'facebook.com','www.facebook.com'} or parsed.username or parsed.password or parsed.port
                or parsed.path not in {'','/','/home.php'}):raise
        current=None
    if current is None:
        marker=first.numeric.picker.login_marker(page);deadline=time.monotonic()+timeout_ms/1000
        try:actor=first.upload.page_actor_matches(page,entry)
        except RuntimeError:actor=False
        if not actor:
            print('目标主页打开后返回Facebook首页；先从已登记主页列表切换，再按数字ID核验。',entry['account'],entry['target'],flush=True)
            first.numeric.picker.select_configured_profile(page,entry,marker,deadline)
            while True:
                first.upload.checkpoint(page);first.upload.require_no_advanced_protection(page)
                if first.numeric.picker.login_marker(page)!=marker:raise RuntimeError('切换主页期间登录者变化，未选择视频。')
                try:actor=first.upload.page_actor_matches(page,entry)
                except RuntimeError:actor=False
                if actor and first.numeric.picker.picker_dialog(page) is None:break
                if time.monotonic()>=deadline:raise RuntimeError('目标公共主页数字身份仍未匹配，未选择视频。')
                page.wait_for_timeout(150)
        first.upload.navigate_profile(page,entry['url'])
        first.upload.checkpoint(page)
        if first.numeric.picker.login_marker(page)!=marker or not first.upload.page_actor_matches(page,entry):raise RuntimeError('返回目标主页后数字身份变化，未选择视频。')
        if first.upload.target_key(page.url)!=expected:raise RuntimeError('身份切换后仍未打开原登记目标主页，未选择视频。')
    return NUMERIC(page,entry,timeout_ms=timeout_ms,interactive=False)


def protect_other_materials():
    # Nothing else in existing inboxes is selected, moved or used as a fallback.
    return {str(path).casefold() for path in (first.upload.ROOT/'videos').glob('fb*/*/inbox/*.mp4') if path.is_file()}


def execute(real_footage):
    if not real_footage:raise ValueError('本批44条新素材尚未确认全部实拍，未导入或发布。')
    require_day();first.workflow.require_versions();stage.setup(first.upload.ROOT)
    path,value=checked_stage();material=value['payload']['distribution']
    content=first.batch.preferences.content_policy(DAY)
    if not content or content['payload']['caption']!=first.batch.preferences.EVERYDAY_CAPTION or content['payload']['comment']!=first.batch.preferences.EVERYDAY_COMMENT:raise ValueError('现有正文和评论不是之前确认的版本，未擅自替换。')
    with allow_launcher_workers():
        wait_previous()
        lock_recovery.recover_locks(first.upload.ROOT)
        stage.import_stage(first.upload.ROOT,path)
    journal=first.upload.ROOT/'logs/material-distribution'/SOURCE_ID/(DAY+'.json')
    def bound(relative=None):
        if relative is not None and (first.upload.ROOT/relative).resolve()!=journal.resolve():raise ValueError('本批只接受刚才导入的44条清单。')
        result=DISTRIBUTION(str(journal.relative_to(first.upload.ROOT)))
        if result[1]['sha256']!=material['sha256']:raise ValueError('本批原分配指纹变化，未选择其他视频。')
        return result
    print('开始11月14日新素材：分配44条；fb17按此前要求暂跳过并保留原文件，其余43个目标依次发布、一次安全补发，再评论及核验。',flush=True)
    print('本批全部实拍，AI标签关闭；沿用原正文、Amazon和Shopfy评论。fb25及以后、本批之外旧视频和旧评论不进入队列。',flush=True)
    with patch.object(first,'DAY',DAY),patch.object(first,'MATERIAL_DAY',DAY),patch.object(first,'SCOPE',SCOPE),patch.object(first,'POINTER',POINTER), \
         patch.object(first,'ALLOWED',ALLOWED),patch.object(first,'WAVE_LABEL','新素材批次'),patch.object(first,'WAVE_DESCRIPTION','fb01–fb24及公共主页（fb17暂跳过）'), \
         patch.object(first,'distribution',side_effect=bound),patch.object(first.archive,'today_files',side_effect=protect_other_materials), \
         patch.object(first,'pause_archived_history',return_value=None),patch.object(first.numeric,'ensure',side_effect=page_identity), \
         patch.object(first.personals,'ensure_personal',side_effect=lambda page,entry:guided.base.ensure_background_identity(PERSONAL,page,entry)):
        result=RUN(True)
    print('本批新素材处理结束；fb17素材仍保留，旧批次成功及待核实记录均未重发。',flush=True)
    return result


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if first.upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传电脑目录运行。')
        raise SystemExit(execute('--real-footage' in sys.argv[2:]))
    except KeyboardInterrupt:print('已暂停，保留导入、发布和评论记录；重跑同一指令继续本批，已提交视频不重发。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
