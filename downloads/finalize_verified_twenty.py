"""Apply the user's verified October 26 results, then retry only fb15/fb17."""
import argparse
import copy
import re
import sys
from datetime import datetime

import confirm_selected_round as confirmed
import fb_upload as upload
import publication_status as status
import publish_available_today as available
import retry_current_verified_absent as absent
from add_fb_accounts import locked
from diagnose_personal_identity import close_selected_window
from retry_failed_with_switch import load_bound_round

ORIGINAL_START='2026-10-26T17:53:46'
EXPANDED='available-today-20261026-182238-604193.json'
DATE='2026-10-26'
VERIFICATION='user-20261027-only-fb15-fb17-absent'
ORIGINAL_SUCCESS=tuple((f'fb{n:02d}','personal' if n in {3,4,7,8,9,10,11} else 'page01') for n in range(1,14))
NEW_SUCCESS=tuple((f'fb{n:02d}','personal') for n in (14,19,20,22,23))
RETRY=(('fb15','personal'),('fb17','personal'))


def stamp():
    return datetime.now().astimezone().isoformat()


def one_source(report,pair):
    rows=[row for row in report['rows'] if (row.get('account'),row.get('target'))==pair]
    if len(rows)!=1:
        raise ValueError('原报告没有唯一的指定视频：'+'/'.join(pair))
    row=rows[0]
    if not isinstance(row.get('key'),str) or not re.fullmatch(r'[a-f0-9]{64}',row['key']):
        raise ValueError('原报告没有确切视频指纹')
    upload.validate_video_filename(row.get('filename'))
    return row


def preflight():
    original_path,original=load_bound_round(ORIGINAL_START)
    path,source=confirmed.load_expanded_report(EXPANDED)
    # The expanded driver reports every configured target, including no-new
    # rows. Validate the selected material without requiring a seven-row file.
    for pair in NEW_SUCCESS+RETRY:
        one_source(source,pair)
    config=upload.read_json(upload.CONFIG,{})
    state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
    confirmed.confirmation_plan(config,state,original,ORIGINAL_SUCCESS)
    confirmed.confirmation_plan(config,state,source,NEW_SUCCESS,allow_unrecorded=True)
    common=(upload.ROOT/'common_caption_today.txt').read_text(encoding='utf-8-sig').strip()
    if source['caption_text'].strip()!=common or source['ai_label']!='off':
        raise ValueError('原文案或实拍不含 AI 的原批次设置不一致')
    return path,source


def save_attempt(result):
    with locked():
        path,source=confirmed.load_expanded_report(EXPANDED)
        source.setdefault('resume_results',[]).append(result)
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        if result.get('key') not in state and not result.get('error'):
            prior=[item for item in source['resume_results'][:-1] if item.get('key')==result.get('key') and item.get('error')]
            if prior:
                result.update(status='needs_check',error=prior[-1]['error'])
        available.save_report(path,source,source['rows'],source.get('results',[])+source['resume_results'],
                              state,update_results=False)


