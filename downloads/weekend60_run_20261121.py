"""Fixed-date background entry; original progress is never reset."""
import contextlib,sys
from datetime import datetime
from pathlib import Path
root=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(root));sys.path.insert(0,str(Path(__file__).resolve().parent))
(root/'logs').mkdir(exist_ok=True)
with (root/'logs'/'weekend60-2026-11-21-run.log').open('a',encoding='utf-8',buffering=1) as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
    try:
        import weekend60_schedule_20261120 as schedule
        print('Run started:',datetime.now().astimezone().isoformat(),flush=True)
        raise SystemExit(schedule.run_day(root,'2026-11-21',sys.argv[2]))
    except KeyboardInterrupt:
        print('Paused; exact original jobs retained.',flush=True);raise SystemExit(130)
    except Exception as error:
        print('STOP:',str(error) or type(error).__name__,flush=True);raise SystemExit(1)
