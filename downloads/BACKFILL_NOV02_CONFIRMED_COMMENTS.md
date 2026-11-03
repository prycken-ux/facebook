# Nov-3 authorization: comments on confirmed successful Nov-2 videos

The user explicitly requested comments on yesterday's already published videos.
Scope is the original 30-job Nov-2 f6cc163c batch, excluding fb02/page01 (unstarted),
fb04/personal (before-Post failure) and the two held fb10/page07 and page08 jobs.
Only the remaining 26 original jobs are offered for comments; no inbox scan, video
upload, republish, media archival or automatic retry is invoked.

The user's existing thirteen explicit success confirmations (including the earlier
fb07 correction) are recorded if still pending, with exact source key-prefix,
target/URL/filename binding, backups, original Post time and user provenance.
The other candidate jobs must already be recorded published. The program never
promotes an unconfirmed outside job into a new comment target.

An existing exact-job permalink is reused. A missing binding may be restored from
a manual-required, unsent comment ledger item only if job key, author target,
authorized text hash and a recognized link-proof method all match. Unknown send
states and already confirmed comments are protected. Bound links are prioritized;
other candidates use the installed exact owner/full-caption/task-time/video-ID
lookup. All candidates are processed independently: a lookup failure is reported
and does not stop the remaining accounts.

The existing daily.backfill engine is called only with this source subset and
future_only=True to require comment refresh verification. It saves sending intent
before a click, deduplicates by task/text and canonical video permalink, and never
resends an unknown outcome. The exact previously approved product comment is used.
Failure of a comment preserves the video's published status. The original report
is refreshed without dropping attempt history; the comments-only summary is text
and private JSON under logs, with no CSV or Notepad.

The launcher downloads immutable, SHA-256/AST-verified programs first, performs
only proven-abandoned-PID lock recovery, checks the installed comment feature in a
fresh process, installs the previously authorized immediate-comment update only
if needed and launches this comments-only script in a separate fresh interpreter.
No current-day publication or older Oct-31 repair entry is called.

Local checks cover exact 26-job scope and four exclusions, source/comment tampering,
exact unsent-ledger link restoration, protected sent/unknown ledgers, all-candidate
continuation, unchanged media/config/retry journals and existing Chromium send-and-
reload behavior. These local checks do not claim production comments were sent.
