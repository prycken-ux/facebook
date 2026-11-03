# November 3 publication priorities

The user confirmed all November 3 footage is real and explicitly requested all
uploads first, one safe retry second, and comments third. The new priority runner
freezes only the new batch, excludes old frozen plans and known jobs, preserves
nonempty same-stem TXT captions, and fills missing captions from the saved common
caption. fb16/fb18/fb21 remain excluded and AI labeling is off for this batch.

Both first-pass and retry uploads defer comments while retaining fresh exact
publication links. Post intent remains durable before clicking and receipt wait
remains at most three minutes. Safe retry keeps the original once-only claims
and exact frozen keys, never retries submitted/unknown or security/identity
failures, and now also recognizes proxy connection failures and timeout failures
at specifically known pre-Post UI stages. Unknown/after-Post timeout stages remain
ineligible. Old retries and comment claims are not reset.

Only after both upload passes does the runner send comments. Exact fresh links
are preferred; otherwise it clicks the actual profile Reels tab, collects links
independently of aria-selected, and requires a unique owner/full-caption/time/ID
match. Ambiguity uses operator selection via browser/Enter or a pasted URL; S
skips and Q stops. The existing guarded sender and reload verification remain
responsible for success. Comment failures do not change publication success.

A dated durable pointer resumes the same batch rather than freezing another.
The optional scheduler resume mode loads validated attempt history under the
uploader lock and skips first-pass jobs already attempted. The second pass keeps
the one-retry ledger. Existing scheduler callers retain their original behavior.

Targeted tests cover phase ordering, caption priority, previous-plan exclusions,
resume attempts and pointers, fresh receipt capture and deferred sends, retry
claims and proof blockers, UI metadata and ownership, and reload verification.
Local fixtures do not claim any live Windows or Facebook publishing occurred.
