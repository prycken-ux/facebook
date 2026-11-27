# FB08 and FB14: ten new managed Pages, November 27

The user supplied these two groups and explicitly said to connect these first. This registration is restricted to ten Pages, independently of the unresolved total for the other requested accounts. It runs on the existing `E:\FB-AutoUpload` Windows installation with uploader core 2.47. It performs local configuration and directory setup only; it does not open a browser, publish a video, send a comment, schedule a task or claim any new Page identity has been verified.

| Account | Target | Page name | Numeric Page ID |
| --- | --- | --- | --- |
| fb08 | page01 | Cleblosswu Poswartslolt | 61596581349898 |
| fb08 | page02 | Clalnongru Calsluchaser | 61596636007799 |
| fb08 | page03 | Cletruwe Storiglo | 61596732513142 |
| fb08 | page04 | Clatruspabro Frocloki | 61596813179840 |
| fb08 | page05 | Chismuglepleng Terspuntpremfrald | 61596875847318 |
| fb14 | page01 | Chikuckcleshi Stucruwe | 61596692195025 |
| fb14 | page02 | Chelretre Bochomil | 61596417496995 |
| fb14 | page03 | Checharige Niblidrabro | 61596777031514 |
| fb14 | page04 | Chemosharert Granuru | 61596810479819 |
| fb14 | page05 | Chemfrordslisto Crecrigu | 61596934854640 |

Each canonical URL is `https://www.facebook.com/profile.php?id=<Page ID>`; the supplied locale query does not change identity and is omitted. The input order determines page01–page05. A collision with a different existing target is refused rather than silently renumbered. Existing registrations of the same ID/name retain all enabled/prepared/custom flags and bytes on repeat.

Every target has `videos\<account>\<pageNN>\inbox`, `completed` and `failed`, using the owner's existing `profiles\<account>` session. No separate Page login, blank replacement profile, credential collection or professional-account conversion is needed. Original personal targets and every unrelated target remain. Newly registered targets use the same `page_flow_configured` workflow and disabled-until-identity/preview state as existing Page onboarding. The tool does not fabricate preparation or identity proof, change existing AI settings or infer the source of future videos.

`upload_config.json` gains these Page entries. If `post_comment_config.json` already exists, its exact existing schema/future-only shape and target bindings are checked before the ten Page bindings are merged. Global enabled/automatic-send switches and other fields are retained; the legacy sender is not newly enabled or created when absent. The existing dated publication pipeline continues to bind the original authorized comment to the exact verified video and require the own comment after reload. Registration verifies the existing common-caption text against the latest valid effective content revision in `publication_preferences.json`; it never replaces the user's caption/comment with an older text. The report records this observed revision while future batches inherit the latest authorized policy at their own creation time.

All ten targets, cross-account Page-ID uniqueness, owner profiles, existing target conflicts, comment-target conflicts, current pause policy and destination links are validated before writing configuration. Existing FB workers block the change without being terminated. The Windows process check exempts only the current installer and its exact contiguous, creation-time-verified venv redirector parent chain, never a sibling installer or reused PID. Known IG commands with their own IG workspace marker are preserved even when using the FB Python interpreter. No Chrome/Python process is killed. Existing worker locks are preserved.

Config, legacy comment bindings and the registration report are backed up together before changed files are atomically replaced. A write failure restores their exact original bytes; newly created empty authorized directories may remain and can be reused on rerun. The tool checks for concurrent configuration edits before committing. Source videos, login profiles, registry, publication/comment ledgers, paused accounts and existing frozen plans are not modified. It does not rewrite the old 58-target batch or add new Pages to its immutable source mapping. A future new batch must use the newly registered target scope, rather than rerunning the old 58-target distributor against a larger set.

Windows report: `E:\FB-AutoUpload\logs\connect-fb08-fb14-pages-20261127.json`. Backup directory: `backups\connect-fb08-fb14-pages-<timestamp>-<id>`. The report is hash-checked and lists the ten Page IDs, shared profiles, inbox paths and inherited content/comment policy. Registration is not proof of live Page rights or publication success; those checks happen when preparing/publishing the next authorized material batch.

Twenty-five local checks passed: 17 new registration/process cases plus eight existing fb09 Page-registration regressions. They cover all supplied IDs and directories, preservation of profiles/personal flags/media/old plans, comment-target merging, idempotence, last-slot/cross-account conflicts, active worker/lock refusal, concurrent edit refusal, destination-link refusal, pause/content refusal, multi-file rollback, Windows parent-chain/IG classification and freezing ten new target jobs with the exact current caption/comment through the existing publication pipeline. No live Facebook upload or comment was performed, and the user's Windows setup remains to be executed.
