# Windows Facebook uploader

Download `fb-local-upload.zip` and extract its files into `E:\FB-AutoUpload`.

Preserve existing `.venv`, `profiles`, and `videos` folders. Read the included Chinese instructions and run `prepare` before enabling publication. The package uses local Chrome browser login; it includes no passwords, cookies, or access tokens.

This is a first implementation of the recorded public Page workflow. Browser interaction must be validated on the local Windows computer. Personal profile posting is not included.

Existing installations can apply `fb-upload-v2-3-fix.zip` without replacing configuration, login profiles, publishing state or videos. Version 2.3 checks the current local Page actor identifier, with a scoped Page header management control fallback when the identifier is unavailable. A conflicting actor stops the operation. Run `batch_upload.py check-identity --accounts=...` before resuming any uploads. Old `needs_review` records remain blocked for manual reconciliation.
