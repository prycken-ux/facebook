# Repair Nov23 caption failures and proven fb09 before-browser failures

The reviewed Nov23 video-only report confirms 0 publication receipts, 33 pre-Post failures, 16 submitted outcomes requiring review, and 11 unstarted targets. Thirty failures are `Locator.input_value` on a contenteditable Describe your reel field. fb14 has a pre-Post interruption/MemoryError; fb32 and fb52 require login/security checks. The 11 unstarted targets are fb09 personal and page01–page10, blocked by an old Chrome profile owner. Missing publication receipts are not proof the 16 submitted videos failed.

The pinned original package contains the old `input_value` reader. The new immutable cache overlays the tested 1.1 recovery module, which reads native editor value or contenteditable innerText and still verifies that closing a known audience prompt preserves the exact caption/editor. Root uploader files are not overwritten.

The uploaded report is bound by exact SHA256 and original request SHA. An immutable local baseline copy is retained before the normal video report updates. Candidate scope is at most 42 jobs: 30 caption failures, one fb14 before-Post interruption and 11 fb09 jobs. Current state, source binding, video and caption identity, nested submission evidence and live paused accounts are checked again. Login failures and submitted/unknown results are preserved.

The fb09 helper allows only an exact-profile, old headless Chrome with no visible window, no active fb09 preparing/posting record and no other project Python worker. The current helper/venv/bootstrap ancestor chain is validated using the existing classifier, creation times and command hashes. Process handles, creation identity and owner are rechecked before terminating the old browser. Normal, newly launched, changed or unrelated browser owners are retained; in that case fb09 is skipped while other eligible jobs proceed.

An absent fb09 state is reconstructed as failed_before_post only when both original first-run and original automatic-retry attempts prove the browser was never launched. The retry claim must bind the same original source and contain no original publication record, no comment ledger can exist for that video, and all available relevant attempt/receipt evidence must be free of submission clues. Reconstruction is backed up with its proof; there is no inference from absence alone.

Publishing reuses the original durable extra-before-Post repair grant. Original automatic retry claims are not reset, consumed repair claims are preserved and each repair job gets at most the existing grant's single attempt. Current source-bound validation is retained. Comment entry text and immediate flags are suppressed at the upload boundary; pending lookup, backfill, comment retry and read-only reconciliation are disabled for this repair. Original caption, real-footage AI OFF and paused34 policy remain. This entry never retries the 16 submitted videos.

Startup acknowledgment: `已确认23号修复补发进程`.
Progress: `logs/nov23-caption-fb09-repair-run.log`.
Status: `logs/nov23-caption-fb09-repair-status.json`.
Final report: original video-only report path, updated from actual current video state.

Validation: 35 real-browser tests passed for caption/audience controls and caption preservation, and 36 tests passed for repair scope/proofs, orphan-process safety and the prior video-only policy. Fresh download/import confirmed the old pinned package contains the bug and the final cache overlays the fixed reader. Live Windows cleanup/publication remains pending starter execution; tests do not establish publication success.
