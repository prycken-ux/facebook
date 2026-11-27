# Instagram ten-account browser trial — 2026-11-27

The user authorized independent IG material allocation and video/first-comment publication, chose the source folder at runtime, and confirmed all real footage with AI labels OFF. Existing registered windows are E:\IG-AutoUpload\profiles\ins01–ins10. Use the FB Python virtual environment only as an interpreter; all new command lines end in E:\IG-AutoUpload so the separate FB supervisor can recognize IG processes. No FB profile, window, task, source video or publication ledger is changed. The latest user authorization explicitly allows this IG batch to reuse FB material. The allocator does not read or exclude FB history; IG submission/comment protections remain authoritative.

Expected authenticated users in slot order:

| Slot | Username |
| --- | --- |
| ins01 | ted47868 |
| ins02 | jenniferriffin45 |
| ins03 | ha.rper9090 |
| ins04 | ivy800550 |
| ins05 | sophia5095091 |
| ins06 | daisybreeze8838 |
| ins07 | ethan400560 |
| ins08 | dylan159851 |
| ins09 | zachary29692 |
| ins10 | alixla2762 |

## Running

Run the pinned starter with the existing E:\IG-AutoUpload workspace. It opens a folder picker for the source on first allocation. The selected total folder and its subfolders supply ten distinct, naturally sorted eligible clips, one per slot. Existing insXX/inbox groups are preferred for their matching account, but they are not required: reserve the matching groups first, then fill any empty slot from remaining eligible clips elsewhere in the chosen total folder. Incomplete groups no longer fail if the total pool has enough distinct clips. Extra clips and every source original remain. The immutable ten-file mapping and completed pointer are recorded under material-staging. Rerunning uses the same batch and never silently substitutes a new source. New allocation is Nov27-only; the existing frozen batch can resume across midnight.

The starter expands only seven hash-checked files into a versioned tools cache, validates workspace ownership/mapping/exact original FB caption and corrected first comment, and checks the existing Playwright installation. It does not install third-party binaries or transfer credentials. Each slot uses its original Chrome user-data directory with its existing proxy/extensions/session. Only the selected slot's windows are normally closed before its operation. A background Chrome process is terminated only after matching the precise IG profile, unchanged process command/creation time, an opened process handle, and two checks that no visible modal/window remains. Other IG and all FB profiles are excluded. Active unrelated IG Python work blocks the release. A visible modal that resists normal close is preserved and that operation fails before upload.

A separate coordinator acknowledges startup and opens a live log viewer. Returning to PS> or closing the log viewer does not stop the background coordinator. Named mutexes prevent duplicate allocators/publishers; a duplicate launcher opens the existing log. State reads use Windows sharing including FILE_SHARE_DELETE, with bounded retry, to avoid the previously observed FB atomic-state replacement failure.

## Publication and proof

- **First trial gate:** ins01 alone must obtain the exact published video and a refreshed own-comment proof. Only then do the remaining nine slots proceed automatically. If the trial fails, it preserves all submission evidence, leaves the other nine unstarted, and exports diagnostics. Repeating the entry does not clear this gate or reupload the uncertain video; diagnose and release a reviewed fix first.
- Video and comment operations have separate **180-second total budgets**, including profile release and browser preparation, with a 15-second heartbeat during the worker. A suspended child is placed in a private Windows Job before any Python/Chrome descendant starts. Timeout stops only this operation's job; it does not kill all Chrome/Python or reset the timer after Share. Cleanup may add up to ten seconds for descendants to exit before the next operation. One recorded safe pre-Share retry is allowed for specified transient failures.
- Actual logged-in username must match the slot. The browser's authenticated current-user response or a unique own-profile navigation element supplies identity; opening the expected profile URL is not identity proof. Login/challenge/two-factor pages stop the operation without bypassing verification. No professional-account conversion, Meta app/OAuth, or FB Page binding is required by this selected browser route.
- Copy the full original caption and corrected first comment unchanged. Where the UI exposes an AI switch it must be verified OFF; if no disclosure control is exposed, record `not_exposed_no_self_label_added` honestly. Do not claim an unseen control was verified. Existing account privacy is preserved; this entry does not change a private account to public.
- Record intent before clicking Share and click return separately. Confirm a unique video only with owner, full caption, upload time window, new shortcode, video type, and matching video-detail author/full caption. Passive metadata reads are performed after request completion outside event callbacks to avoid blocking response-body reads. Never guess the newest post or use the shared notice alone as proof.
- The user's FB-style post-click timeout policy may record `assumed_published=true` only for an actual receipt timeout after Share returned. It does not fabricate a video URL/ID, receipt or comment success, and cannot satisfy the first trial gate. All submitted/uncertain/confirmed tasks remain protected against another upload.
- Comments target the proven exact video. Persist comment intent independently in both ledgers before sending; uncertain sends are not repeated. Detect an existing own original comment, then require it after page reload. The same original comment on another account/video cannot satisfy this task. A label such as `sent` without reload proof does not pass the gate.
- Once both proofs pass, move only this assigned copy from inbox to published; retain the source original. No cleanup/deletion of old source videos is part of this entry.

