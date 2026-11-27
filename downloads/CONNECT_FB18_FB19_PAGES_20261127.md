# FB18 and FB19: ten new managed Pages, November 27

This connector registers exactly the ten Pages supplied by the user, in the supplied order. It uses the existing `E:\FB-AutoUpload` Windows core 2.47 and original login profiles. The current work is local configuration and folder preparation; it does not upload videos, send comments, open Chrome, switch live identities, terminate processes or create scheduled tasks.

| Account | Target | Page name | Numeric Page ID |
| --- | --- | --- | --- |
| fb18 | page01 | Genesis Franco | 61596537516729 |
| fb18 | page02 | George Hamilton | 61596767336826 |
| fb18 | page03 | George Bishop | 61596809964895 |
| fb18 | page04 | Gary McKinney | 61596831623934 |
| fb18 | page05 | Gary Dominguez | 61596840203585 |
| fb19 | page01 | Cefruthi Brosheldplurd | 61596461206832 |
| fb19 | page02 | Cespuslocro Neftgangping | 61596745082806 |
| fb19 | page03 | Ceftswoskami Shomprublu | 61596826679349 |
| fb19 | page04 | Cetbrildgladru Swumblartflo | 61596838498947 |
| fb19 | page05 | Bruspaliglo Guremti | 61596951625627 |

All ten IDs are distinct, including against the twenty earlier supplied fb08/fb14/fb15/fb16 IDs. Canonical URLs retain the numeric identity and omit the locale query. Each target gets `videos\<account>\<pageNN>\inbox`, `completed`, and `failed`, sharing the original `profiles\fb18` or `profiles\fb19`. Original personal targets, other Pages, preparation flags, login data, videos and publication/comment ledgers are preserved. Newly added entries use `page_flow_configured` with `enabled=false` until their own identity and video preparation checks. Existing matching entries retain their enabled/prepared/custom flags.

The connector validates all ten target bindings and owner profiles, cross-account Page-ID uniqueness, target/comment conflicts, destination links and current pause rules before writing configuration. It inherits the current validated authorized common caption and corrected first comment. Existing legacy per-video comment targets are extended without changing enabled/automatic-send/future-only switches; a missing legacy sender is not created. It does not invent or change a global fb18 resumption, infer unknown video AI status or replace any common text with an older revision. Future publication follows the current allowed-account scope and exact Page actor, video and own-comment reload checks.

Active FB work or original worker locks block the registration without killing the task. Known IG processes remain separate even when using the FB interpreter. Only the current exact contiguous venv redirector parent chain is exempted, with creation-time and argument checks; sibling installers and reused PIDs remain blockers. Changed config, comment bindings and the report are backed up and atomically written together; failures restore their original bytes. Existing media, external concurrent edits and linked destinations are not overwritten.

The prior fb08/fb14 and fb15/fb16 config entries, comment targets and registration reports remain unchanged. The old 58-target frozen manifests remain immutable; a future batch must use the expanded target scope. Adding these ten makes **30 unique Page links received** across six accounts, not proof that all three Windows commands have already run. No fb20 Page has been supplied or silently inferred.

Report: `E:\FB-AutoUpload\logs\connect-fb18-fb19-pages-20261127.json`. Backup prefix: `backups\connect-fb18-fb19-pages-...`.

Sixty-two local checks passed: 18 fb18/fb19 cases, including preservation of the prior twenty target/comment bindings and reports, plus 44 prior registration regressions. The new cases also cover exact IDs, all folders, common caption/comment batch binding under an already authorized fb18 resumption, idempotence, conflicts, locks, pause/content/link checks, rollback, concurrent changes, IG classification and Windows venv ancestry. These are local fixture/configuration checks; live Page rights, Windows execution, video publication and first-comment success remain to be verified on the original computer.
