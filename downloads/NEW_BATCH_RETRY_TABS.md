# New batch publication with one retry and alternate comment lookup

Workflow 2.2, lookup 1.1; uses the installed uploader 2.47, comment workflow 1.4
and durable automatic retry queue 1.0 without resetting their records.

The Nov-2 user-authorized new batch is real footage. The runner uses AI off,
excludes fb16/fb18/fb21, includes fb10 personal and all ten Pages, preserves each
nonempty same-stem TXT and otherwise uses the saved common caption. It completes
all first-pass videos, makes one recoverable before-Post retry and then handles
comments with reload verification. Submitted/unknown outcomes are never retried.

New-batch freezing additionally excludes exact media keys from checksum-validated
previous-day frozen manifests, even if a task never created a publication state
record. This specifically prevents the Oct-31 fb02 unstarted file from silently
entering today's queue. New different bytes under an old filename remain eligible.
Historical manifests are read for exclusion only; no old job is executed or its
status rewritten. Same-day duplicate launches still rely on the publication and
retry journals; this update does not promise arbitrary interrupted-batch recovery.

The actual comment investigation found profile timelines staying at Loading.
When a production exact lookup cannot prove a unique video on the profile,
it now checks bounded Reels and Videos tabs. A standalone grid Video must carry
its own author ID, exact full caption, creation/publication time and explicit
published flag; parent captions, drafts, pending media, conflicting video IDs
and multiple matches do not authorize a send. Existing exact Story/UI proof and
comment intent/deduplication/reload rules remain in force. No newest-reel guess.

The installer only replaces four Python modules with immutable download hashing,
AST validation, existing locking, backup, atomic replacement and rollback. Media,
captions, account config, Chrome profiles and all publication/comment/retry journals
are preserved. Installation alone starts no task. The separately pinned Nov-2
entry runs the new-batch publisher in a fresh Python process after version checks.
No historical retry or comment-repair entry is invoked. Console text is used;
no table/CSV or Notepad output is introduced.

Local fixtures exercise a timeline that remains Loading while Reels supplies a
complete exact video proof, conflicting cross-tab candidates, missing publication
flags and inherited-caption rejection, plus exclusion of previously frozen but
unstarted files and acceptance of replacement bytes under the same filename.
These tests do not claim that production Facebook actions have already succeeded.
