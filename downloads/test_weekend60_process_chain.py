import copy,subprocess,unittest
from unittest.mock import patch
import weekend60_schedule_20261120 as schedule
import test_nov16_venv_process_chain as fixtures

class WeekendWorkerTests(unittest.TestCase):
    def test_scheduled_pythonw_venv_pair_exempts_only_exact_day_and_plan(self):
        f=fixtures.VenvProcessChainTests();f.setUp();runner=f.root+r'\material-staging\tools\package\weekend60_run_20261120.py';sha='e'*64
        rows=copy.deepcopy(f.rows[:2]);rows[1]['parent']=1
        for r in rows:
            r['name']='pythonw.exe';r['command']=subprocess.list2cmdline([f.exe,'-u',runner,f.root,sha])
        rows.append(f.row(101,1,['-u',runner,f.root,sha]))
        rows.append(f.row(102,1,['-u',runner,f.root,'a'*64]))
        rows.append(f.row(103,1,['-u',f.root+r'\publish_eligible60_materials_20261119.py',f.root]))
        workers,allowed=schedule.app.workers.classify_workers(rows,f.root,100,runner,extra_arguments=(sha,))
        self.assertEqual(allowed,[99,100]);self.assertEqual({r['pid'] for r in workers},{101,102,103})
    def test_setup_four_process_chain_with_immutable_starter_is_exempted(self):
        f=fixtures.VenvProcessChainTests();f.setUp();rows=copy.deepcopy(f.rows)
        runner=f.root+r'\material-staging\tools\package\weekend60_schedule_20261120.py'
        body=f.body.replace('start_finish_first24_nov16','start_weekend60_schedule_20261120').replace('verified-nov16-first24-and-nov14-stage','verified-weekend60-three-day-schedule')
        for r in rows[:2]:r['command']=subprocess.list2cmdline([f.exe,'-u',runner,f.root])
        for r in rows[2:]:r['command']=subprocess.list2cmdline([f.exe,'-u','-c',body,f.root])
        with patch.object(schedule.app.workers,'BOOTSTRAP',schedule.BOOTSTRAP):workers,allowed=schedule.app.workers.classify_workers(rows,f.root,100,runner)
        self.assertEqual(allowed,[97,98,99,100]);self.assertEqual(workers,[])
    def test_invalid_extra_grant_not_accepted(self):
        f=fixtures.VenvProcessChainTests();f.setUp()
        with self.assertRaises(ValueError):schedule.app.workers.classify_workers(f.rows,f.root,100,f.runner,extra_arguments=('not-a-digest',))

if __name__=='__main__':unittest.main()
