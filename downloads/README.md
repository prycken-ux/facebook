# Windows Facebook uploader

Download `fb-local-upload.zip` and extract its files into `E:\FB-AutoUpload`.

Preserve existing `.venv`, `profiles`, and `videos` folders. Read the included Chinese instructions and run `prepare` before enabling publication. The package uses local Chrome browser login; it includes no passwords, cookies, or access tokens.

Browser interaction must be validated on the local Windows computer. The recorded personal profile workflow is available from version 2.4, with separate identity checks and a required local prepare step.

Existing installations can apply `fb-upload-v2-3-fix.zip` without replacing configuration, login profiles, publishing state or videos. Version 2.3 checks the current local Page actor identifier, with a scoped Page header management control fallback when the identifier is unavailable. A conflicting actor stops the operation. Run `batch_upload.py check-identity --accounts=...` before resuming any uploads. Old `needs_review` records remain blocked for manual reconciliation.

For personal profiles, apply `fb-upload-v2-4-personal.zip`, close any automated Chrome windows using those profiles, and run `setup_personal.py`. It reads the existing local `account_registry.json`, backs up configuration, and adds disabled personal targets without changing public Page targets or publication state. Place MP4/TXT pairs in `videos/<account>/personal/inbox`, then run `fb_upload.py prepare --account <account> --target personal`. Validate each account before enabling or publishing. Public audience and the requested AI switch are checked. If a short profile URL cannot be verified as the logged-in user's own profile, the uploader stops before selecting a video.

Validation for version 2.4: 56 Python tests passed, including local Chromium fixtures for personal upload controls and identity mismatch handling; 8 receipt observer scenarios passed. These fixtures do not establish that personal publishing has succeeded on a real Facebook account. The uploaded recording stopped before Post; an actual Windows prepare and subsequent publication receipt remain required.

Version 2.5 (`fb-upload-v2-5-identity.zip`, or just replace `fb_upload.py`) fixes short personal profile URLs blocked when Edit profile is hidden. It verifies the target against Facebook's `/me` profile redirect and the unchanged local personal login identity. Numeric redirects require a matching actor and canonical profile URL. Configuration and publication state are preserved; rerunning setup is unnecessary. Fourteen personal browser/queue tests passed, including missing Edit profile, mismatched owners with the same name, numeric redirects, and login changes during verification. Actual personal posts without a captured receipt must still be confirmed using the verified Reel URL rather than retried.
