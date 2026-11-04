# November 4 new video priorities and comments

The user requests November 4 new videos with existing same-stem captions first,
saved common-caption fallback, all uploads before one safe before-Post retry,
and comments last. Yesterday's batch had 16 confirmed videos but zero confirmed
comments; 15 comment jobs failed navigating profiles with connection-closed
errors and one was skipped. A subsequent fb02 ordinary Chrome window loads its
Page while the earlier default automated launch fails proxy preflight. This is
live evidence of a startup-path difference, not proof of a specific proxy cause.

This package retains the tested priority batch runner and immutable job scope.
The November 4 wrapper binds all browser sessions to the freshly frozen batch
owner URLs, and uses normal Chrome startup with the original profiles, extensions
and proxy settings through validated ephemeral loopback-only CDP connections.
The override covers upload, safe retry and comment stages and is restored on exit.
It changes no installed upload core, Windows proxy or account registration.
The fb16/fb18/fb21 exclusions and removed fb24-fb26 remain excluded by registration.

Fresh publication receipts are still captured and bound to each exact video key
before the browser closes. Uploads and their one safe retry defer comment sending.
Comments then use exact bound links first; missing links use the actual Reels tab
without depending on aria-selected, unique owner/caption/time/ID proof, or explicit
operator video selection. Existing strict comment owner/actor checks, durable send
intent, duplicate guards and reload verification remain. Comment failure never
turns a confirmed publication into a failed video. Historical video/comment jobs
are outside this new batch. An active earlier job remains blocking via PID locks.

Real-footage confirmation is required for the November 4 batch; absent a chat
confirmation the starter obtains explicit REAL input in the local console before
starting. No prior batch's footage declaration is reused. Resume preserves the
same dated batch, first-pass attempts and once-only retry claims.

Validation covers real local Chromium CDP control/closure, scope restoration,
normal browser arguments, source owner allowlists, captions/previous-plan exclusion,
phase order, retries and unknown outcomes, exact Reels target checks, guarded
comment send and reload verification. This does not assert that any November 4
video or comment has already been posted on the user's Windows computer.
