# Repair and retry the November 4 before-Post failures

The user supplied the November 4 d6707ad5 batch results: all 30 failed before
Post; 27 hit Playwright's remote-file transfer limit above 50MB and three had
file input timeouts/chooser failures. fb06/fb07/fb08 already used an automatic
retry. The user now explicitly requests another retry after repair.

The repair retains normal Chrome profiles, extensions and proxy behavior, but
sets the exact authorized local path through public DOM.setFileInputFiles. It
does not transfer FilePayload buffers, modify Playwright private colocation
flags, compress video, change the original file, or loosen owner/media checks.
Locator, ElementHandle and FileChooser entry points route only owned, batch-bound
contexts through the local setter; unrelated contexts use their original APIs.
The setter validates the exact inbox path, original job/content/config/caption
fingerprints, file size and owner, and marks the exact original input to resolve
one DOM node. Temporary method hooks are restored when the last context closes.

Before any new retry grant, the Windows runner opens an inert about:blank test
page in the first eligible account profile and exercises both locator and native
chooser selection with an original file above 50MB when available. Name, size,
first and last byte samples must match; no Facebook upload or Post happens in
this self-check. It creates no fixture/video copy on disk. A failed check stops
the batch before any original failure guard is replaced.

The dated November 5 runner accepts only the checksum-verified November 4
30-target frozen source. It preserves original media/captions/AI-off provenance,
old reports and attempts, and all prior automatic retry claims. Only exact
failed_before_post records with no Post/success evidence (including nested
previous attempts) qualify. Each receives one separately durable repair grant.
Prior failed retry flags are retained inside the original-record history rather
than granting another automatic retry. A crash before a new task exists can
resume; an actual new task consumes the repair grant, including unknown receipts.
Successful/submitted/unknown/active jobs are never reset or posted again.

All video attempts finish before comments on the original batch's successful
videos. Comments retain the exact-link-first lookup, actor/author checks, durable
send intent, duplicate protection and reload verification. November 5 new media,
November 3 unknowns and deleted fb24-fb26 are outside scope.

Validation reproduced the old 50MB failure on a real local CDP browser using a
64MiB file, then selected it through locator, element and native chooser APIs and
both original core Reels selection branches, checking full browser SHA-256 against
the original. It also covers on-machine self-check, modified/out-of-scope files,
context isolation/hook restoration, original retry-history preservation, all 30
real-core intent/archive paths, phase ordering, unknown receipt and restart guards.
Local fixtures do not claim live Windows or Facebook publication success.
