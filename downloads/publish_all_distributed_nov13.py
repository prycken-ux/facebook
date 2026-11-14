"""Run originals first, then the owned fifty-account generation; both include comments."""
import contextlib,copy,hashlib,re,shutil,sys,uuid
from collections import Counter
from pathlib import Path
from unittest.mock import patch
if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import publish_distributed_nov13_first24 as first
import personal_owner_registration as registration

NEW={f'fb{n:02d}' for n in range(25,75)}
BATCH_ID='personal-20261112-fifty-fb25-fb74'
SECOND='nov13-distributed-second-owned-fifty-v1'
CONTROL='nov13-distributed-two-wave-publication.json'
SUMMARY='nov13-two-wave-summary.json'
WAVE_POINTER_PREFIX='nov13-second-wave-'
RUN=first.execute
DISTRIBUTION=first.distribution
ORIGINAL_VALIDATE=first.workflow.validate


def reservation():
    value=first.upload.read_json(first.upload.ROOT/'additional_personal_accounts.json',{})
    batch=value.get('batches',{}).get(BATCH_ID,{})
    if (value.get('schema')!='additional-personal-logins-v1' or batch.get('accounts')!=sorted(NEW) or batch.get('count')!=50
            or any(value.get('slots',{}).get(a,{}).get('batch_id')!=BATCH_ID for a in NEW)):
        raise ValueError('fb25–fb74不是这次明确预留的新50账号批次，未恢复旧的已删除账号。')
    return value


def register_one(account,entry,proof):
    config=first.upload.read_json(first.upload.CONFIG,{})
    registry=first.upload.read_json(first.upload.ROOT/'account_registry.json',{})
    extra=reservation()
    identity=first.upload.target_key(entry.get('url',''))
    if (account not in NEW or entry.get('account')!=account or entry.get('target')!='personal' or entry.get('type')!='personal'
            or not identity.startswith('id:') or proof.get('target_url')!=entry.get('url') or proof.get('name')!=entry.get('name')
            or proof.get('method')!='personal_actor_id_match' or not proof.get('checked_at')
            or proof.get('session_marker')!=hashlib.sha256(('personal:'+identity[3:]).encode()).hexdigest()):
        raise ValueError('新账号缺少刚刚核实的确切本人身份，未登记。')
    first.upload.validate_entry(entry)
    if any(first.upload.target_key(r.get('url',''))==identity for r in config.get('targets',[])+registry.get('accounts',[]) if r.get('account')!=account):
        raise ValueError('同一登录身份已属于其他账号编号，未重复登记。')
    current=[r for r in config.get('targets',[]) if r.get('account')==account]
    known=[r for r in registry.get('accounts',[]) if r.get('account')==account]
    if len(current)>1 or len(known)>1:raise ValueError('该编号已有多个目标，未接管。')
    for row in current+known:
        if row.get('type')!='personal' or row.get('target','personal')!='personal' or first.upload.target_key(row.get('url',''))!=identity:
            raise ValueError('当前登录者与原登记不一致，未换号或覆盖。')
    mapping={k:entry[k] for k in ('account','target','type','name','url','workflow')}
    result,recorded,manifest=copy.deepcopy((config,registry,extra))
    row=dict(current[0]) if current else dict(excluded_files=[])
    row.update(mapping,enabled=True,ai_label=False,auto_switch_personal=True,prepared_at=proof['checked_at'],
               identity_verified_at=proof['checked_at'],personal_onboarding_method='verified-personal-onboarding-v1',
               personal_route_validation=dict(version=first.personals.VERSION,aliases=proof.get('verified_aliases',[]),checked_at=proof['checked_at']))
    result['targets']=[r for r in result['targets'] if r.get('account')!=account]+[row]
    recorded['accounts']=[r for r in recorded['accounts'] if r.get('account')!=account]+[dict(mapping,profile='profiles/'+account,inbox='videos/'+account+'/personal/inbox')]
    manifest['slots'][account].update(state='registered',mapping=mapping,publishing_ready=True,identity_verified_at=proof['checked_at'],identity_method=proof['method'])
    paths=[first.upload.CONFIG,first.upload.ROOT/'account_registry.json',first.upload.ROOT/'additional_personal_accounts.json']
    backup=first.upload.ROOT/'backups'/('nov13-ready-'+account+'-'+uuid.uuid4().hex[:10]);backup.mkdir(parents=True)
    originals={p:p.read_bytes() if p.is_file() else None for p in paths}
    for path,data in originals.items():
        if data is not None:(backup/path.name).write_bytes(data)
    try:
        for path,value in zip(paths,(result,recorded,manifest)):first.upload.save_json(path,value)
        if not first.batch.eligible(row,True,date=first.DAY):raise ValueError('新账号发布登记仍不完整。')
    except BaseException:
        for path,data in originals.items():
            if data is None:path.unlink(missing_ok=True)
            else:path.write_bytes(data)
        raise
    print('新账号自动核验并接入：',account,entry['name'],entry['url'],flush=True)


