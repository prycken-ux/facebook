# Immediate verified comments on each newly published video

New-batch workflow 2.3 / retry integration 1.1 / uploader 2.47 protocol plus
IMMEDIATE_COMMENT_VERSION=1.0-receipt-first-reload. The user requested moving the
comment to immediately after each video's successful publication. The two old
fb10/page07 and page08 jobs are not queued or modified by this update.

The new-batch entry freezes only fresh eligible media, excluding validated older
frozen jobs. It enables immediate-after-publication-v1 on that manifest. Each
confirmed successful video saves the exact fresh receipt link before archival,
keeps the same browser open, sends its bound authorized top-level comment and
reloads that exact video to verify retention before proceeding to the next file.
It retains the existing duplicate-send ledger, author/session checks and exact
comment text. A comment failure never makes a successfully published video a
video retry candidate. Unknown video outcomes receive no comments or reposts.

The first-pass queue is followed by the existing durable one-time recoverable
before-Post retry. New immediate manifests propagate the timing into this retry,
so its successful videos also comment immediately. Legacy deferred manifests keep
their prior behavior; no historical batch is migrated or scanned. The new entry
has no bulk-backfill phase. Account exclusions fb16/fb18/fb21, existing-caption
preference, saved common-caption fallback and text reports are unchanged.

Fresh link timing can reduce failures caused by closing the publishing browser
and later reopening a profile stuck at Loading. It does not guarantee Facebook
will expose a usable link or comment editor. Missing exact targets and security or
identity errors remain safe manual-required outcomes. A same-episode comment seen
only optimistically is not called successful; the existing refresh receipt is
required. Exact lookup results from Reels/video tabs are now also accepted by the
existing verified-link validator, fixing a missing method-whitelist entry.

Local Chromium fixtures exercise real Post-intent persistence, a fresh UI receipt,
exact link capture, full comment text, persisted send, refresh verification and
same-browser completion without reopening the timeline. They also exercise a
nonpersistent optimistic comment, an unavailable comment handler and an unknown
video outcome. The retry integration test enforces video/comment/video/comment
order and the one-retry cap. Other checks cover intent deduplication, old-record
protection, source/caption/config binding and legacy deferred flows. These are
local tests, not evidence that a production Facebook comment already succeeded.

The standalone verified installer only updates five code modules using the
existing global lock, backups, atomic replacements, exact bytecode-cache clearing,
fresh-process verification and rollback. Publication/comment/retry ledgers,
accounts, captions, media and browser profiles are preserved. Installing this
update alone performs no upload, retry, comment send, marking or old-job lookup.
