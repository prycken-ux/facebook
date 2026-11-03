# Nov-3 authorization to retry six Nov-2 before-Post failures

The user supplied the complete Nov-2 30-job report (batch f6cc163c) and explicitly
requested retry of its publication failures. Scope is exactly fb01/page01,
fb03/personal, fb04/personal, fb05/page01, fb06/page01 and fb10/page01, bound to each
reported original filename and key prefix. The user subsequently confirmed fb07
was actually published; it is excluded. fb02/not-started, all unresolved submissions,
all other successes, Oct-31 jobs and today's new media are also excluded.

This standalone runner executes only on Beijing Nov 3 with installed core 2.47.
It does not install/alter the uploader. It requires a unique checksum-validated
Nov-2 original manifest, exact source report rows, unchanged target configuration,
full video key, caption bytes and caption text. Existing Post/success evidence,
unknown outcomes, prior retries/automatic claims or active tasks block the retry.
Published records are skipped without requiring already archived media to exist.

A separate durable six-job grant is reserved before any browser action, with a
backup of the original state. Neither publication records nor automatic-retry
claims are reset. The runner gracefully closes only the exact selected account's
Chrome window, checks the original network/profile in a fresh browser and uses
only the existing known identity-switch workflow. A proxy/tunnel failure gets
one extra read-only profile navigation; proxy settings and security settings are
never changed. Failed environmental checks consume this grant and skip the item;
the console distinguishes these from an attempted upload.

Each successful preflight uses the real existing upload core with exact filename,
full expected job key, AI off, before-Post retry mode and deferred comments. The
core saves Post intent before the click and retains its three-minute receipt
limit. Any unknown outcome remains protected. Only newly successful jobs from
these six are then passed to existing deduplicated, refresh-verified comments.
The original 30-job report and all unrelated ledgers remain untouched. A new text
summary and private JSON/ZIP are written under logs; no CSV, table or Notepad.

Seven focused tests and nine existing automatic retry tests passed locally.
Coverage includes exact source scope, changed material/config, prior Post/automatic
claims, reservation before failed preflight, real core intent and archival for
only the six jobs, rerun idempotence, receipt timeout protection, unchanged unrelated
records and read-only proxy preflight retry. These are local tests; they do not
claim that the Windows/Facebook republish has already happened.
