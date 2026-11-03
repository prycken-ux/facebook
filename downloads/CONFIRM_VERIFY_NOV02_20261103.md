# Confirm the user-verified Nov-2 successes and verify only fb10/page07 and page08

The user confirmed that twelve of the fourteen previously unresolved Nov-2 jobs
were actually published, and separately had already confirmed fb07/personal. The
user then explicitly requested verification and success marking. These thirteen
jobs are bound to their original Nov-2 f6cc163c manifest key prefixes and targets;
they receive a user-confirmed publication provenance, not an automatic receipt.

Only fb10/page07 (8ae46e51b98e) and page08 (32a7138d90cb) receive online verification.
These are the Nov-2 submitted files, not the older Oct-31 jobs on the same Pages.
The existing exact author/full-caption/task-time/video-ID lookup checks the profile
and bounded alternate Reels/video tabs. The final direct video page must retain
the same canonical video ID and show the exact owner profile before status changes.
Loading, ambiguity, changed records or owner mismatches leave the record pending.
Online-confirmed provenance and the exact bound permalink are stored separately
from user confirmation. No missing published_at timestamp is invented.

A unique checksum-validated original 30-job text-report manifest and matching source
report are required. The updater holds the existing uploader locks, backs up the
publication state, source manifest and previous reports, and preserves each changed
record's prior value in an audit. Confirmed records are idempotent. The current text,
JSON and ZIP summary is refreshed with original attempt history retained. Comments,
automatic retry claims, account configuration, inbox/completed files and unrelated
records are unchanged. Only the exact fb10 profile is gracefully closed for a
persistent-context read; an active preparing/posting task blocks that inspection.
No uploads, republishing, media moves, comment sending, CSV or Notepad is invoked.

Five focused tests cover user versus online provenance, expected 28/26 success
counts depending on proof, unchanged other records/config/comment/retry ledgers,
source tampering, malformed record/time, final owner/direct-link binding, backups,
report refresh and idempotence. Existing alternate-tab browser fixtures are also
run. All are local tests, not evidence that the Windows online checks already ran.