def ready_new():
    reservation();ready=set();issues=[]
    for index,account in enumerate(sorted(NEW),1):
        config=first.upload.read_json(first.upload.CONFIG,{})
        entries=[e for e in config.get('targets',[]) if (e.get('account'),e.get('target'))==(account,'personal')]
        if len(entries)==1 and first.batch.eligible(entries[0],True,date=first.DAY):
            ready.add(account);continue
        print('检查第二批保存的登录：',index,'/50',account,'；自动读取本人名称，不要求重新填写。',flush=True)
        try:
            first.archive.safe(first.upload.ROOT/'profiles'/account)
            entry,proof=registration.discover(account);register_one(account,entry,proof);ready.add(account)
        except KeyboardInterrupt:raise
        except Exception as error:
            issues.append(dict(account=account,reason=str(error).split('\n',1)[0] or type(error).__name__))
            print('该账号暂未通过登录/身份核验，继续其他账号：',account,issues[-1]['reason'],flush=True)
    return ready,issues


def fresh_validate(path,value):
    payload=value.get('payload',{})
    if not str(payload.get('distributed_scope','')).startswith(SECOND+'-'):return ORIGINAL_VALIDATE(path,value)
    reservation()
    first.priority.validate(path,value,first.DAY)
    intended=set(payload.get('intended_accounts',[]))
    if (not intended or not intended<=NEW or any(j['account'] not in intended or j['target']!='personal' for j in payload['jobs'])
            or payload.get('distributed_scope')!=SECOND+'-'+first.batch.digest(sorted(intended))[:12]
            or value.get('scheduled_priority_runner')!=first.workflow.VERSION
            or value.get('browser_launch_mode')!=first.normal.NORMAL_CHROME_VERSION or value.get('local_file_input_mode')!=first.local.VERSION):
        raise ValueError('新50账号批次范围或发布模式不匹配。')


@contextlib.contextmanager
def wave(accounts,scope,pointer):
    with patch.object(first,'ALLOWED',set(accounts)),patch.object(first,'SCOPE',scope),patch.object(first,'POINTER',pointer), \
            patch.object(first,'WAVE_LABEL','第二批'),patch.object(first,'WAVE_DESCRIPTION','fb25–fb74（本次已核验账号）'), \
            patch.object(first.workflow,'validate',side_effect=fresh_validate):yield


def summary(first_path,control,issues,material):
    paths=[first_path]+[first.upload.ROOT/'logs'/w['manifest'] for w in control['waves']]
    state=first.upload.read_json(first.upload.ROOT/'logs/publish_state.json',{});rows={}
    for path in paths:
        value=first.archive.checked_json(path)
        for job in value['payload']['jobs']:
            row=state.get(job['key'],{})
            rows[job['key']]=dict(account=job['account'],target=job['target'],filename=job['filename'],
                                  video_status=row.get('status','not_started'),comment_status=row.get('comment_status','not_started'))
    counts=Counter(r['video_status'] for r in rows.values())
    expected={(r['account'],r['target']) for r in material['payload']['assignments'] if r['account'] in NEW|{f'fb{n:02d}' for n in range(1,25)}}
    covered={(r['account'],r['target']) for r in rows.values()}
    missing=sorted(expected-covered)
    print('今天两批累计：视频成功',counts['published'],'；发布前失败',counts['failed_before_post'],
          '；待核实',sum(counts[k] for k in ('needs_review','posting','preparing')),'；未开始',counts['not_started'],
          '；评论确认成功',sum(r['comment_status'] in {'sent','already_present'} for r in rows.values()),'；尚未进入发布清单',len(missing),flush=True)
    for issue in issues:print('第二批仍需处理：',issue['account'],issue['reason'],flush=True)
    complete=not missing and not issues and all(r['video_status']=='published' and r['comment_status'] in {'sent','already_present'} for r in rows.values())
    first.upload.save_json(first.upload.ROOT/'logs'/SUMMARY,dict(date=first.DAY,source_material_date=first.MATERIAL_DAY,rows=list(rows.values()),new_account_issues=issues,unplanned_targets=missing,complete=complete))
    return complete


