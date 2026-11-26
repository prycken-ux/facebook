# November 26 FB environment preparation

User scope: stop November 25 and earlier FB publication/comment/retry work, close FB account browsers, delete old FB media. No November 26 videos have been placed yet. Instagram is explicitly excluded. This entry does not allocate or publish.

Run `start_prepare_fb_for_nov26_20261126.py` from the existing Windows upload computer with `E:\FB-AutoUpload` as its only argument, using the pinned download/hash command supplied with the release. The installer contains its complete helper bundle, verifies immutable cache files and imports before running synchronously, and emits progress to the console and `logs/nov26-environment-prepare-run.log`.

Process termination requires exact pinned script contents/source date (including Nov25 resume scripts dated Nov26), command line and process creation identity. Unknown or current-day project processes block preparation. Old scheduled tasks are disabled only when every action matches old FB work. Mixed/unknown tasks are retained and reported. FB profiles are selected only by their exact project `profiles/fbNN` user-data directory. Visible windows receive a normal close request; a remaining visible window or modal blocks cleanup. Windowless roots are rechecked for identity and visible descendant windows before termination. IG profiles/processes are excluded.

Media deletion requires a signed historical distribution/frozen manifest with matching content, an uploader-generated batch prefix, or an explicit dated batch directory. Camera dates and modification times are insufficient. New/future manifests protect their content, even if old batches referenced the same bytes. IG paths, browser/login data, programs, text captions/comments and historical submission/comment ledgers remain. Unknown, linked, hardlinked, changed or busy videos are retained with an audit. Historical job rows are archived with previous statuses and submission evidence preserved; video and comment retries are disabled. Original state backups and per-file deletion journals are retained.

The existing fb32/fb52 login-abnormal exclusion is merged idempotently, preserving the earlier exclusions: 36 stopped accounts, 58 future eligible targets. This count is a planning baseline; new allocation must read the real current config.

Key evidence: `logs/nov26-prepare-plan-*.json`, `logs/nov26-prepare-windows-*.json`, `logs/pre-nov26-media-cleanup-*.jsonl`, `logs/pre-nov26-materials-ended.json`, `logs/materials-ended-through-20261125.json`. An incomplete Windows audit prevents all media deletion. Test results are local verification, not proof of execution on the user's Windows machine.

Browser occupancy/source isolation are addressed here. Facebook receipt delays, network/platform failures and comment location/refresh proof still require a real first-video/comment check when the new batch is authorized; cleanup alone is not a guarantee of successful publication.
