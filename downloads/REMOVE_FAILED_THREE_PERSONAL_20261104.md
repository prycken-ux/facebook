# Permanent removal of three unsuccessful personal logins

The user confirms fb24, fb25 and fb26 did not log in or connect, then explicitly
requests deletion of all their local information, superseding the earlier backup
proposal. This standalone command permanently deletes only those three profiles,
video directories, exact login shortcuts and the dedicated onboarding controllers
and caches. It removes their registrations, reservation batch and related entries
from root/log JSON documents and existing JSON backups, including interrupted
JSON temporary files. Mixed backups retain other accounts. It creates no backup
of the deleted account data. The generic uploader and other account records stay.

It first validates the original three-account reservation and file scope, plans
all JSON changes, refuses links/reparse paths and unknown ownership, acquires the
existing upload locks and gracefully closes only the three specific browser
profiles. Live locks remain blocking. It never force-kills Chrome or Python and
never sends a Facebook request or deletes a Facebook account on the platform.

A temporary progress marker contains only this removal scope and is deleted on
completion. It permits safe reruns after an interrupted partial deletion. The
final pass verifies there are no remaining planned removals/JSON updates. A repeat
on a clean installation is a no-op. Reused numbers without this original batch or
an in-progress cleanup marker are not deleted.

Local fixtures cover permanent deletion, preservation of old sessions/config,
mixed backup sanitization, original-batch ownership, window/lock failures,
interrupted cleanup, malformed JSON and symlink rejection. No local fixture
represents execution on the user's Windows computer.
