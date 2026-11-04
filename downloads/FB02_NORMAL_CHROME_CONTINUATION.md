# Continue fb02 using the working normal Chrome startup

Live user evidence: the guarded fb02 publication stopped during read-only
preflight with ERR_PROXY_CONNECTION_FAILED and no video selected. The subsequent
normal Chrome launch with the same fb02 profile visibly loads the Donna Merrill
Page. The manual open command itself only opens a browser and does not upload.
The exact network/proxy root cause is not established by these screenshots.

This standalone continuation checksum-loads the unchanged original single-job
runner from 04acb09. All original November 3 aa7a3134 source checks, exact 2.mp4
and caption checks, historical fb02 pause provenance, single grant, Post intent,
receipt timeout and repeat protections remain in the original runner. It only
replaces the fb02/page01 launch function for the current process and restores it
in finally. No installed upload core or proxy configuration is overwritten.

Chrome starts as the normal login launcher with the existing profile directory,
Default profile and existing extensions/proxy behavior. An ephemeral local-only
CDP endpoint permits the existing verified publisher to control this owned
browser. Endpoint metadata is validated and never printed; stdout/stderr from
Chrome are suppressed. Proxy credentials, cookie values and local control URLs
are not logged. Context closing sends graceful Browser.close and uses the same
exact-profile window closure helper; no process is force-killed. Browser warmup
may retry only read navigation for specific connection errors, before selecting
any video. The usual owner, file, caption and final identity checks still apply.

Local validation includes real Chromium CDP connection, DOM control and graceful
closure, normal startup flags without disabling extensions/sandbox, loopback-only
addressing, metadata validation, sanitized connection errors, scoped override
restoration, and all existing single-job real-core intent/receipt/archive tests.
These tests do not assert live Windows or Facebook publication success.
