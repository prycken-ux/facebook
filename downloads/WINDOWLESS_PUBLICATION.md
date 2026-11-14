# Windowless Chrome for existing publication flows

The normal Chrome launcher can read `browser_run_settings.json`:

```json
{"schema":"facebook-browser-run-mode-v1","mode":"background"}
```

`background` starts the existing account profile with Chrome's supported `--headless=new`, a 1440×1000 window size, and the same loopback-only CDP connection. It retains the configured profile, extensions and proxy settings. An extension that requires a visible authentication popup may need manual attention; there is no automatic visible-window fallback. The Windows profile-check and graceful-close PowerShell helpers use `CREATE_NO_WINDOW` to avoid console flashes.

Missing settings preserve the former foreground behavior. Invalid settings stop before launching Chrome. To restore visible mode, change only `mode` to `foreground` while no publication task is running. Do not edit frozen manifests, publication state or comment receipts.

`browser_background_mode_installer.py` verifies a pinned four-module package, refuses a live/unknown publication lock, backs up changed modules and settings, and rolls back on failed fresh-process import verification. It then starts the existing Nov14 continuation of original Nov13 footage with closed stdin, so a hidden account needing manual input is recorded by the per-target error handling. No new material is selected. Successful, submitted and commented state is preserved by the original continuation guards. The preference persists for subsequent flows that use `normal_chrome_batch`.

The progress console may be minimized; closing it can interrupt publication. Avoid opening a login shortcut for the profile currently being used. If switching an active foreground run, first press Ctrl+C normally and wait for it to exit. Never launch a second publisher concurrently.

Validation: mocked Windows process/rollback tests and a real local Linux Chromium CDP test for windowless startup, profile-cookie persistence and both original-file picker paths. No live Facebook posts were made in testing. Windows profile/proxy compatibility is checked when the user runs the command; it is not inferred from the local browser test.
