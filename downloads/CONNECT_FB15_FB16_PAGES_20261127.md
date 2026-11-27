# FB15 and FB16: ten unique managed Pages, November 27

The user supplied five lines for each account, but the last two original fb15 lines shared ID `61596851483106` and used the names Hailev Chapman and Hailey Chapman. The user then supplied **Hailey Joyce / 61596554106097** as the missing fifth distinct Page. The final mapping below contains ten unique IDs; Hailey Chapman is registered once under the last supplied spelling. No duplicate or guessed fifth target is created.

| Account | Target | Page name | Page ID |
| --- | --- | --- | --- |
| fb15 | page01 | Hannah Cruz | 61596516877551 |
| fb15 | page02 | Gregory Slater | 61596466899962 |
| fb15 | page03 | Hannah Butler | 61596641942170 |
| fb15 | page04 | Hailey Chapman | 61596851483106 |
| fb15 | page05 | Hailey Joyce | 61596554106097 |
| fb16 | page01 | Gerald Eaton | 61596291677565 |
| fb16 | page02 | Grace Short | 61596536796977 |
| fb16 | page03 | Grace Collier | 61596564485485 |
| fb16 | page04 | Grace Hampton | 61596572945160 |
| fb16 | page05 | George Lester | 61596728488394 |

The Windows connector `connect_fb15_fb16_pages_20261127.py` uses the existing `E:\FB-AutoUpload` core 2.47 and original `profiles\fb15` / `profiles\fb16`. For each Page it creates `videos\<account>\<target>\inbox`, `completed` and `failed`. Locale query parameters are dropped from the canonical numeric-ID URL. The fb15/page05 identity comes exclusively from the user's later reply, not from copying page04. The report preserves the duplicate-resolution note.

The connector uses the same safeguards as the fb08/fb14 registration tool: validate all supplied targets and owner profiles first; refuse mismatched slots, cross-account Page-ID collisions and conflicting comment bindings; preserve original personal/other target settings, login profiles and media; acquire the existing worker locks and refuse active FB work; preserve known IG processes using the shared FB interpreter. Only the actual contiguous Windows venv parent chain is exempted, with argument and creation-time checks. No browser or process is opened/closed for identity switching and no worker is terminated.

New Page entries use the existing `page_flow_configured` workflow and `enabled=false` until their own identity/preparation checks. Already matching targets retain their exact enabled/prepared/custom settings. The current pause file is validated and no paused owner is restored. In particular, registration does not invent a new global fb16 resumption; an existing effective resumption is preserved. Future publication must apply the user's current allowed-account scope and verify each Page identity.

The common caption is verified against the latest valid effective content revision in `publication_preferences.json`. Existing `post_comment_config.json` receives the ten new bindings while retaining enabled/automatic-send/future-only and other settings. When that legacy file is absent, the obsolete sender is not created; the existing dated publication pipeline binds the authorized original comment to the exact video. The connector does not change caption/comment text or assert a source/AI label for unknown future material. Video confirmation and own-comment reload verification remain required in the next authorized batch.

Config, legacy comment bindings and the report are backed up before atomic replacement, and failed writes roll back their original bytes. Repeated runs preserve existing material and configuration bytes. Destination links, concurrent edits and existing locks are refused without overwriting them. Old 58-target manifests and prior fb08/fb14 registrations, comments and reports remain unchanged. Newly registered targets need a new material scope; they are not appended to an old frozen batch.

Report: `E:\FB-AutoUpload\logs\connect-fb15-fb16-pages-20261127.json`. Backup prefix: `backups\connect-fb15-fb16-pages-...`. This step registers configuration and creates local folders only; it does not publish videos, send comments, verify live Page rights, modify IG, change schedules or create replacement login profiles.

Forty-four local checks passed: 19 fb15/fb16 cases (including duplicate resolution, the later Joyce ID, preservation of the prior fb08/fb14 setup, transaction/process protections and freezing exact current caption/comment jobs with an already authorized fb16 resumption), plus the existing 17 fb08/fb14 and eight fb09 registration checks. The Windows connector still needs to run on the user's original computer; these are not live publication/identity proofs.