def execute(real_footage):
    if not real_footage:raise ValueError('今天所有待发布素材尚未确认全部实拍。')
    first.require_day()
    with first.locked():
        path,material,_,_=DISTRIBUTION()
        relative=first.archive.relative(path)
        selected={(r['account'],r['target']) for r in material['payload']['assignments'] if r.get('account') in NEW}
        if selected!={(a,'personal') for a in NEW}:raise ValueError('今天尚未给fb25–fb74全部分配素材，请先完成统一分配。')
        control_path=first.upload.ROOT/'logs'/CONTROL
        control=first.upload.read_json(control_path,None)
        if control is None:
            payload=dict(date=first.DAY,distribution_manifest=relative,distribution_sha256=material['sha256'])
            control=dict(payload=payload,sha256=first.batch.digest(payload),waves=[]);first.upload.save_json(control_path,control)
        if (control.get('sha256')!=first.batch.digest(control.get('payload',{})) or control['payload'].get('distribution_sha256')!=material['sha256']
                or control['payload'].get('distribution_manifest')!=relative or not isinstance(control.get('waves'),list)):
            raise ValueError('两批发布的原素材来源已变化，未另选视频。')
    def bound(relative_path=None):
        result=DISTRIBUTION(relative_path or relative)
        if result[1]['sha256']!=material['sha256']:raise ValueError('两批素材指纹不一致，未替换。')
        return result
    with patch.object(first,'distribution',side_effect=bound):
        print('先完整处理fb01–fb24及公共主页的视频、一次安全补发和评论，随后自动接着处理fb25–fb74。',flush=True)
        RUN(True)
        first_pointer=first.upload.read_json(first.upload.ROOT/'logs'/first.POINTER,{})
        first_path=first.upload.ROOT/'logs'/first_pointer['manifest']
        print('第一批本轮处理结束；现在检查并处理第二批新50账号。',flush=True)
        progress=first.upload.read_json(path.with_name(path.stem+'-progress.json'),{})
        all_targets={r['account']+'/'+r['target'] for r in material['payload']['assignments']}
        if not all_targets<=set(progress.get('done',[])):
            print('第二批素材分配曾中断，现在只续完原分配清单，再开始新账号发布。',flush=True)
            first.materials.distribute(first.upload.ROOT,material['payload']['source'],day=first.MATERIAL_DAY,scope='all')
        with first.locked():
            ready,issues=ready_new()
            # Recover any second-wave freeze committed before its controller update.
            names={w['manifest'] for w in control['waves']}
            for candidate in (first.upload.ROOT/'logs').glob('frozen-material-'+first.DAY+'-*.json'):
                value=first.upload.read_json(candidate,{})
                if (candidate.name not in names and str(value.get('payload',{}).get('distributed_scope','')).startswith(SECOND+'-')
                        and value['payload'].get('distribution_sha256')==material['sha256']):
                    fresh_validate(candidate,value)
                    accounts=value['payload']['intended_accounts'];tag=first.batch.digest(sorted(accounts))[:12]
                    control['waves'].append(dict(accounts=accounts,scope=value['payload']['distributed_scope'],pointer=WAVE_POINTER_PREFIX+tag+'.json',manifest=candidate.name,sha256=value['sha256']))
            covered=set()
            for saved in control['waves']:
                if (not re.fullmatch(re.escape(WAVE_POINTER_PREFIX)+r'[a-f0-9]{12}\.json',saved.get('pointer',''))
                        or not re.fullmatch('frozen-material-'+first.DAY+r'-[a-f0-9]{16}\.json',saved.get('manifest',''))):
                    raise ValueError('第二批续跑指针格式异常。')
                value=first.archive.checked_json(first.upload.ROOT/'logs'/saved['manifest']);fresh_validate(first.upload.ROOT/'logs'/saved['manifest'],value)
                if saved['sha256']!=value['sha256']:raise ValueError('第二批原冻结指纹变化。')
                covered.update(j['account'] for j in value['payload']['jobs'])
            remaining=ready-covered
            if remaining:
                tag=first.batch.digest(sorted(remaining))[:12];scope=SECOND+'-'+tag;pointer=WAVE_POINTER_PREFIX+tag+'.json'
                try:
                    with wave(remaining,scope,pointer):path,value=first.freeze()
                    if path.name not in {w['manifest'] for w in control['waves']}:
                        control['waves'].append(dict(accounts=sorted(remaining),scope=scope,pointer=pointer,manifest=path.name,sha256=value['sha256']))
                except ValueError as error:
                    issues.extend(dict(account=a,reason=str(error).split('\n',1)[0]) for a in sorted(remaining))
            first.upload.save_json(control_path,control)
        for saved in control['waves']:
            with wave(saved['accounts'],saved['scope'],saved['pointer']):RUN(True)
        complete=summary(first_path,control,issues,material)
    return 0 if complete else 3


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:
        if first.upload.ROOT.resolve()!=Path(sys.argv[1]).resolve():raise ValueError('请在原上传目录运行。')
        raise SystemExit(execute('--real-footage' in sys.argv[2:]))
    except KeyboardInterrupt:print('已暂停，两批的归档、发布和评论进度均保留；重跑继续。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