## Results and troubleshooting

Live log: `E:\IG-AutoUpload\logs\ig-2026-11-27-run.log`.
State: `ig-2026-11-27-status.json`; ten-row results: `ig-2026-11-27-results.json` and `.txt`. Video state, assumed-by-policy counts and verified comments are separate. Normal completion or a held first trial creates `IG-publish-check-20261127-<id>.zip` on the Desktop (logs fallback) containing results, sanitized per-operation diagnostic text/screenshots, own ledgers and bounded operation logs. It excludes login profiles, cookies, credentials and source videos. Screenshots are captured only after the slot's identity was verified.

Twenty-five checks passed locally. These checks run locally against fixture configuration, simulated processes, and real headless Chromium with all Instagram traffic intercepted by test HTML/JSON. They demonstrate mapping, copy/source protection, identity refusal, AI/comment switches, exact metadata filtering, real DOM upload/comment/reload flow, first-trial gating, replay protection, contained deadlines and PowerShell release guards. **They are not proof of compatibility or publication success on the user's live Instagram UI.** The Windows acknowledgement, actual first video URL and refreshed own-comment result remain to be observed.


## Allocation failure correction after the first Windows attempt

The Windows screenshot shows three stops with `IG新素材不足10条，或编号ins03没有未分配视频；正式目录未复制`. This is evidence that the allocator stopped before formal copies/publication; it does not show the chosen source path or prove the pool is insufficient. The old allocator only read one directory level and required every detected insXX group to supply its own clip. Both limits are corrected by recursive total-folder scanning and account-first reservation with surplus filling. Existing immutable allocations and post/comment ledgers remain authoritative and are never reset/rescanned.

Before copying, print counts of discovered video files, distinct eligible clips, byte-identical copies, previous IG allocation, unsupported formats and unreadable files. Detailed per-file reasons and the chosen source path are saved in `logs/ig-material-scan-20261127.json` and `.txt`. If fewer than ten eligible distinct clips remain, no allocation manifest/pointer or video copy is created, and no browser is launched; a Desktop `IG-material-scan-20261127-<id>.zip` (logs fallback) carries only these scan reports. Skip links/reparse points, workspace credentials/logs/cache, generated assigned copies and archived published/review/failed directories. Originals remain; within-IG and within-batch duplicate protections remain. This scan resolves nested/partial-group layouts. A subsequent Windows screenshot established the actual remaining blocker: 12 discovered clips, 10 excluded by the then-active FB-history filter and only 2 eligible. The explicit authorization below supersedes that filter.

Seven added allocation regression checks cover two top-level clips plus nested surplus (the ins03-style stop), incomplete account groups, reservation for later matching slots, complete-group compatibility, exact failure counts/scan archive/no-copy behavior, workspace/history/link exclusions and frozen-batch replay. The existing fixture coordinator and capsule checks continue to pass. Actual successful allocation/publication still requires the Windows execution result.


## Current Nov27 authorization: allow FB material reuse for this IG batch

The user explicitly authorized: “允许这批素材用于IG，同时保留‘同一IG账号不重复发布’和评论防重复规则。” This overrides the earlier independent-content requirement for this batch only. Remove FB-history hash scanning entirely; a damaged or inaccessible FB allocation report cannot affect this IG allocation. Scanner and manifest record `user-authorized-this-ig-batch-reuse-fb-material-20261127`; new manifests bind `fb_material_reuse={allowed:true,authorization:...}` into their digest. The scanner reports that FB reuse is allowed. It still rejects byte-identical within-batch candidates, protected prior IG allocations and generated copies, and still preserves all IG job keys, state ledgers, comment-send intents and the existing first-trial gate. No state/intent/gate is cleared to make the batch appear new.

Existing frozen manifests without the new optional reuse field remain valid and are not regenerated. The change only affects a not-yet-planned batch's eligibility; every frozen/submitted video and possibly sent comment retains its original identity and replay protection. The original caption/comment, real footage/AI OFF confirmation, exact ten mappings, per-operation 180 seconds and ins01 trial-before-other-nine rule remain.

Five additional policy regressions cover the exact 12-clips/10-FB-history scenario (all 12 eligible; ten allocated), no FB-history read/dependency even if its JSON is corrupt, preserved prior IG fingerprint exclusions, unchanged submitted-video/uncertain-comment ledgers (coordinator never invokes video upload for that task), and an older frozen manifest remaining byte-identical. Alongside the current 32 regressions the local total is 37 checks. These are fixture/browser tests, not evidence of actual Windows/Instagram publication.