def retry_once(pair,close_windows=False):
    """Consume this fresh absence assertion once a new ledger task exists.

    The outer claim also covers unrecorded preparation jobs. Without it, a
    second invocation could incorrectly apply the old absence assertion to a
    newly unknown result created by the first preparation/publication attempt.
    """
    claims_path=upload.ROOT/'logs/verified-twenty-user-check.json'
    state_path=upload.ROOT/'logs/publish_state.json'
    with locked():
        path,source=confirmed.load_expanded_report(EXPANDED)
        row=one_source(source,pair)
        key=row['key']
        state=upload.read_json(state_path,{})
        claims=upload.read_json(claims_path,{})
        claim_id=path.name+':'+key+':'+VERIFICATION
        claim=claims.get(claim_id)
        if claim and claim.get('phase')=='reserved':
            saved=claim.get('original_record')
            if state.get(key)==saved or key not in state:
                if saved is not None and key not in state:
                    state[key]=copy.deepcopy(saved)
                    upload.save_json(state_path,state)
                claim['phase']='not_started'
            else:
                claim['phase']='consumed'
            upload.save_json(claims_path,claims)
        if claim and claim.get('phase')!='not_started':
            print('本次人工核实已用于此视频，保留新结果，不再次补发：','/'.join(pair),flush=True)
            return False
        old=state.get(key)
        if old and old.get('status')=='published':
            print('视频已有成功记录，不重发：','/'.join(pair),flush=True)
            return False
        entries=[e for e in upload.read_json(upload.CONFIG,{})['targets'] if
                 (e.get('account'),e.get('target'))==pair]
        if len(entries)!=1:
            raise ValueError('目标配置缺失或重复')
        entry=entries[0]
        upload.validate_entry(entry)
        if upload.target_key(row.get('url',''))!=upload.target_key(entry['url']):
            raise ValueError('原报告与当前目标网址不一致')
        validation=copy.deepcopy(state)
        if old is not None:
            absent.validate_record(entry,row,old)
            del validation[key]
        selected=upload.named_job(entry,validation,row['filename'])
        common=(upload.ROOT/'common_caption_today.txt').read_text(encoding='utf-8-sig').strip()
        if (not selected or selected[0]!=key or selected[3]!=source['caption_text'].strip()
                or common!=source['caption_text'].strip() or source['ai_label']!='off'):
            raise ValueError('原视频、文案或 AI 设置发生变化，未选择其他素材')
        backup=upload.ROOT/'backups'/('verified-two-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True)
        for original in (state_path,claims_path,upload.CONFIG,path):
            if original.is_file():
                (backup/original.name).write_bytes(original.read_bytes())
        claims[claim_id]=dict(phase='reserved',original_record=copy.deepcopy(old),asserted_at=stamp(),
            source_report=path.name,key=key,account=pair[0],target=pair[1],backup=str(backup))
        upload.save_json(claims_path,claims)
    try:
        if close_windows:
            with locked():
                close_selected_window(pair[0])
        if old is None:
            return available.run(True,'off',True,False,[pair],EXPANDED)==0
        return absent.retry_one(pair,path,source,True,confirmation_id=VERIFICATION)
    finally:
        with locked():
            actual=upload.read_json(state_path,{})
            claims=upload.read_json(claims_path,{})
            claim=claims[claim_id]
            if key not in actual:
                if old is not None:
                    actual[key]=old
                    upload.save_json(state_path,actual)
                claim['phase']='not_started'
            elif actual[key]==old:
                claim['phase']='not_started'
            else:
                claim.update(phase='consumed',status=actual[key].get('status'),completed_at=stamp())
            upload.save_json(claims_path,claims)


def run(publish=False,verified=False,close_windows=False):
    if publish and not verified:
        raise ValueError('实际执行需 --verified-results，表示用户已核实只有 fb15/fb17 未发布，其余原视频均已发布')
    with locked():
        preflight()
    print('人工核实范围：原批次 18 个视频已发布，仅 fb15/personal、fb17/personal 未发布。',flush=True)
    if not publish:
        print('只检查范围；未改变记录、归档或发布。',flush=True)
        return 0
    confirmed.confirm(ORIGINAL_START,ORIGINAL_SUCCESS,True)
    confirmed.confirm(None,NEW_SUCCESS,True,source_report=EXPANDED,allow_unrecorded=True)
    for pair in RETRY:
        with locked():
            _,source=confirmed.load_expanded_report(EXPANDED)
            row=one_source(source,pair)
        result=dict(account=pair[0],target=pair[1],key=row['key'],filename=row['filename'],
                    attempted_at=stamp(),user_verified_absent=True,verification_id=VERIFICATION)
        try:
            result['attempt']='finished' if retry_once(pair,close_windows) else 'skipped_or_unconfirmed'
        except Exception as error:
            result.update(attempt='needs_check',status='needs_check',error=str(error).splitlines()[0][:500])
            print('此目标保留记录，继续下一个：','/'.join(pair),result['error'],flush=True)
        finally:
            save_attempt(result)
    with locked():
        report=status.collect(DATE)
        output=status.save(report)
        print('\n原批次最新结果：',report['counts'],flush=True)
        for row in report['rows']:
            if (row['account'],row['target']) in RETRY:
                print(row['account']+'/'+row['target'],row['filename'],row['label'],row['reason'],flush=True)
        print('最新汇总：',output.with_suffix('.csv'),flush=True)
        print('原已确认成功的 18 条没有重发；新补发若仍未知，需重新查看实际视频。',flush=True)
        selected=[row for row in report['rows'] if (row['account'],row['target']) in RETRY]
        return 0 if len(selected)==2 and not report['issues'] and all(row['status']=='published' for row in selected) else 3


def main():
    parser=argparse.ArgumentParser(description='补记用户已确认的 18 个原视频，只补发已核实未发布的 fb15/fb17')
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--verified-results',action='store_true')
    parser.add_argument('--close-windows',action='store_true')
    args=parser.parse_args()
    return run(args.run,args.verified_results,args.close_windows)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('已中断；保留任务和一次性人工核实记录，请先检查结果。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',str(error).splitlines()[0],flush=True)
        raise SystemExit(1)
