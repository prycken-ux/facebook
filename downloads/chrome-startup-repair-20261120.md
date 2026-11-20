Chrome startup repair, 2026-11-20

Observed Windows traceback: the initial Chrome Popen process exits before DevToolsActivePort exists. Cleanup then raises a profile-busy error, hiding that initial exception. The actual reason Chrome exits is not yet established.

Wait up to the existing 30-second startup budget for a valid loopback endpoint even if the initial launcher exits. Capture Chrome stderr locally. Preserve primary launch/authorization failures even if cleanup fails. A retained Popen handle is the only handle force-closed by normal session cleanup.

The standalone installer stops only today's fixed Weekend60 task, refuses to modify files while another project Python process is active, recovers only proven stale locks, acquires the existing upload locks, and closes only idle headless Chrome parent processes belonging to the 40 currently active project profiles. It pins process handles and checks creation times; visible browsers and excluded profiles are retained. Original programs are backed up, with rollback on installation write errors. A local blank-page startup/close probe precedes restarting the existing task. Failure leaves today's task stopped and prints the diagnostic file location.

No video state, retry claims, media, caption, comment, account exclusion or future schedule is changed. Successful local startup is not proof of Facebook publication. Original task safeguards decide which jobs can safely retry.

Validation: 60 relevant Python tests; real Chromium loopback blank-page launch and clean exit; actual PowerShell parsing for both embedded scripts; installer process identity checks for Windows venv parent, sibling and login process. Windows execution still requires the user's machine.
