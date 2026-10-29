"""Record explicit success confirmations and export only bound failure evidence."""
import argparse
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import confirm_selected_round as confirmations
import fb_upload as upload
from add_fb_accounts import locked
from diagnose_personal_identity import parse_target_pairs


def run(source_report,confirmed_targets=(),verified=False,output_dir=None):
    if not re.fullmatch(r'other-accounts-publish-\d{8}-\d{6}-\d{6}\.json',source_report):
        raise ValueError('需提供确切原 other-accounts-publish 报告文件名')
    if confirmed_targets:
        confirmations.confirm(None,confirmed_targets,verified,source_report=source_report)
    with locked():
        path,report=confirmations.load_expanded_report(source_report)
        state=upload.read_json(upload.ROOT/'logs/publish_state.json',{})
        config=upload.read_json(upload.CONFIG,{})
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        directory=upload.ROOT/'logs'/('other-accounts-failure-review-'+stamp)
        directory.mkdir(parents=True)
        evidence=dict(schema='other-accounts-failure-evidence-v1',source_report=path.name,
            original_created=report['created'],collected_at=datetime.now().astimezone().isoformat(),
            currently_installed_core=upload.VERSION,failures=[],blocked_targets=[],missing_artifacts=[])
        files={}

        def collect(source,name):
            if not source.is_file():
                evidence['missing_artifacts'].append(name)
                return
            source.resolve().relative_to((upload.ROOT/'logs').resolve())
            files[name]=source.read_bytes()

        rows=report.get('rows',[])
        for row in rows:
            key=row.get('key')
            record=state.get(key,{}) if key else {}
            pair=(row.get('account'),row.get('target'))
            if row.get('status')=='blocked_by_older_review':
                blocking=[]
                for old_key in row.get('blocking_keys',[]):
                    old=state.get(old_key,{})
                    blocking.append({field:old.get(field) for field in
                        ('account','target','status','url','created','error','confirmation_method','confirmed_source_report')}
                        |dict(key=old_key,filename=confirmations.basename(old.get('video',''))))
                evidence['blocked_targets'].append(dict(account=pair[0],target=pair[1],blocking_records=blocking))
            if record.get('status')!='failed_before_post':
                continue
            if (not re.fullmatch(r'[a-f0-9]{64}',key or '') or (record.get('account'),record.get('target'))!=pair
                    or upload.target_key(record.get('url',''))!=upload.target_key(row.get('url',''))):
                raise ValueError('失败记录与原批次冲突，未打包其他任务')
            job={field:record.get(field) for field in
                 ('account','target','url','created','status','error','failure_stage','uploader_version','ai_label_requested')}
            job.update(key=key,filename=row['filename'])
            entry=next((item for item in config.get('targets',[]) if
                        (item.get('account'),item.get('target'))==pair),{})
            job['configured_target']={field:entry.get(field) for field in
                ('account','target','type','name','url','enabled','workflow','prepared_at')}
            evidence['failures'].append(job)
            prefix=pair[0]+'-'+pair[1]
            collect(path.with_name(path.stem+'-'+prefix+'-error.txt'),prefix+'-full-error.txt')
            collect(upload.ROOT/'logs'/('review-'+key[:12]+'.png'),prefix+'-failure.png')
            optional=upload.ROOT/'logs'/('review-'+key[:12]+'-error.txt')
            if optional.is_file():
                collect(optional,prefix+'-core-error.txt')
        files['failure-evidence.json']=json.dumps(evidence,ensure_ascii=False,indent=2).encode('utf-8')
        for name,content in files.items():
            (directory/name).write_bytes(content)
        destination=Path(output_dir) if output_dir else upload.ROOT/'logs'
        if not destination.is_dir():
            raise ValueError('诊断包输出目录不存在')
        output=destination/('请上传-其他账号失败调查-'+stamp+'.zip')
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,content in files.items():
                archive.writestr(name,content)
        print('\n失败证据已打包：',len(evidence['failures']),'个目标',flush=True)
        print('请上传完整压缩包，不用解压：',output,flush=True)
        print('本工具没有打开浏览器、上传或发布视频。',flush=True)
        return output


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='补记已确认成功的原视频，并打包本轮失败日志与截图')
    parser.add_argument('--source-report',required=True)
    parser.add_argument('--confirmed-targets')
    parser.add_argument('--verified-published',action='store_true')
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    try:
        run(args.source_report,parse_target_pairs(args.confirmed_targets) if args.confirmed_targets else (),
            args.verified_published,args.output_dir)
    except Exception as error:
        print('STOP：',error,flush=True)
        raise SystemExit(1)
