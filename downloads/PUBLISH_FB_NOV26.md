# November 26 FB publication and comments

User explicitly requested publication and comments for today's FB videos using prior rules, then confirmed this batch is all real footage with no AI/significant alteration and requested the AI label OFF. Scope: the completed Nov26 eligible58 allocation only. Instagram, old Nov25 work, deleted media and the three Disabled old Weekend60 scheduled tasks are not resumed or modified.

The batch binds `material-staging/eligible58-20261126-pending-import.json`, original imported distribution, journal progress, source hashes, actor identities and reservation generations. An incomplete distribution is awaited for at most 180 seconds by a PowerShell queue; this entry never picks or redistributes source videos. A generic pointer is never substituted for the Nov26 source. Frozen waves, requests, claims and result filenames use a new eligible58 scope; historical eligible60 jobs stay unchanged. Thirty-six stopped accounts include fb32/fb52, leaving 38 account slots and 58 targets (32 personal / 26 Pages) before any additional live exclusion.

Original caption and corrected first-comment revision: `ef039935845a6c85c37d4502d113bf15605f5103e374b0cecff29c32cf9bd894`. Existing content policies are verified, not rewritten. Only this user-confirmed Nov26 footage uses AI OFF.

Before any media child starts, one read-only Windows snapshot checks all currently active requested FB profile directories. A busy profile blocks startup with the exact account/PID; no manual browser is killed. Existing IG windows and IG-root Python tasks remain separate even if they share the FB venv. A newly appearing occupied FB profile is checked again during its individual operation. Existing safe idle-owner handling remains scoped and conservative.

A supervisor owns a suspended-launch Windows Job for each worker. Video and comment operations have independent 180-second budgets; video time includes profile checks/browser preparation. Receipt waiting shares that budget and reserves ten seconds for durable state. Only the owned Job is stopped on deadline. Exact frozen operation/request/date/actor bindings are checked before a timed-out target can be skipped. No operation marker for 180 seconds causes a diagnostic stop instead of an indefinite hang or guessing a target. Progress is emitted every 15 seconds.

Post-receipt timeout may be treated as success under the user's standing rule only after the native click returned and state proves `needs_review` / `publication_receipt_timeout` / `wait_success_receipt` for this exact file and actor. `post_intent_at` alone never authorizes success or retry. Assumed-success provenance and original errors remain; no platform receipt/link is invented. Submitted or uncertain videos are never uploaded twice. Only existing bounded safe pre-Post retry grants apply.

Comments use the previously tested upload-created time window, owner/full-caption/time/video-ID proofs and DOM-order lookup corrections. A first-comment gate requires the exact actor/job/text/permalink ledger and `own_comment_seen_after_reload` evidence before expanding attempts. A first comment failure/timeout blocks later comment attempts, preserving video outcomes and exporting a scoped diagnostic ZIP to Desktop (logs fallback). Other established comment successes remain; uncertain sends are not blindly repeated. A gate failure produces review_required even if a child incorrectly returns zero. Gate evidence is synchronized across watchdog child restarts.

The launcher opens a separate PowerShell live log window after queue acknowledgment, then exits so it cannot deadlock the queue's Python-worker checks. Closing the log viewer stops viewing only. The process stays in the background. Duplicate starts are checked by queue/supervisor mutexes, source identity and actual process command/creation checks. Logs/acknowledgments distinguish waiting, starting, running, finished and review_required.

Key files:
- `logs/eligible58-2026-11-26-run.log`
- `logs/eligible58-2026-11-26-status.json`
- `logs/nov26-profile-preflight.json`
- `logs/eligible58-real-publication-request-20261126.json`
- `logs/eligible58-real-publication-<request-prefix>.json` and `.txt`
- `logs/nov26-comment-gate-<request-prefix>.json`
- Desktop `FB-Nov26-comment-diagnostic-*.zip` if first-comment verification fails.

Local validation includes 58-target simulated publication/comment flows, exact source/content/AI assertions, failure and replay behavior, before-click versus post-click evidence, actual blocked child process-group cleanup, PowerShell queue tests, first-comment ledger negatives, profile preflight negatives, overlay integrity, independent runtime import probe and allocation regression. These checks do not establish Facebook live success; execution on the user's Windows machine and actual platform/comment results still require its current acknowledgments and logs.
