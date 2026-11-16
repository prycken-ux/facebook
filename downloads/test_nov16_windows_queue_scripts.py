"""Exercise the Windows scripts in PowerShell with synthetic CIM/task providers."""
import json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
import finish_first24_nov14_on_nov16 as app

PWSH=shutil.which('pwsh') or ('/tmp/nov16-pwsh/pwsh' if Path('/tmp/nov16-pwsh/pwsh').is_file() else None)


@unittest.skipUnless(PWSH,'PowerShell runtime unavailable')
class WindowsQueueScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.env=dict(os.environ,XDG_CACHE_HOME=str(self.root/'cache'),XDG_CONFIG_HOME=str(self.root/'config'),XDG_DATA_HOME=str(self.root/'data'))
    def run_ps(self,script,data):
        path=self.root/'script.ps1';path.write_text(script)
        return subprocess.run([PWSH,'-NoLogo','-NoProfile','-NonInteractive','-File',str(path)],input=json.dumps(data),text=True,capture_output=True,env=self.env,timeout=20)
    def test_live_workers_only_exempt_actual_direct_verified_bootstrap_parent(self):
        root=r'E:\FB-AutoUpload';exe=root+r'\.venv\Scripts\python.exe'
        rows=[dict(ProcessId=7,ParentProcessId=8,Name='python.exe',ExecutablePath=exe,CommandLine=root+r'\material-staging\tools\cache\finish_first24_nov14_on_nov16.py'),
              dict(ProcessId=8,ParentProcessId=9,Name='python.exe',ExecutablePath=exe,CommandLine="python -c https://raw.githubusercontent.com/p/r/sha/downloads/start_finish_first24_nov16.py "+root),
              dict(ProcessId=10,Name='python.exe',ExecutablePath=exe,CommandLine=root+r'\publish_unplanned_fortysix_nov14.py'),
              dict(ProcessId=11,Name='python.exe',ExecutablePath=exe,CommandLine=root+r'\summarize_nov12_readonly.py'),
              dict(ProcessId=12,Name='python.exe',ExecutablePath=exe,CommandLine='python -c unrelated_but_unclassified'),
              dict(ProcessId=13,Name='python.exe',ExecutablePath=exe,CommandLine=root+r'\start_finish_first24_nov16.py'),
              dict(ProcessId=14,Name='python.exe',ExecutablePath=r'C:\Other\python.exe',CommandLine='other_work.py')]
        file=self.root/'processes.json';file.write_text(json.dumps(rows))
        prefix="function Get-CimInstance { Get-Content -Raw '"+str(file)+"' | ConvertFrom-Json }\n"
        result=self.run_ps(prefix+app.WORKERS,dict(pid=7,root=root,python=exe))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual({r['pid'] for r in json.loads(result.stdout)},{10,12,13})
        self.assertNotIn('CommandLine',result.stdout)
    def task(self,name,*,state='Ready',date='2026-11-14T09:00:00+08:00',repeat=None,python=None):
        root=r'E:\FB-AutoUpload'
        return dict(TaskName=name,TaskPath='\\',State=state,Actions=[dict(Execute=python or root+r'\.venv\Scripts\python.exe',WorkingDirectory=root,Arguments='"'+root+r'\scheduled_priority_workflow.py" run --manifest fixed.json')],
                    Triggers=[dict(CimClass=dict(CimClassName='MSFT_TaskTimeTrigger'),Repetition=dict(Interval=repeat),StartBoundary=date)])
    def schedule_run(self,rows,fail_second=False):
        datafile=self.root/'tasks.json';datafile.write_text(json.dumps(rows))
        log=self.root/'mutations.txt'
        prefix="""$script:tasks=Get-Content -Raw 'TASKFILE' | ConvertFrom-Json
function Get-ScheduledTask { param($TaskName,$TaskPath) if($TaskName){$script:tasks | Where-Object {$_.TaskName -eq $TaskName}}else{$script:tasks} }
function Export-ScheduledTask { param($TaskName,$TaskPath) '<Task>'+ $TaskName +'</Task>' }
function Unregister-ScheduledTask { param($TaskName,$TaskPath,[switch]$Confirm) if(FAILSECOND -and $TaskName -eq 'FBUpload-Old2'){throw 'simulated failure'};Add-Content 'MUTATIONLOG' ('remove '+$TaskName) }
function Register-ScheduledTask { param($TaskName,$TaskPath,$Xml) Add-Content 'MUTATIONLOG' ('restore '+$TaskName) }
""".replace('TASKFILE',str(datafile)).replace('MUTATIONLOG',str(log)).replace('FAILSECOND','$true' if fail_second else '$false')
        backup=self.root/'backup';backup.mkdir(exist_ok=True)
        root=r'E:\FB-AutoUpload'
        result=self.run_ps(prefix+app.SCHEDULES,dict(root=root,python=root+r'\.venv\Scripts\python.exe',backup=str(backup),cutoff='2026-11-16T00:00:00+08:00',scripts=[root+r'\scheduled_priority_workflow.py']))
        return result,log.read_text() if log.exists() else '',backup
    def test_only_expired_exact_one_off_task_removed_after_xml_backup(self):
        rows=[self.task('FBUpload-Old'),self.task('FBUpload-Future',date='2026-11-17T09:00:00+08:00'),self.task('FBUpload-Recurring',repeat='P1D'),self.task('FBUpload-Other',python=r'C:\Other\python.exe')]
        result,log,backup=self.schedule_run(rows);self.assertEqual(result.returncode,0,result.stderr)
        receipt=json.loads(result.stdout);self.assertEqual(receipt['removed'],['FBUpload-Old'])
        self.assertEqual(set(receipt['preserved']),{'FBUpload-Future','FBUpload-Recurring','FBUpload-Other'})
        self.assertEqual(log.strip(),'remove FBUpload-Old');self.assertEqual(len(list(backup.glob('*.xml'))),1)
        self.assertIn('<Task>FBUpload-Old</Task>',next(backup.glob('*.xml')).read_text())
    def test_running_task_refuses_before_any_delete(self):
        result,log,_=self.schedule_run([self.task('FBUpload-Running',state='Running')])
        self.assertNotEqual(result.returncode,0);self.assertIn('still running',result.stderr);self.assertEqual(log,'')
    def test_partial_delete_restores_removed_task_from_exact_xml(self):
        result,log,backup=self.schedule_run([self.task('FBUpload-Old'),self.task('FBUpload-Old2')],fail_second=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('simulated failure',result.stderr)
        self.assertEqual(log.splitlines(),['remove FBUpload-Old','restore FBUpload-Old'])
        self.assertEqual(len(list(backup.glob('*.xml'))),2)


if __name__=='__main__':unittest.main()
