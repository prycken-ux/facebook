"""Register the user's exact ten fb09 Pages and inboxes; never upload or publish."""
import copy
import shutil
import sys
from datetime import datetime
from pathlib import Path

if __name__=='__main__':sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import add_fb_accounts as accounts
import fb_upload as upload

ACCOUNT='fb09'
PAGES=(
    ('page01','Tastingju Diteshogren','61595986545178'),
    ('page02','Thugrabra Pivirtpruclu','61595989965125'),
    ('page03','Belukupla Plitleldvo','61595990925353'),
    ('page04','Hungshusoda Dreltgoltglipla','61596006674234'),
    ('page05','Shonglevine Turdstulflogas','61596155017553'),
    ('page06','Joclusleplu Prublusoto','61596319380574'),
    ('page07','Ditrugepo Grongdodi','61595963866525'),
    ('page08','Taftrelucla Dusucos','61595977605490'),
    ('page09','Chaplefle Niltchobro','61595956966226'),
    ('page10','Glarplibre Plafono','61595952586635'),
)


def plan(config):
    if (not isinstance(config,dict) or not isinstance(config.get('targets'),list)
            or any(not isinstance(row,dict) for row in config['targets'])):
        raise ValueError('原上传配置格式异常，未修改')
    owners=[row for row in config['targets'] if (row.get('account'),row.get('target'))==(ACCOUNT,'personal')]
    if len(owners)!=1 or owners[0].get('type')!='personal':raise ValueError('fb09没有唯一的原个人主页配置')
    upload.validate_entry(owners[0])
    updated=copy.deepcopy(config);added=[]
    for target,name,number in PAGES:
        current=[row for row in updated['targets'] if (row.get('account'),row.get('target'))==(ACCOUNT,target)]
        if len(current)>1:raise ValueError('已有重复目标编号，未修改：'+target)
        for row in updated['targets']:
            if upload.target_key(row.get('url',''))=='id:'+number and row not in current:
                raise ValueError('该公共主页已登记在其他目标，未重复添加：'+target)
        if current:
            row=current[0]
            if row.get('type')!='page' or row.get('name')!=name or upload.target_key(row.get('url',''))!='id:'+number:
                raise ValueError('目标编号已用于其他配置，未覆盖：'+target)
            upload.validate_entry(row)
        else:
            row=dict(account=ACCOUNT,target=target,type='page',name=name,url='https://www.facebook.com/profile.php?id='+number,
                     enabled=False,ai_label=owners[0].get('ai_label',True),excluded_files=[],workflow='page_flow_configured')
            upload.validate_entry(row);updated['targets'].append(row);added.append(target)
    return updated,added


def connect(root):
    root=Path(root).resolve()
    if any(Path(value).resolve()!=root for value in (upload.ROOT,accounts.ROOT)) or upload.CONFIG.resolve()!=root/'upload_config.json':
        raise ValueError('上传目录与原程序不一致，未修改配置')
    if upload.VERSION!='2.47':raise ValueError('原上传核心版本不匹配，未覆盖原程序')
    if not upload.CONFIG.is_file() or not (root/'profiles'/ACCOUNT).is_dir():
        raise ValueError('缺少fb09原浏览器资料或上传配置，未创建空白登录资料代替')
    with accounts.locked():
        original=upload.CONFIG.read_bytes()
        config=upload.read_json(upload.CONFIG,None)
        # Validate all ten slots and all cross-account Page ID collisions first.
        updated,added=plan(config)
        for target,_,_ in PAGES:
            for folder in ('inbox','completed','failed'):
                (root/'videos'/ACCOUNT/target/folder).mkdir(parents=True,exist_ok=True)
        if added:
            backup=root/'backups'/('connect-fb09-pages-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            backup.mkdir(parents=True,exist_ok=False)
            saved=backup/'upload_config.json';saved.write_bytes(original)
            try:
                upload.save_json(upload.CONFIG,updated)
                if upload.read_json(upload.CONFIG,None)!=updated:raise RuntimeError('写入后配置核对失败')
            except BaseException:
                shutil.copy2(saved,upload.CONFIG)
                raise
            print('原配置已备份：',backup,flush=True)
        print('fb09公共主页登记完成：10/10；本次新增',len(added),'个。',flush=True)
        for target,name,number in PAGES:
            print(ACCOUNT+'/'+target,name,'https://www.facebook.com/profile.php?id='+number,flush=True)
            print('待发布目录：',root/'videos'/ACCOUNT/target/'inbox',flush=True)
        print('原个人主页、登录资料和历史视频/评论记录保留。',flush=True)
        print('后续按原自动批次流程选取新素材，发布前逐页切换并核对数字ID；未通过则跳过。',flush=True)
        print('本次仅登记配置和建立目录；后续发布时执行身份核验。此次没有上传视频或发送评论。',flush=True)
        return updated


def main():
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑运行')
    connect(Path(sys.argv[1]));return 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(main())
    except KeyboardInterrupt:print('已停止；原配置有备份，可重跑同一命令继续登记。',flush=True);raise SystemExit(130)
    except Exception as error:print('STOP：',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
