# Three additional personal login profiles

The user requested three additional existing personal Facebook logins and video
publication integration. The fixed personal-20261104-three onboarding batch
reserves the next three unused fbNN numbers by examining current registration,
profiles, video folders and shortcuts; on the existing fb01-fb23 installation
these will normally be fb24-fb26. Existing data is never adopted or overwritten.
Repeating the same batch resumes the same slots and preserves local sessions.

The controller creates independent login shortcuts/folders, opens one account at
a time for the user to log in, and asks for that person's profile name and URL
in the Windows console. It gracefully closes only that profile's window and
reopens it to check the current personal actor and target owner with the existing
identity verifier. It rejects duplicate owners before registration. An invalid
name, URL, session, Page actor or network failure does not register/enable an
unverified new target. S skips an account and Q preserves progress and exits.
Passwords and OTPs are entered only into Facebook by the user.

Verified mappings are registered and enabled with identity verification
provenance. No prepared-at/media-preview result or publication is fabricated.
The first real video publication still executes all normal media, caption,
audience, AI label and final actor checks. Activation backs up and rolls back
config and onboarding manifest on failure. Existing profiles, account mappings,
publication/comment records, retry claims, captions and video files are retained.
No video is uploaded by onboarding and no scheduled task is created.

The scheduler retains the existing fb01-fb23 behavior and exclusions of fb16,
fb18 and fb21. Higher-numbered accounts are eligible only as personal targets
with a matching verified registration and publishing-ready marker. The same
owner check handles frozen retry jobs which omit type/workflow fields, so both
primary upload and the existing one-safe-retry workflow can include the new
personal accounts. Historical 30-target manifests and fixed-date scripts retain
their original scope.

Local tests validate allocation/resume without session replacement, exact owner
activation, duplicate and wrong-owner refusal, rollback, console stop/skip,
new-job eligibility and existing caption, resume and retry behavior. Live login
and activation are completed only when the user runs the command on Windows.
