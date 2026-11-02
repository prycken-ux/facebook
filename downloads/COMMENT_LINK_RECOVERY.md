# Exact video lookup and comment recovery

Uploader 2.47 / new-batch workflow 2.1 / comment workflow 1.4.

The supplied Oct-31 report contained eight confirmed published jobs whose comment
step skipped because no exact video permalink was saved. All eight timeline ARIA
snapshots still contained Loading articles. The future-batch path previously
stopped immediately when the saved link was absent.

The uploader now captures fresh receipt/Story links before archiving. Missing
links trigger a bounded timeline lookup: exact author identity, complete caption,
absolute publication time within the recorded task window and one canonical video
ID. It waits for loaded posts, expands only the matching caption and can inspect a
fresh timestamp tooltip. Duplicate matches, unfinished matching cards, stale
tooltips and nested shared videos do not authorize a comment. Only filtered lookup
counters and canonical links are written to diagnostics; no raw API payloads or
cookies are stored. Expanded Reel author labels are accepted only with the exact
owner profile URL. Existing Facebook-attribution URL normalization is retained.

`repair_oct31_published_comments.py` is a Nov-2-only comments repair. It validates
the original 30-job Oct-31 manifest and reads current publication state. It selects
only confirmed published jobs; excluded accounts, unconfirmed video results and
any sent/sending/verifying/needs_review comment ledger entries remain protected.
It never calls video upload code. It attempts at most three safe candidates to
obtain one actual comment seen after a reload before proceeding with the remaining
eligible comments. Any unknown send outcome stops this initial gate. The older
standalone fb06 comment is not marked or resent. No Notepad or CSV output is used.

The generic automatic retry remains one recoverable BEFORE-Post retry per exact
media job, reserved durably before browser actions. Successful, submitted or
unknown-outcome jobs do not reenter the queue. New records now retain their exact
source-manifest retry binding, and text results identify the used opportunity.
The repair runner audits the existing queue claims and publication receipts. An
installation screenshot or a manual fixed-list retry is not evidence of an actual
generic automatic retry succeeding. The audit never resets claims or starts a
video retry.

Validation: 117 local checks passed, including Chromium fixtures for delayed
Loading articles, exact matching, ambiguous matches, scoped caption expansion,
fresh/stale timestamp tooltips, send-and-refresh persistence and non-persistent
comment deduplication. The real core retry-intent/archive test also verifies the
new source-manifest binding. These are local tests, not a claim that Facebook
production comments or an automatic retry have already succeeded on Windows.

The installer verifies an immutable package hash, acquires the existing global
lock, backs up and atomically replaces only eleven Python modules, clears their
exact bytecode caches and rolls back on errors. It preserves all media, captions,
publication/comment journals, retry claims, account config and browser profiles.
Installation alone sends nothing. A separate fresh Python process runs the
comments-only repair on the original Windows computer.
