# Instagram ten-account browser trial — 2026-11-27

The user authorized independent IG material allocation and video/first-comment publication, chose the source folder at runtime, and confirmed all real footage with AI labels OFF. Existing registered windows are E:\IG-AutoUpload\profiles\ins01–ins10. Use the FB Python virtual environment only as an interpreter; all new command lines end in E:\IG-AutoUpload so the separate FB supervisor can recognize IG processes. No FB profile, window, task, source video or publication ledger is changed. Only signed FB allocation hashes may be read to exclude a clip already assigned to FB.

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

Run the pinned starter with the existing E:\IG-AutoUpload workspace. It opens a folder picker for the source on first allocation. A flat folder supplies ten distinct, naturally sorted eligible clips, one per slot. Alternatively provide all ten insXX subfolders, each with its own clip (an inbox subfolder is supported). Extra clips and every source original remain. The immutable ten-file mapping and completed pointer are recorded under material-staging. Rerunning uses the same batch and never silently substitutes a new source. New allocation is Nov27-only; the existing frozen batch can resume across midnight.

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
