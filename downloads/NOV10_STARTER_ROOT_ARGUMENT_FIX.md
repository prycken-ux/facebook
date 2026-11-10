The Nov 10 starter omitted the upload root when launching publish_today_20261110.py. The worker expects argv[1] to be the root, so it interpreted --real-footage as the root and stopped at its Windows/root guard before creating or publishing a batch.

Pass the resolved root before --real-footage. Retain the unchanged pinned package, footage confirmation, date and identity guards, dated account exclusions, existing batch pointer, claims and comment records. The corrected starter resumes the same daily manifest if one already exists.

Validation: assert exact child argv and launch a real child Python process that checks root/flag ordering; preserve fixture config/state. Existing installer rollback, policy date boundary and frozen-batch resumption tests also run. No live Windows/Facebook publication is claimed by these local checks.
