# Nov25 comments-only recovery

The user explicitly chose the Nov25 current batch on 2026-11-25. Nov24 recovery and its two manually commented sample links remain outside this task.

This package uses the pinned Nov25 publication runtime from b00862fe3ac4c5f36edc56b22bfc0e8c355abbe5 in a new immutable cache. It starts a separate PowerShell queue that waits for existing project publication/allocation/login Python workers to finish, then starts a comments-only watchdog. It does not modify a running publisher or its cache. Queue and supervisor mutexes, status, operation, progress and diagnostic logs are separate from the video publisher. It preserves the original 60-target/34-exclusion scope and exact comment revision.

The recovery hook requires an existing dated publication request, validates the original allocation and frozen job/wave fingerprints, and processes only already submitted published/needs_review jobs. It never adds upload waves, retries videos or changes old dates. The video submission API is explicitly disabled. Local MP4 files are not needed for comment work. Sent/uncertain comment records retain the normal no-double-send protections; uncertain sends are verified on their exact saved permalink rather than sent again.

Three targeted lookup changes address evidence from the prior diagnostic package: pending lookup begins five seconds before the original task's created/upload time instead of five seconds before clicking Post; full owner/caption/time/video-ID metadata plus detail-page author proof can qualify an exact video even when the headless player is hidden, while pending/draft/editor/wrong-owner evidence still rejects it; fallback candidates retain their DOM order instead of sorting video IDs. The already pinned Nov25 policy continues to try the full profile metadata lookup before Reels fallback.

Each comment has an external 180-second Windows Job deadline and a 15-second heartbeat. Only owned worker descendants can be stopped on timeout. Manual Chrome remains protected. Before starting bulk recovery, the first attempted comment must be seen after reload with a matching ledger/video job/account/text/permalink. If it is not, bulk recovery stops and writes a bounded diagnostics ZIP to the user's Desktop (logs fallback). Existing verified comments can satisfy this gate on replay.

Diagnostics record only selected post identifiers, owner IDs, caption/description and absolute time/status fields; never request headers, cookies or raw network responses. They are saved incrementally during lookup to survive a killed worker, and exported files are limited to this batch's job prefixes. A summary distinguishes video status from comment status and only counts reload-verified comments as automatic success. This does not assert that missing live Facebook metadata can always be reconstructed; a failed first lookup deliberately collects the specific observed fields needed to finish diagnosis.

Validation covers original60 comments without any local videos, zero upload calls, replay, exclusion of failed/unsubmitted/other-date jobs, first-comment gate and diagnostic export, scoped evidence/ledger checks, created-before-Post lookup window, actual local Chromium hidden-player/pending/editor/owner cases, Windows queue wait/duplicate behavior, and actual blocked-process cleanup. The exact installation probe is run against the downloaded pinned runtime. Cloud tests do not establish live Facebook success; the user must run the pinned command on the original Windows computer.

Build: `python downloads/build_nov25_comments_starter.py`.
Tests from downloads: `python -m unittest test_repair_nov25_comments_only test_comment_target_watchdog_20261125 test_start_comment_nov25_20261125 test_pending_video_comment_lookup_20261119.PendingLookupTests test_actual_reels_comment_lookup test_nov25_publication_policy`.

Progress log: `logs/eligible60-2026-11-25-comments-repair-run.log`.
Status: `logs/eligible60-2026-11-25-comments-repair-status.json`.
Results: `logs/nov25-comments-repair-results.json`.
