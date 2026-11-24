# Resume Nov23 with a hard comment-target deadline

A synchronous browser response read can stop the comment lookup loop before it checks its soft timeout. The current Nov23 log stopped at fb10/page03 for over an hour while the queue still said running.

This entry resumes the original Nov23 allocation and runs an independent supervisor. Each comment target, including lookup, send, verification, reporting and browser close, has a 180-second monotonic deadline. The worker starts suspended, is assigned to a Windows Job Object, and only then resumes; this contains the Windows venv launcher and all new Python, browser and transport descendants. At timeout the supervisor terminates that job, waits for its processes to exit, records the skipped target and restarts the original workflow with that target excluded from further comment attempts in the current run. Completed phase targets are retained across worker restarts. Only the current target can reserve an automatic comment-retry claim.

For the existing uncontained process, takeover requires a matching original Nov23 direct-worker status, pinned original driver path and SHA256, unchanged queue and log hashes, and a log older than 180 seconds with one identifiable unfinished comment target from the original frozen manifests. PowerShell pins process handles and validates creation times; only the matching old worker and verified descendants are terminated. A changing log or ambiguous process is preserved. The original recovery archives only PID locks whose owners have exited.

Existing video state, comment ledger and submit-intent protection stay authoritative. Unknown video outcomes are not reuploaded and pending comment sends are not resent without reconciliation. The original caption, corrected comment, real-footage AI OFF policy and paused34 scope are verified through the pinned original runtime. The root uploader source and profile files are not overwritten.

Artifacts on the upload computer:

- `logs/eligible60-2026-11-23-deadline.json`: supervisor acknowledgment and latest status.
- `logs/nov23-comment-deadline-<run>.json`: completed phase targets and skipped targets.
- `logs/nov23-comment-operation-<worker>.json`: monotonic target start and completion.
- Existing `logs/eligible60-2026-11-23-run.log`: normal output plus supervisor updates every 15 seconds.
- Unique supervisor and worker diagnostic files under `logs`.

Validation: 24 tests passed. These include a real blocked Python worker and descendant terminated using a Linux process-group adapter followed by successful next-target completion; actual PowerShell execution with mocked process handles to verify exact descendant termination, changed logs, PID reuse and unchanged other processes; Windows API contract tests for suspended assignment and failed-assignment cleanup; target filtering and retry-claim isolation; pinned runtime download, source hash checks, import and original scope/content assertions. Windows Job Object and real Facebook runtime execution require running the starter on the upload computer. No Windows publishing operation was performed during these tests.

Takeover update: PowerShell 5.1 `Get-FileHash` can open the old log without sharing write access and fail while the original Python worker keeps its append handle open. SHA256 now uses an explicitly read-only .NET FileStream with ReadWrite/Delete sharing. It neither closes the writer nor edits the log. Queue/log hashes are still checked twice and process identity, staleness and ownership guards are retained. Added tests hold a real .NET writer open while hashing, confirm the writer remains usable and the bytes unchanged, reject a missing log without creating it, and reject log changes after process handles were pinned. The rebuilt starter uses a new immutable cache fingerprint. Real Windows takeover still requires running the updated command.
