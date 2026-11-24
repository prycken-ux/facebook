"""Stop only the status-bound Nov23 repair; leave all publication ledgers intact."""
import copy,json,subprocess,sys,uuid
from pathlib import Path
from publication_file_state_20261124 import save

STATUS='logs/nov23-caption-fb09-repair-status.json'
MARKER='logs/nov23-user-ended-20261124.json'

def finish(root,audit):
    if audit.get('schema')!='nov23-user-ended-video-repair-v1' or audit.get('material_date')!='2026-11-23' or audit.get('submission_records_preserved') is not True:
        raise ValueError('停止回执不符，保留原状态。')
    path=root/STATUS;status=json.loads(path.read_text(encoding='utf-8-sig'))
    if status.get('launch_id')!=audit['launch_id'] or status.get('pid')!=audit['owner_pid'] or status.get('material_date')!='2026-11-23':
        raise ValueError('原23号任务回执变化，未覆盖。')
    # Audit includes the complete original status. Neither publish_state nor the
    # video/comment ledgers are edited or interpreted as failed/successful.
    save(root/MARKER,audit)
    stopped=copy.deepcopy(status)
    stopped.update(phase='user_stopped',message='用户结束23号修复发布；保留所有原视频及提交/待核实记录，不再续跑。',updated_at=audit['stopped_at'],user_ended_audit=MARKER)
    save(path,stopped)

def main(root):
    if sys.platform!='win32':raise ValueError('请在原Windows上传电脑执行。')
    root=Path(root).resolve()
    if not (root/'upload_config.json').is_file():raise ValueError('不是原上传目录。')
    audit_path=root/'logs'/('nov23-stop-audit-'+uuid.uuid4().hex+'.json')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_suffix('.ps1')),'-Root',str(root),'-ResultPath',str(audit_path)],capture_output=True,timeout=60,creationflags=0x08000000)
    output=(result.stdout+result.stderr).decode('utf-8-sig',errors='replace').strip()
    # Windows PowerShell may use its OEM encoding when output is redirected;
    # the JSON audit, not console text, is the authoritative acknowledgement.
    if result.returncode or not audit_path.is_file():raise RuntimeError('未确认23号已结束；未动24号。'+output)
    audit=json.loads(audit_path.read_text(encoding='utf-8-sig'));finish(root,audit)
    # Keep this project Python alive until cleanup ends so the Nov24 PowerShell
    # queue continues waiting. Recover only locks whose owners are proven dead.
    try:
        import verified_publication_lock_recovery as locks
        locks.recover_locks(root)
    except Exception as error:print('23号已结束；遗留锁保留待核对：'+str(error),flush=True)
    print('已结束23号视频补发；提交和待核实记录已保留，未关闭24号或其他账号任务。',flush=True)
    print('停止记录：'+str(root/MARKER),flush=True)
    return 0

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    try:raise SystemExit(main(Path(sys.argv[1])))
    except Exception as error:print('STOP：'+str(error),flush=True);raise SystemExit(1)
