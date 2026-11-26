# Register the user's ten Instagram account mappings

The user reports ins01–ins10 already logged in and supplied all ten profile URLs. This replaces the earlier tentative ins01=faithdjurner96 mapping: ins01 is ted47868. faithdjurner96 has no slot in this ten-account list. Account type evidence for faithdjurner96 does not establish the type of any newly listed account.

Run the pinned `register_instagram10_accounts_20261126.py` with the existing `E:\IG-AutoUpload` workspace on the original Windows computer. The script backs up and merges `instagram_accounts.json`, records user-reported login separately from verified browser identity, and writes a dated CSV and registration report. It requires all ten existing profile/media directory bindings and workspace ownership to match; it does not create/reassign profiles or read credentials. Existing captions/comments and browser sessions remain. A different identity on an already enabled slot is rejected. Repeat registration preserves existing verification for an unchanged identity.

No browser is opened/closed or identity-checked by this script. No video/comment is uploaded. The automation uses independent IG videos and the existing FB caption/first comment. Browser actor verification and a real first-video/first-comment check remain necessary before enabling publishing. No Meta app/OAuth or linked FB Page is required for this chosen browser workflow.

Cloud registration is not Windows execution. `instagram10_user_mapping_20261126.json` is a user-supplied expectation, not proof of authenticated session identity. The real Windows result is `E:\IG-AutoUpload\logs\register-ins01-ins10-20261126.json`.
