# Open fb01 using its original Chrome profile

The fb01 shortcut can fail when a windowless Chrome still owns its original profile. This helper checks the live profile owner rather than using a PID copied from a screenshot.

- Restore an existing visible fb01 window, or request a window from an idle normal Chrome.
- Close only an exact-profile, identity-checked, headless browser that predates all current project Python workers and has no active fb01 preparing/posting record; an orphan browser with no project worker may also be released for manual review.
- Refuse ambiguous or active ownership. Recheck ownership and process identity immediately before closing, then confirm a visible normal window after launch.
- Use the existing `profiles/fb01/Default`; preserve login data, extensions and configured profile proxy. Do not create replacement profiles, delete profile locks, alter publication records, stop other account browsers or restart publishing.
- Cache a SHA-verified PowerShell helper and a unique diagnostic output file. No upload application source is overwritten.

Run the Python starter on the original Windows upload computer with `E:\FB-AutoUpload` as its argument. Runtime output, not this repository test result, determines whether the window actually opened.

Validation: 14 tests pass, including actual PowerShell guard logic with mocked process records, exact-profile matching, venv-parent handling, stale versus active ownership, PID identity mismatch, and embedded-script integrity. Real Windows Chrome/window behavior still requires running the helper on the upload computer.
