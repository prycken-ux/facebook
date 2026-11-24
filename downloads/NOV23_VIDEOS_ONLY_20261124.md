# Continue Nov23 videos without comments

The user canceled comment work for the original Nov23 allocation because lookup and commenting were too slow. This entry stops the verified Nov23 comment supervisor and its owned worker descendants, then resumes the same source-bound video workflow with the existing caption, real-footage AI OFF setting and paused34 accounts.

Source and existing authorization are validated before stopping anything. The stop helper reads the current supervisor status; it requires the exact known immutable cache path and driver SHA256, matching root argument, source date, creation time and freshly rechecked run/PID identity. It pins process handles before ending only the supervisor and its verified descendants. Unrelated Chrome and project tasks are preserved. Closing the original supervisor also closes its Windows Job Object and stops the contained worker. Unknown processes are retained and no second publisher starts.

The video workflow runs original publication and the original durable single safe pre-Post retry phase. Consumed retry claims are not reset, and submitted/unknown videos are never reuploaded. Comment phases, pending-video comment lookup, backfill and automatic comment retry are disabled. The upload boundary removes both authorized-comment text and immediate-comment flags and forces deferred mode, preventing publication-time comment link collectors and sends. Original frozen manifests, caption/content hashes and comment ledgers stay intact.

The new mode is recorded in `logs/nov23-videos-only-policy.json` bound to the original request and stage hashes. A video-only report evaluates video completion independently of comment status; it does not mark comments successful or rewrite publication records. This change applies to Nov23 only.

Windows startup acknowledgment: `已确认23号仅视频后台进程`.
Progress: `logs/eligible60-2026-11-23-videos-only-run.log`.
Status: `logs/eligible60-2026-11-23-videos-only-status.json`.
Report: original controller stem plus `-videos-only.json` and `.txt`.

Validation: 15 tests passed, covering comment suppression at the upload boundary, absent lookup/backfill/retry execution, video/safe-retry-only phase selection, completion with no comments, preserved state/paused accounts, source preflight before stopping, original worker-check binding, exact supervisor-tree termination with unrelated processes retained, recycled/unknown PID rejection, runtime hashes and launch-specific acknowledgment. Fresh pinned original19-module package import and Nov23 content/scope checks passed. Real Windows switch still requires running the verified starter; repository tests do not prove a live task was stopped or a video published.
