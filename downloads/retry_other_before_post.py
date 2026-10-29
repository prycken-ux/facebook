"""Retry only exact before-Post failures from a fixed other-account round."""
import argparse
import sys
from datetime import datetime

import confirm_selected_round as confirmations
import fb_upload as upload
import publish_fb10_pages_direct as direct
from add_fb_accounts import locked
from diagnose_personal_identity import parse_target_pairs
from retry_current_verified_absent import retry_one


def run(source_report,targets,close_windows=False):
    if not targets or len(set(targets))!=len(targets):
        raise ValueError('需提供明确、不重复的原批次目标')
    with locked():
        path,report=confirmations.load_expanded_report(source_report)
        if report['schema']!='other-accounts-direct-publication-v1':
            raise ValueError('只处理指定其他账号直接发布批次')
        bound=[]
        for pair in targets:
            rows=[row for row in report['rows'] if (row.get('account'),row.get('target'))==pair]
            if len(rows)!=1 or not rows[0].get('key'):
                raise ValueError('原批次没有唯一确切素材：'+'/'.join(pair))
            bound.append(rows[0])
    results=[]
    try:
        for pair,row in zip(targets,bound):
            result=dict(account=pair[0],target=pair[1],key=row['key'],filename=row['filename'],
                repair_version=upload.VERSION,attempted_at=datetime.now().astimezone().isoformat())
            print('\n仅修复后重试原发布前失败：','/'.join(pair),row['filename'],flush=True)
            try:
                done=retry_one(pair,path,report,False,confirmation_id='before-post-repair-'+upload.VERSION.replace('.','-'),
                    direct_publication=True,close_windows=close_windows,before_post_only=True)
                result['attempt']='finished' if done is not False else 'skipped'
            except KeyboardInterrupt:
                result.update(attempt='interrupted',error='用户中断，保留任务状态')
                raise
            except Exception as error:
                result.update(attempt='account_action_required' if isinstance(error,upload.AccountActionRequired) else 'stopped',
                              error=str(error))
                print('此目标保留记录，继续下一个：',error,flush=True)
            finally:
                results.append(result)
                with locked():
                    current=upload.read_json(path,{})
                    if (current.get('schema')!=report['schema'] or current.get('rows')!=report['rows']
                            or current.get('caption_text')!=report['caption_text'] or current.get('ai_label')!=report['ai_label']):
                        raise ValueError('原批次报告变化，未覆盖其内容')
                    current.setdefault('repair_results',[]).append(result)
                    direct.save(path,current,current['rows'],current.get('results',[]))
    finally:
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        print('\n本次指定目标结果：',flush=True)
        for pair,row in zip(targets,bound):
            actual=state.get(row['key'],{})
            print('/'.join(pair),row['filename'],actual.get('status','missing'),flush=True)
        print('已更新原汇总：',path.with_suffix('.csv'),flush=True)
        print('其余目标未重新发布；新结果未知时不重复使用本次重试。',flush=True)
    return 0 if all(state.get(row['key'],{}).get('status')=='published' for row in bound) else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='修复后只重试原批次明确的发布前失败')
    parser.add_argument('--source-report',required=True)
    parser.add_argument('--targets',required=True)
    parser.add_argument('--close-windows',action='store_true')
    args=parser.parse_args()
    try:
        raise SystemExit(run(args.source_report,parse_target_pairs(args.targets),args.close_windows))
    except KeyboardInterrupt:
        print('已中断，保留当前任务记录。',flush=True)
        raise SystemExit(130)
    except Exception as error:
        print('STOP：',error,flush=True)
        raise SystemExit(1)
